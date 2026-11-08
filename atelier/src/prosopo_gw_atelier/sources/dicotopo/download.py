"""On-demand download and indexing of DicoTopo departments through the job queue.

The dictionary is fetched one department at a time from the public ``chartes/dico-topo``
repository into ``<cache>/dicotopo/DTxx.xml``; nothing from DicoTopo is shipped with
the package. Set ``PROSOPO_GW_ATELIER_DICOTOPO_RAW`` (same ``{dept}`` placeholder) to
point the download at another server, for instance a local one.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from prosopo_gw_atelier.sources.base import SourceError
from prosopo_gw_atelier.sources.dicotopo.index import DicoTopoIndex
from prosopo_gw_atelier.sources.fetch import Opener, default_opener, download, get_json
from prosopo_gw_atelier.sources.queue import Job, SourceQueue

DICOTOPO = "dicotopo"
RAW_URL = "https://raw.githubusercontent.com/chartes/dico-topo/master/data/DT{dept}/DT{dept}.xml"
CONTENTS_URL = "https://api.github.com/repos/chartes/dico-topo/contents/data"
RAW_ENV = "PROSOPO_GW_ATELIER_DICOTOPO_RAW"
MAX_DEPARTMENT_BYTES = 200 * 1024 * 1024
_COVERAGE_FILE = "coverage.json"
logger = logging.getLogger(__name__)

# Used only when the coverage list is unknown (no network, nothing cached): well-formed
# French department codes, 01-95 except 20, Corsica (2A/2B) and overseas (971-976).
_FALLBACK_CODE = re.compile(r"^(?:0[1-9]|1\d|2[1-9]|[3-8]\d|9[0-5]|2[AB]|97[1-6])$")


def _directory(cache: Path) -> Path:
    return cache / DICOTOPO


def _raw_url(department: str) -> str:
    template = os.environ.get(RAW_ENV) or RAW_URL
    if "{dept}" not in template:
        logger.warning("%s ignorée : le motif doit contenir {dept}", RAW_ENV)
        template = RAW_URL
    return template.replace("{dept}", department)


def _normalise(department: str) -> str:
    return department.strip().upper()


def _check_department(department: str, covered: Sequence[str] | None = None) -> str:
    code = _normalise(department)
    known = covered if covered else None
    ok = bool(_FALLBACK_CODE.match(code)) and (known is None or code in known)
    if not ok:
        raise SourceError(f"Département inconnu de DicoTopo : {department!r}.")
    return code


def coverage(
    cache: Path, *, refresh: bool = False, opener: Opener | None = None
) -> list[str]:
    """Departments available upstream, cached in ``<cache>/dicotopo/coverage.json``.

    Returns the cached list when present (unless ``refresh``); if the network fails the
    stale cache is kept, and ``[]`` is returned when there is none (coverage unknown).
    """
    path = _directory(cache) / _COVERAGE_FILE
    cached: list[str] | None = None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            cached = [str(d) for d in data]
    except (OSError, ValueError):
        cached = None
    if cached and not refresh:
        return cached
    try:
        entries = get_json(CONTENTS_URL, opener=opener)
    except SourceError:
        return cached or []
    found: list[str] = []
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", ""))
            if entry.get("type") == "dir" and re.fullmatch(r"DT[0-9A-Z]{2,3}", name):
                found.append(name[2:].upper())
    found.sort()
    if not found:
        return cached or []
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(found), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        logger.warning("Couverture DicoTopo non mise en cache", exc_info=True)
    return found


def request_download(
    queue: SourceQueue,
    departments: Iterable[str],
    *,
    covered: Sequence[str] | None = None,
) -> list[int]:
    """Queue one ``download`` job per department (priority 0, key ``DTxx``).

    ``covered`` is the coverage list; when empty or ``None`` only well-formed French
    department codes are accepted. Invalid codes raise before anything is queued.
    """
    codes = [_check_department(d, covered) for d in departments]
    return [queue.enqueue(DICOTOPO, "download", f"DT{c}", {}, 0) for c in codes]


def _department_of(job: Job) -> str:
    key = job.key
    if not key.startswith("DT"):
        raise SourceError(f"Clé de tâche DicoTopo invalide : {key!r}.")
    return key[2:]


def _wrap(opener: Opener | None) -> Opener:
    inner = opener or default_opener

    def opened(request: urllib.request.Request, timeout: float) -> BinaryIO:
        try:
            return inner(request, timeout)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                exc.close()
                raise SourceError("département absent de DicoTopo") from exc
            raise

    return opened


def handle_download(
    job: Job, *, cache: Path, queue: SourceQueue, opener: Opener | None = None
) -> None:
    """Fetch ``DTxx.xml`` into the cache, then queue its ``index`` job."""
    department = _check_department(_department_of(job))
    target = _directory(cache) / f"DT{department}.xml"
    download(
        _raw_url(department),
        target,
        opener=_wrap(opener),
        max_bytes=MAX_DEPARTMENT_BYTES,
    )
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    queue.enqueue(DICOTOPO, "index", f"DT{department}", {"downloaded_at": stamp}, 0)


def handle_index(
    job: Job,
    *,
    cache: Path,
    index: DicoTopoIndex,
    queue: SourceQueue | None = None,
) -> None:
    """Index a downloaded department; a missing or partial file is an error.

    With ``queue``, the cached match results for that department are deleted so
    the projects match it again.
    """
    department = _check_department(_department_of(job))
    xml = _directory(cache) / f"DT{department}.xml"
    part = xml.with_suffix(xml.suffix + ".part")
    if part.exists() or not xml.is_file():
        raise SourceError(
            f"Fichier DicoTopo DT{department} absent ou incomplet "
            "(relancez le téléchargement)."
        )
    stamp = job.payload.get("downloaded_at")
    downloaded_at = (
        stamp
        if isinstance(stamp, str)
        else datetime.now(UTC).isoformat(timespec="seconds")
    )
    index.add_department(department, xml, downloaded_at)
    if queue is not None:
        queue.clear_results(DICOTOPO, department)


def remove_department(
    cache: Path,
    index: DicoTopoIndex,
    department: str,
    *,
    queue: SourceQueue | None = None,
) -> None:
    """Drop a department from the index and delete its cached file.

    The code is validated first (``SourceError``). With ``queue``, pending and failed
    jobs for the department are cancelled; a job already running may still finish and
    re-index it.
    """
    code = _check_department(department)
    if queue is not None:
        queue.cancel(DICOTOPO, f"DT{code}")
    index.remove(code)
    xml = _directory(cache) / f"DT{code}.xml"
    xml.unlink(missing_ok=True)
    xml.with_suffix(xml.suffix + ".part").unlink(missing_ok=True)
