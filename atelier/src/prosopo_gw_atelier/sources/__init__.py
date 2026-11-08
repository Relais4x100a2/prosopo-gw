"""Sources externes de lieux et file de fond.

``SourceRuntime`` regroupe ce que l'application web partage avec le fil de fond :
la file de tâches, la configuration locale, les sources (DicoTopo), leur index et
le ``Worker`` qui exécute les tâches (téléchargement, indexation, appariement).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from prosopo_gw_atelier.refdata import RefData
from prosopo_gw_atelier.sources.base import Source
from prosopo_gw_atelier.sources.dicotopo import download as dicotopo_download
from prosopo_gw_atelier.sources.dicotopo.index import DicoTopoIndex
from prosopo_gw_atelier.sources.dicotopo.source import DicoTopoSource
from prosopo_gw_atelier.sources.fetch import Opener
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


@dataclass
class SourceRuntime:
    """Queue, config, sources, index and worker of one atelier run.

    ``sources`` is replaced (not mutated) when the config changes: pass it again
    to ``Project.attach_sources``.
    """

    queue: SourceQueue
    config: LocalConfig
    config_path: Path
    cache: Path
    index: DicoTopoIndex
    ref: RefData
    sources: dict[str, Source]
    opener: Opener | None = None
    limiter: RateLimiter | None = None
    worker: Worker = field(init=False)

    def __post_init__(self) -> None:
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
        runtime = cls(
            queue=SourceQueue(cache / "queue.sqlite"),
            config=config,
            config_path=config_path,
            cache=cache,
            index=index,
            ref=ref,
            sources={},
            opener=opener,
            limiter=limiter,
        )
        runtime.sources = {DICOTOPO: runtime._dicotopo()}
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

        return {
            (DICOTOPO, "match"): match,
            (DICOTOPO, "download"): download,
            (DICOTOPO, "index"): index,
        }

    def set_api_enabled(self, enabled: bool) -> None:
        """Allow or forbid the DicoTopo API; written to ``config.json``."""
        self.config.dicotopo_api = enabled
        save_config(self.config, self.config_path)
        self.sources = {**self.sources, DICOTOPO: self._dicotopo()}

    def coverage(self) -> list[str]:
        return dicotopo_download.coverage(self.cache, opener=self.opener)

    def start(self) -> None:
        self.queue.resume()
        self.worker.start()

    def stop(self) -> None:
        self.worker.stop()


__all__ = ["DICOTOPO", "SourceRuntime"]
