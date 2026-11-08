"""On-demand download and indexing of GeoNames country files through the job queue.

Source verified on 2026-11-08 (HEAD requests and ``readme.txt`` only):

- ``https://download.geonames.org/export/dump/`` serves ``<CC>.zip`` (one ``<CC>.txt``
  inside) and the common tables ``admin1CodesASCII.txt``, ``admin2Codes.txt`` and
  ``countryInfo.txt``. Every file answers ``Content-Length`` and ``Last-Modified``.
- Sizes: ``CA.zip`` 8 MB, ``FR.zip`` 7 MB, ``GB.zip`` 3.6 MB, ``US.zip`` 71 MB;
  ``admin2Codes.txt`` 2.4 MB, ``admin1CodesASCII.txt`` 150 kB,
  ``countryInfo.txt`` 32 kB.
- Licence: Creative Commons Attribution 4.0 (``readme.txt``); credit GeoNames.

Nothing of it is shipped with the package. Set ``PROSOPO_GW_ATELIER_GEONAMES_DUMP`` to
an http(s) URL ending in ``/`` to point the download at another server (a local one,
say); an invalid value is ignored with a logged warning.

Country codes are two letters, uppercased. They are checked against the cached
``countryInfo.txt`` when it is there; before that only the format is checked, and an
unknown code ends as a permanent "absent from GeoNames" error (HTTP 404) once the
common files, queued first, are in. The extraction date handed to the index is the
HTTP ``Last-Modified`` date of the zip (else the download date), kept in a
``<CC>.date`` sidecar so a later re-index reuses it.
"""

from __future__ import annotations

import email.utils
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path
from typing import BinaryIO

from prosopo_gw_atelier.sources.base import PermanentSourceError, SourceError
from prosopo_gw_atelier.sources.fetch import (
    USER_AGENT,
    Opener,
    default_opener,
    download,
)
from prosopo_gw_atelier.sources.geonames.index import GeoNamesIndex, read_country_info
from prosopo_gw_atelier.sources.queue import Job, SourceQueue

GEONAMES = "geonames"
DUMP_URL = "https://download.geonames.org/export/dump/"
DUMP_ENV = "PROSOPO_GW_ATELIER_GEONAMES_DUMP"
COMMON_FILES = ("admin1CodesASCII.txt", "admin2Codes.txt", "countryInfo.txt")
MAX_COUNTRY_BYTES = 600 * 1024 * 1024
MAX_COMMON_BYTES = 50 * 1024 * 1024
_COUNTRY = re.compile(r"^[A-Z]{2}$")
logger = logging.getLogger(__name__)


def _directory(cache: Path) -> Path:
    return cache / GEONAMES


def _dump_url() -> str:
    override = os.environ.get(DUMP_ENV)
    if override:
        scheme = urllib.parse.urlparse(override).scheme.lower()
        if scheme in ("http", "https") and override.endswith("/"):
            return override
        logger.warning(
            "%s ignorée : une URL http(s) finissant par / est attendue", DUMP_ENV
        )
    return DUMP_URL


def _check_country(country: str, cache: Path | None = None) -> str:
    code = country.strip().upper()
    if not _COUNTRY.fullmatch(code):
        raise SourceError(f"Code pays GeoNames invalide : {country!r}.")
    if cache is not None:
        info = _directory(cache) / "countryInfo.txt"
        try:
            known = read_country_info(info)
        except (OSError, ValueError):
            known = {}
        if known and code not in known:
            raise SourceError(f"Pays inconnu de GeoNames : {country!r}.")
    return code


def request_country(
    queue: SourceQueue, country: str, *, cache: Path | None = None
) -> list[int]:
    """Queue the downloads then the ``index`` job for ``country`` (priority 0).

    The common files already in ``cache`` are not fetched again. An invalid code raises
    before anything is queued.
    """
    code = _check_country(country, cache)
    ids: list[int] = []
    for name in COMMON_FILES:
        if cache is None or not (_directory(cache) / name).is_file():
            ids.append(queue.enqueue(GEONAMES, "download", name, {}, 0))
    ids.append(queue.enqueue(GEONAMES, "download", f"{code}.zip", {}, 0))
    ids.append(queue.enqueue(GEONAMES, "index", code, {}, 0))
    return ids


