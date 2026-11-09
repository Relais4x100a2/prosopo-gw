"""Sources externes de lieux et file de fond.

``SourceRuntime`` regroupe ce que l'application web partage avec le fil de fond :
la file de tâches, la configuration locale, les sources (DicoTopo, GeoNames), leurs
index et le ``Worker`` qui exécute les tâches (téléchargement, indexation, appariement).

GeoNames : une seule ``GeoNamesSource`` et un seul ``RateLimiter`` (4 s) pour toute la
durée du runtime (le compteur de requêtes de l'API est protégé par un verrou propre à
l'instance). Index et fichiers dans ``<cache>/geonames/``, compteur de l'API dans
``<cache>/geonames/api_counter.json``. L'identifiant GeoNames est lu dans ``config``
(objet partagé) à chaque requête : le changer ne recrée pas la source.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from prosopo_gw_atelier.refdata import RefData
from prosopo_gw_atelier.sources.base import Source
from prosopo_gw_atelier.sources.dicotopo import download as dicotopo_download
from prosopo_gw_atelier.sources.dicotopo.index import DicoTopoIndex
from prosopo_gw_atelier.sources.dicotopo.source import DicoTopoSource
from prosopo_gw_atelier.sources.fetch import Opener
from prosopo_gw_atelier.sources.geonames import download as geonames_download
from prosopo_gw_atelier.sources.geonames.index import GeoNamesIndex
from prosopo_gw_atelier.sources.geonames.source import MIN_INTERVAL, GeoNamesSource
from prosopo_gw_atelier.sources.queue import (
    Job,
    JobKind,
    RateLimiter,
    SourceQueue,
    Worker,
    handle_match,
)
from prosopo_gw_atelier.store.config import LocalConfig, load_config, save_config

DICOTOPO = dicotopo_download.DICOTOPO
GEONAMES = geonames_download.GEONAMES
API_COUNTER = "api_counter.json"
COVERAGE_FAILED = "coverage.failed"
COVERAGE_RETRY_SECONDS = 3600


@dataclass
class SourceRuntime:
    """Queue, config, sources, indexes and worker of one atelier run.

    ``sources`` is replaced (not mutated) when the config changes: pass it again
    to ``Project.attach_sources`` (with ``geonames_index``). The GeoNames source is
    the same instance in every ``sources`` mapping.
    """

    queue: SourceQueue
    config: LocalConfig
    config_path: Path
    cache: Path
    index: DicoTopoIndex
    ref: RefData
    sources: dict[str, Source]
    geonames_index: GeoNamesIndex
    opener: Opener | None = None
    limiter: RateLimiter | None = None
    geonames_limiter: RateLimiter | None = None
    geonames: GeoNamesSource = field(init=False)
    worker: Worker = field(init=False)
    _refreshing: threading.Lock = field(init=False, default_factory=threading.Lock)

    def __post_init__(self) -> None:
        if self.geonames_limiter is None:
            self.geonames_limiter = RateLimiter(MIN_INTERVAL)
        self.geonames = GeoNamesSource(
            self.geonames_index,
            config=self.config,
            counter_path=self.cache / GEONAMES / API_COUNTER,
            opener=self.opener,
            limiter=self.geonames_limiter,
            queue=self.queue,
        )
        self.worker = Worker(self.queue, self._handlers())

    @classmethod
    def build(
        cls,
        directory: Path,
        ref: RefData,
        *,
        opener: Opener | None = None,
        limiter: RateLimiter | None = None,
    ) -> SourceRuntime:
        """Runtime whose cache and ``config.json`` live in ``directory``."""
        cache = directory / "cache"
        cache.mkdir(parents=True, exist_ok=True)
        config_path = directory / "config.json"
        config = load_config(config_path)
        index = DicoTopoIndex(cache / DICOTOPO / "index.sqlite")
        geonames_index = GeoNamesIndex(cache / GEONAMES)
        runtime = cls(
            queue=SourceQueue(cache / "queue.sqlite"),
            config=config,
            config_path=config_path,
            cache=cache,
            index=index,
            ref=ref,
            sources={},
            geonames_index=geonames_index,
            opener=opener,
            limiter=limiter,
        )
        runtime.sources = {DICOTOPO: runtime._dicotopo(), GEONAMES: runtime.geonames}
        return runtime

    def _dicotopo(self) -> DicoTopoSource:
        # One limiter for the whole run, kept across a config change.
        if self.limiter is None:
            self.limiter = RateLimiter(1.0)
        return DicoTopoSource(
            self.index,
            self.ref,
            api_enabled=self.config.dicotopo_api,
            opener=self.opener,
            limiter=self.limiter,
        )

    def _handlers(self) -> dict[tuple[str, JobKind], Callable[[Job], None]]:
        def match(job: Job) -> None:
            handle_match(job, source=self.sources[job.source], queue=self.queue)

        def download(job: Job) -> None:
            dicotopo_download.handle_download(
                job, cache=self.cache, queue=self.queue, opener=self.opener
            )

        def index(job: Job) -> None:
            dicotopo_download.handle_index(
                job, cache=self.cache, index=self.index, queue=self.queue
            )

        def geonames_download_job(job: Job) -> None:
            geonames_download.handle_download(job, cache=self.cache, opener=self.opener)

        def geonames_index_job(job: Job) -> None:
            # Clears the country's cached matches: the projects match it again.
            geonames_download.handle_index(
                job, cache=self.cache, index=self.geonames_index, queue=self.queue
            )

        return {
            (DICOTOPO, "match"): match,
            (DICOTOPO, "download"): download,
            (DICOTOPO, "index"): index,
            (GEONAMES, "match"): match,
            (GEONAMES, "download"): geonames_download_job,
            (GEONAMES, "index"): geonames_index_job,
        }

    def set_api_enabled(self, enabled: bool) -> None:
        """Allow or forbid the DicoTopo API; written to ``config.json``."""
        self.config.dicotopo_api = enabled
        save_config(self.config, self.config_path)
        self.sources = {**self.sources, DICOTOPO: self._dicotopo()}

    def set_geonames_username(self, username: str | None) -> None:
        """Set or clear the GeoNames user name; written to ``config.json`` only.

        The caller validates the value. The shared ``GeoNamesSource`` reads it from
        ``config`` at each request. Any change lifts a hold left by a refused
        user name (GeoNames code 10); with a user name, the failed GeoNames
        ``match`` jobs are retried too.
        """
        self.config.geonames_username = username or None
        save_config(self.config, self.config_path)
        self.queue.clear_credentials_rejection(
            GEONAMES, retry_failed=self.config.geonames_username is not None
        )

    def geonames_size(self, country: str) -> int | None:
        """Size of the cached ``<CC>.zip`` of ``country`` (``None`` if absent)."""
        path = self.cache / GEONAMES / f"{country}.zip"
        try:
            return path.stat().st_size
        except OSError:
            return None

    def coverage(self) -> list[str]:
        """Cached coverage only: never touches the network."""
        return dicotopo_download.cached_coverage(self.cache)

    def refresh_coverage(self) -> bool:
        """Fetch the coverage in a daemon thread unless it is cached or a fetch
        failed less than an hour ago (``coverage.failed`` holds the failure time).
        Returns whether a refresh was started."""
        directory = self.cache / DICOTOPO
        failed = directory / COVERAGE_FAILED
        if self.coverage():
            return False
        try:
            if time.time() - float(failed.read_text()) < COVERAGE_RETRY_SECONDS:
                return False
        except (OSError, ValueError):
            pass
        if not self._refreshing.acquire(blocking=False):
            return False  # a refresh is already running

        def run() -> None:
            try:
                found = dicotopo_download.coverage(
                    self.cache, refresh=True, opener=self.opener
                )
                if not found:
                    try:
                        directory.mkdir(parents=True, exist_ok=True)
                        tmp = failed.with_suffix(".tmp")
                        tmp.write_text(str(time.time()))
                        os.replace(tmp, failed)  # never seen half-written
                    except OSError:
                        pass
                else:
                    failed.unlink(missing_ok=True)
            finally:
                self._refreshing.release()

        threading.Thread(target=run, daemon=True).start()
        return True

    def start(self) -> None:
        self.queue.resume()
        self.worker.start()
        self.refresh_coverage()

    def stop(self) -> None:
        self.worker.stop()


__all__ = ["DICOTOPO", "GEONAMES", "SourceRuntime"]
