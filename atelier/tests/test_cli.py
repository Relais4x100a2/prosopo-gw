import shutil
import socket
import sqlite3
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from prosopo_gw_atelier import cli
from prosopo_gw_atelier.refdata import RefData, load_refdata
from prosopo_gw_atelier.store import paths

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Whatever happens, never touch the real user data dir.
    monkeypatch.setenv(paths.HOME_ENV, str(tmp_path / "home"))


def mini_ref() -> RefData:
    return load_refdata(FIXTURES / "refdata_mini")


class Recorder:
    def __init__(self) -> None:
        self.served: list[tuple[FastAPI, int]] = []
        self.opened: list[str] = []

    def launch(self, app: FastAPI, port: int, on_started: Callable[[], None]) -> None:
        self.served.append((app, port))
        on_started()

    def open(self, url: str) -> bool:
        self.opened.append(url)
        return True


def offline_opener(request: urllib.request.Request, timeout: float) -> BinaryIO:
    raise urllib.error.URLError("offline in tests")


def run(argv: list[str], recorder: Recorder) -> int:
    # The sources' background threads get an opener that never reaches a network.
    return cli.main(
        argv,
        launcher=recorder.launch,
        open_browser=recorder.open,
        load_ref=mini_ref,
        opener=offline_opener,
    )


@pytest.fixture
def gw(tmp_path: Path) -> Path:
    target = tmp_path / "bases" / "lieux_varies.gw"
    target.parent.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "lieux_varies.gw", target)
    return target


def test_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    recorder = Recorder()
    absent = tmp_path / "absent.gw"
    assert run([str(absent), "--no-browser"], recorder) == 2
    err = capsys.readouterr().err
    assert f"Fichier introuvable : {absent}" in err
    assert recorder.served == []
    assert not (tmp_path / "home").exists()


def test_launch_with_data_dir_and_port(
    tmp_path: Path, gw: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    recorder = Recorder()
    data = tmp_path / "donnees"
    with socket.socket() as probe:  # a free port, not a fixed one
        probe.bind(("127.0.0.1", 0))
        wanted = probe.getsockname()[1]
    code = run([str(gw), "--port", str(wanted), "--data-dir", str(data)], recorder)
    assert code == 0
    ((app, port),) = recorder.served
    assert port == wanted
    assert recorder.opened == [f"http://127.0.0.1:{wanted}/"]
    assert f"http://127.0.0.1:{wanted}/" in capsys.readouterr().out
    assert (data / "referentiel.sqlite").is_file()
    assert any((data / "projets").glob("*.sqlite"))
    assert not (tmp_path / "home").exists()
    # The app was built on that project (its registry is closed after serving,
    # so only routes that do not touch it are checked here).
    assert TestClient(app, base_url="http://127.0.0.1").get("/").status_code == 200


def test_version_1_registry_is_migrated_on_launch(tmp_path: Path, gw: Path) -> None:
    data = tmp_path / "d"
    data.mkdir()
    conn = sqlite3.connect(data / "referentiel.sqlite")
    conn.executescript((FIXTURES / "registry_v1.sql").read_text("utf-8"))
    conn.close()
    assert run([str(gw), "--no-browser", "--data-dir", str(data)], Recorder()) == 0
    conn = sqlite3.connect(data / "referentiel.sqlite")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
    conn.close()
    assert list(data.glob("referentiel.v1-*.sqlite"))


def test_no_browser_and_free_port(tmp_path: Path, gw: Path) -> None:
    recorder = Recorder()
    code = run([str(gw), "--no-browser", "--data-dir", str(tmp_path / "d")], recorder)
    assert code == 0
    ((_, port),) = recorder.served
    assert recorder.opened == []
    assert 0 < port < 65536
    # The port is free: it can be bound.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))


def test_default_data_dir(tmp_path: Path, gw: Path) -> None:
    recorder = Recorder()
    assert run([str(gw), "--no-browser"], recorder) == 0
    assert (tmp_path / "home" / "referentiel.sqlite").is_file()
    assert (tmp_path / "home" / "projets").is_dir()


def test_unreadable_base(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    folder = tmp_path / "dossier.gw"
    folder.mkdir()
    recorder = Recorder()
    assert run([str(folder), "--no-browser"], recorder) == 2
    assert "Fichier introuvable" in capsys.readouterr().err


def test_port_already_in_use(
    tmp_path: Path, gw: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    recorder = Recorder()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        port = sock.getsockname()[1]
        argv = [str(gw), "--port", str(port), "--data-dir", str(tmp_path / "d")]
        assert run(argv, recorder) == 2
    assert f"Port {port} déjà utilisé" in capsys.readouterr().err
    assert recorder.served == []


def test_worker_runs_with_the_served_app(tmp_path: Path, gw: Path) -> None:
    recorder = Recorder()
    assert (
        run([str(gw), "--no-browser", "--data-dir", str(tmp_path / "d")], recorder) == 0
    )
    ((app, _),) = recorder.served
    runtime = app.state.atelier.sources
    assert runtime is not None
    assert not runtime.worker.running
    with TestClient(app, base_url="http://127.0.0.1"):
        assert runtime.worker.running
    assert not runtime.worker.running


def test_served_runtime_uses_the_injected_opener(tmp_path: Path, gw: Path) -> None:
    recorder = Recorder()
    assert (
        run([str(gw), "--no-browser", "--data-dir", str(tmp_path / "d")], recorder) == 0
    )
    ((app, _),) = recorder.served
    runtime = app.state.atelier.sources
    assert runtime is not None
    assert runtime.opener is offline_opener
