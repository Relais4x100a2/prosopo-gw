"""
Tests unitaires du binaire ``geneweb-py`` (Click + Rich).
"""

import builtins
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result

pytest.importorskip("rich")

from geneweb_py.cli import commands as cli_commands
from geneweb_py.cli.commands import cli

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
SIMPLE_GW = FIXTURES_DIR / "simple_test.gw"


def _combined_output(result: Result) -> str:
    """Concatène stdout/stderr selon CliRunner.mix_stderr (Click 8+).

    Par défaut Click mélange stderr dans ``result.output`` : accéder à
    ``result.stderr`` lève alors ``ValueError`` (CI Python 3.8/3.9).
    """
    try:
        err = result.stderr or ""
    except ValueError:
        return result.output or ""
    out = result.stdout or ""
    return f"{out}{err}"


@pytest.fixture
def runner() -> CliRunner:
    """Runner Click isolé."""
    return CliRunner()


@pytest.mark.unit
def test_cli_help_displays_commands(runner: CliRunner) -> None:
    """``--help`` liste les sous-commandes parse et export."""
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "parse" in result.output
    assert "export" in result.output


@pytest.mark.unit
def test_cli_version(runner: CliRunner) -> None:
    """``--version`` affiche la version du package."""
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "geneweb-py" in result.output


@pytest.mark.unit
def test_parse_command_summary(runner: CliRunner) -> None:
    """``parse`` affiche un résumé pour un fichier .gw valide."""
    result = runner.invoke(cli, ["parse", str(SIMPLE_GW)])
    assert result.exit_code == 0
    out = result.output
    assert "Résumé" in out or "Personnes" in out
    assert str(SIMPLE_GW) in out or SIMPLE_GW.name in out


@pytest.mark.unit
def test_parse_command_missing_file(runner: CliRunner) -> None:
    """Fichier absent : code de sortie non nul."""
    missing = FIXTURES_DIR / "n_existe_pas.gw"
    result = runner.invoke(cli, ["parse", str(missing)])
    assert result.exit_code != 0


@pytest.mark.unit
@pytest.mark.parametrize("fmt", ["gedcom", "json", "xml"])
def test_export_command_formats(runner: CliRunner, tmp_path: Path, fmt: str) -> None:
    """``export`` produit un fichier pour chaque format supporté."""
    if fmt == "gedcom":
        out_file = tmp_path / "out.ged"
    elif fmt == "json":
        out_file = tmp_path / "out.json"
    else:
        out_file = tmp_path / "out.xml"

    result = runner.invoke(
        cli,
        [
            "export",
            str(SIMPLE_GW),
            "--format",
            fmt,
            "-o",
            str(out_file),
        ],
    )
    assert result.exit_code == 0, _combined_output(result)
    assert out_file.is_file()
    assert out_file.stat().st_size > 0


@pytest.mark.unit
def test_export_requires_format(runner: CliRunner, tmp_path: Path) -> None:
    """``--format`` est obligatoire."""
    out_file = tmp_path / "x.ged"
    result = runner.invoke(
        cli,
        ["export", str(SIMPLE_GW), "-o", str(out_file)],
    )
    assert result.exit_code != 0


@pytest.mark.unit
def test_export_parse_error_shows_rich_panel(
    runner: CliRunner,
    tmp_path: Path,
) -> None:
    """Erreur de parsing : message sur stderr (Rich)."""
    bad = tmp_path / "bad.txt"
    bad.write_text("not a gw file", encoding="utf-8")
    out_file = tmp_path / "out.ged"
    result = runner.invoke(
        cli,
        ["export", str(bad), "--format", "gedcom", "-o", str(out_file)],
    )
    assert result.exit_code != 0
    combined = _combined_output(result)
    assert "Erreur" in combined or "extension" in combined.lower()


@pytest.mark.unit
def test_entry_main_imports_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le point d'entrée ``main`` délègue au groupe Click."""
    import geneweb_py.cli.commands as commands_module
    from geneweb_py.cli import entry

    called: dict[str, bool] = {}

    def fake_cli() -> None:
        called["ok"] = True

    monkeypatch.setattr(commands_module, "cli", fake_cli)
    entry.main()
    assert called.get("ok") is True


