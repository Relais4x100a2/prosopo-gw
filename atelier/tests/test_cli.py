import shutil
import socket
from collections.abc import Callable
from pathlib import Path

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


def run(argv: list[str], recorder: Recorder) -> int:
    return cli.main(
        argv, launcher=recorder.launch, open_browser=recorder.open, load_ref=mini_ref
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
    code = run([str(gw), "--port", "8765", "--data-dir", str(data)], recorder)
    assert code == 0
    ((app, port),) = recorder.served
    assert port == 8765
    assert recorder.opened == ["http://127.0.0.1:8765/"]
    assert "http://127.0.0.1:8765/" in capsys.readouterr().out
    assert (data / "referentiel.sqlite").is_file()
    assert any((data / "projets").glob("*.sqlite"))
    assert not (tmp_path / "home").exists()
    # The app was built on that project (its registry is closed after serving,
    # so only routes that do not touch it are checked here).
    assert TestClient(app, base_url="http://127.0.0.1").get("/").status_code == 200


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
