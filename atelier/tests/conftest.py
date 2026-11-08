"""Shared fixtures: no network and no writes to the user's real data dir."""

from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import NoReturn

import pytest

from prosopo_gw_atelier.store.paths import HOME_ENV


def _refuse(*args: object, **kwargs: object) -> NoReturn:
    raise RuntimeError("network access is forbidden in tests")


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", _refuse)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", _refuse)


@pytest.fixture(autouse=True)
def atelier_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "atelier-home"
    monkeypatch.setenv(HOME_ENV, str(home))
    return home
