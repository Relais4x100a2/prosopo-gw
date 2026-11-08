from __future__ import annotations

import json
import os
import stat
import urllib.request
from pathlib import Path

import pytest

from prosopo_gw_atelier.store.config import (
    LocalConfig,
    load_config,
    save_config,
)


def test_default_config_when_missing(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "nope.json")
    assert cfg.dicotopo_api is False
    assert cfg.geonames_username is None
    assert cfg.extra == {}


def test_invalid_json_gives_defaults(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    p.write_text("{not json", encoding="utf-8")
    assert load_config(p) == LocalConfig()
    p.write_text("[1, 2]", encoding="utf-8")
    assert load_config(p) == LocalConfig()


def test_round_trip_keeps_unknown_keys(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    p.write_text(
        json.dumps({"dicotopo_api": True, "future": {"a": 1}}), encoding="utf-8"
    )
    cfg = load_config(p)
    assert cfg.dicotopo_api is True
    cfg.geonames_username = "demo"
    save_config(cfg, p)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["future"] == {"a": 1}
    assert data["geonames_username"] == "demo"
    assert load_config(p) == cfg


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_config_file_is_private(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    save_config(LocalConfig(), p)
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_default_path_uses_home(atelier_home: Path) -> None:
    save_config(LocalConfig(dicotopo_api=True))
    assert load_config().dicotopo_api is True
    assert (atelier_home / "config.json").exists()


def test_network_is_forbidden_in_tests() -> None:
    with pytest.raises(RuntimeError):
        urllib.request.urlopen("http://example.invalid")