@pytest.mark.unit
def test_parse_summary_includes_validation_errors_row(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Une ligne « Avertissements / erreurs » si ``validation_errors`` non vide."""
    from geneweb_py.core.exceptions import ErrorSeverity, GeneWebError
    from geneweb_py.core.genealogy import Genealogy

    genealogy = Genealogy()
    genealogy.validation_errors.append(
        GeneWebError("avertissement", severity=ErrorSeverity.WARNING)
    )
    monkeypatch.setattr(cli_commands, "_parse_genealogy", lambda _path: genealogy)
    gw_file = tmp_path / "stub.gw"
    gw_file.write_text("encoding: utf-8\n", encoding="utf-8")
    result = runner.invoke(cli, ["parse", str(gw_file)])
    assert result.exit_code == 0
    assert "Avertissements / erreurs" in result.output


@pytest.mark.unit
def test_parse_command_encoding_error(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from geneweb_py.core.exceptions import GeneWebEncodingError

    monkeypatch.setattr(
        cli_commands,
        "_parse_genealogy",
        lambda _p: (_ for _ in ()).throw(GeneWebEncodingError("encodage")),
    )
    gw_file = tmp_path / "enc.gw"
    gw_file.write_text("x", encoding="utf-8")
    result = runner.invoke(cli, ["parse", str(gw_file)])
    assert result.exit_code == 1
    combined = _combined_output(result)
    assert "encodage" in combined.lower()


@pytest.mark.unit
def test_parse_command_parse_error(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from geneweb_py.core.exceptions import GeneWebParseError

    monkeypatch.setattr(
        cli_commands,
        "_parse_genealogy",
        lambda _p: (_ for _ in ()).throw(GeneWebParseError("syntaxe")),
    )
    gw_file = tmp_path / "parse.gw"
    gw_file.write_text("x", encoding="utf-8")
    result = runner.invoke(cli, ["parse", str(gw_file)])
    assert result.exit_code == 1
    assert "Erreur" in _combined_output(result)


@pytest.mark.unit
def test_parse_command_unexpected_exception(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        cli_commands,
        "_parse_genealogy",
        lambda _p: (_ for _ in ()).throw(RuntimeError("inattendu")),
    )
    gw_file = tmp_path / "boom.gw"
    gw_file.write_text("x", encoding="utf-8")
    result = runner.invoke(cli, ["parse", str(gw_file)])
    assert result.exit_code == 1


@pytest.mark.unit
def test_export_command_encoding_error(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from geneweb_py.core.exceptions import GeneWebEncodingError

    monkeypatch.setattr(
        cli_commands,
        "_parse_genealogy",
        lambda _p: (_ for _ in ()).throw(GeneWebEncodingError("enc")),
    )
    out_file = tmp_path / "out.ged"
    result = runner.invoke(
        cli,
        ["export", str(SIMPLE_GW), "--format", "gedcom", "-o", str(out_file)],
    )
    assert result.exit_code == 1
    assert "encodage" in _combined_output(result).lower()


@pytest.mark.unit
def test_export_command_unexpected_parse_exception(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        cli_commands,
        "_parse_genealogy",
        lambda _p: (_ for _ in ()).throw(KeyError("metadata")),
    )
    out_file = tmp_path / "out.ged"
    result = runner.invoke(
        cli,
        ["export", str(SIMPLE_GW), "--format", "gedcom", "-o", str(out_file)],
    )
    assert result.exit_code == 1


@pytest.mark.unit
def test_export_command_conversion_error(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from geneweb_py.core.genealogy import Genealogy
    from geneweb_py.formats.base import ConversionError

    monkeypatch.setattr(cli_commands, "_parse_genealogy", lambda _p: Genealogy())

    class BrokenExporter:
        def export(self, gen: Genealogy, output_path: Path) -> None:
            raise ConversionError("export impossible")

    monkeypatch.setattr(
        cli_commands,
        "_get_exporter",
        lambda _fmt: (BrokenExporter(), "GEDCOM"),
    )
    out_file = tmp_path / "out.ged"
    result = runner.invoke(
        cli,
        ["export", str(SIMPLE_GW), "--format", "gedcom", "-o", str(out_file)],
    )
    assert result.exit_code == 1
    assert "Erreur" in _combined_output(result)


@pytest.mark.unit
def test_export_command_os_error(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from geneweb_py.core.genealogy import Genealogy

    monkeypatch.setattr(cli_commands, "_parse_genealogy", lambda _p: Genealogy())

    class OsFailExporter:
        def export(self, gen: Genealogy, output_path: Path) -> None:
            raise OSError(13, "Permission denied", str(output_path))

    monkeypatch.setattr(
        cli_commands,
        "_get_exporter",
        lambda _fmt: (OsFailExporter(), "JSON"),
    )
    out_file = tmp_path / "out.json"
    result = runner.invoke(
        cli,
        ["export", str(SIMPLE_GW), "--format", "json", "-o", str(out_file)],
    )
    assert result.exit_code == 1
    combined = _combined_output(result)
    assert "écriture" in combined.lower() or "Erreur" in combined


@pytest.mark.unit
def test_export_command_unexpected_export_exception(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from geneweb_py.core.genealogy import Genealogy

    monkeypatch.setattr(cli_commands, "_parse_genealogy", lambda _p: Genealogy())

    class BoomExporter:
        def export(self, gen: Genealogy, output_path: Path) -> None:
            raise RuntimeError("boom export")

    monkeypatch.setattr(
        cli_commands,
        "_get_exporter",
        lambda _fmt: (BoomExporter(), "XML"),
    )
    out_file = tmp_path / "out.xml"
    result = runner.invoke(
        cli,
        ["export", str(SIMPLE_GW), "--format", "xml", "-o", str(out_file)],
    )
    assert result.exit_code == 1


@pytest.mark.unit
def test_entry_main_without_cli_deps_exits(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Sans module ``commands`` importable : message stderr et code 1.

    En dernier : un ImportError simulé peut laisser ``sys.modules`` incohérent
    pour les tests suivants sans nettoyage explicite.
    """
    import importlib
    import sys

    real_import = builtins.__import__

    def fake_import(
        name: str,
        globals_: dict[str, Any] | None,
        locals_: dict[str, Any] | None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == "geneweb_py.cli.commands":
            raise ImportError("simulated missing CLI deps")
        return real_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    try:
        entry_mod = importlib.import_module("geneweb_py.cli.entry")
        with pytest.raises(SystemExit) as excinfo:
            entry_mod.main()
        assert excinfo.value.code == 1
        assert "geneweb-py[cli]" in capsys.readouterr().err
    finally:
        sys.modules.pop("geneweb_py.cli.commands", None)
        sys.modules.pop("geneweb_py.cli.entry", None)
        importlib.invalidate_caches()
        importlib.import_module("geneweb_py.cli.commands")
