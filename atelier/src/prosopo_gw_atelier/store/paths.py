"""Where the atelier keeps its user data."""

from __future__ import annotations

import os
from pathlib import Path

import platformdirs

HOME_ENV = "PROSOPO_GW_ATELIER_HOME"


def data_dir() -> Path:
    """``$PROSOPO_GW_ATELIER_HOME`` when set and non-empty, else the user data dir."""
    home = os.environ.get(HOME_ENV)
    if home:
        return Path(home)
    return Path(platformdirs.user_data_dir("prosopo-gw-atelier"))


def registry_path() -> Path:
    """Path of the personal place registry."""
    return data_dir() / "referentiel.sqlite"