def _wrap(opener: Opener | None, seen: dict[str, str] | None = None) -> Opener:
    inner = opener or default_opener

    def opened(request: urllib.request.Request, timeout: float) -> BinaryIO:
        try:
            response = inner(request, timeout)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                exc.close()
                raise PermanentSourceError("fichier absent de GeoNames") from exc
            raise
        if seen is not None:
            headers = getattr(response, "headers", None)
            modified = headers.get("Last-Modified") if headers is not None else None
            if modified:
                seen["last-modified"] = str(modified)
        return response

    return opened


def _http_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC)
    return parsed.date().isoformat()


def _sidecar(cache: Path, country: str) -> Path:
    return _directory(cache) / f"{country}.date"


def handle_download(job: Job, *, cache: Path, opener: Opener | None = None) -> None:
    """Fetch one common file or one country zip into ``<cache>/geonames/``."""
    name = job.key
    country: str | None = None
    if name in COMMON_FILES:
        limit = MAX_COMMON_BYTES
    elif name.endswith(".zip"):
        country = _check_country(name[:-4], cache)
        if name != f"{country}.zip":
            raise SourceError(f"Clé de tâche GeoNames invalide : {name!r}.")
        limit = MAX_COUNTRY_BYTES
    else:
        raise SourceError(f"Clé de tâche GeoNames invalide : {name!r}.")
    seen: dict[str, str] = {}
    download(
        _dump_url() + name,
        _directory(cache) / name,
        opener=_wrap(opener, seen),
        max_bytes=limit,
    )
    if country is not None:
        stamp = _http_date(seen.get("last-modified")) or date.today().isoformat()
        _sidecar(cache, country).write_text(stamp, encoding="utf-8")


def handle_index(job: Job, *, cache: Path, index: GeoNamesIndex) -> None:
    """Index a downloaded country; a missing or partial file is an error."""
    country = _check_country(job.key)
    directory = _directory(cache)
    zip_path = directory / f"{country}.zip"
    files = [zip_path, *(directory / name for name in COMMON_FILES)]
    for path in files:
        part = path.with_suffix(path.suffix + ".part")
        if part.exists() or not path.is_file():
            raise SourceError(
                f"Fichier GeoNames {path.name} absent ou incomplet "
                "(relancez le téléchargement)."
            )
    try:
        extracted = _sidecar(cache, country).read_text(encoding="utf-8").strip()
        date.fromisoformat(extracted)
    except (OSError, ValueError):
        extracted = (
            datetime.fromtimestamp(zip_path.stat().st_mtime, UTC).date().isoformat()
        )
    index.build(
        country,
        zip_path,
        directory / "admin1CodesASCII.txt",
        directory / "admin2Codes.txt",
        extracted,
    )


def remote_size(url: str, *, opener: Opener | None = None) -> int | None:
    """``Content-Length`` of ``url`` via ``HEAD``; ``None`` on any failure."""
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT}, method="HEAD"
    )
    try:
        with (opener or default_opener)(request, 30.0) as response:
            headers = getattr(response, "headers", None)
            value = headers.get("Content-Length") if headers is not None else None
            return int(value) if value is not None else None
    except Exception as exc:
        if isinstance(exc, urllib.error.HTTPError):
            exc.close()
        return None


def country_size(country: str, *, opener: Opener | None = None) -> int | None:
    """Remote size of ``<CC>.zip`` (for a "this will download N MB" notice)."""
    return remote_size(_dump_url() + f"{_check_country(country)}.zip", opener=opener)


def remove_country(
    cache: Path,
    index: GeoNamesIndex,
    country: str,
    *,
    queue: SourceQueue | None = None,
) -> None:
    """Drop a country from the index and delete its cached zip and date.

    The common files stay. With ``queue``, pending and failed jobs for the country are
    cancelled; a job already running may still finish and re-index it.
    """
    code = _check_country(country)
    if queue is not None:
        queue.cancel(GEONAMES, code)
        queue.cancel(GEONAMES, f"{code}.zip")
    index.remove(code)
    zip_path = _directory(cache) / f"{code}.zip"
    zip_path.unlink(missing_ok=True)
    zip_path.with_suffix(".zip.part").unlink(missing_ok=True)
    _sidecar(cache, code).unlink(missing_ok=True)
