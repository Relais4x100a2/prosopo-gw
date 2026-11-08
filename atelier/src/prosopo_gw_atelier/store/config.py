"""Local user configuration and the shared source cache location."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from prosopo_gw_atelier.store.paths import data_dir

_KNOWN = ("dicotopo_api", "geonames_username")


def cache_dir() -> Path:
    """Shared cache for downloaded external sources, created on demand."""
    path = data_dir() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return data_dir() / "config.json"


@dataclass
class LocalConfig:
    dicotopo_api: bool = False
    geonames_username: str | None = None
    extra: dict[str, object] = field(default_factory=dict)


def load_config(path: Path | None = None) -> LocalConfig:
    """Read the config; a missing or invalid file gives the defaults."""
    target = path or config_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return LocalConfig()
    if not isinstance(raw, dict):
        return LocalConfig()
    user = raw.get("geonames_username")
    return LocalConfig(
        dicotopo_api=raw.get("dicotopo_api") is True,
        geonames_username=user if isinstance(user, str) and user else None,
        extra={k: v for k, v in raw.items() if k not in _KNOWN},
    )


def save_config(config: LocalConfig, path: Path | None = None) -> None:
    """Write the config atomically with 0600 permissions."""
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, object] = dict(config.extra)
    data["dicotopo_api"] = config.dicotopo_api
    data["geonames_username"] = config.geonames_username
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        with contextlib.suppress(OSError):
            os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
