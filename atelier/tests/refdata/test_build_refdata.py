"""Tests of the offline builder ``atelier/tools/build_refdata.py``.

The source fixtures under ``fixtures/refdata_sources`` mimic the INSEE COG and
La Poste file layouts. Codes starting with ``99`` are synthetic (no commune has
them) and exercise the resolution of chained mergers.
"""

from __future__ import annotations

import gzip
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from prosopo_gw_atelier.refdata import load_refdata

ATELIER = Path(__file__).resolve().parents[2]
SOURCES = ATELIER / "tests" / "fixtures" / "refdata_sources"


def _load_builder() -> ModuleType:
    path = ATELIER / "tools" / "build_refdata.py"
    spec = importlib.util.spec_from_file_location("build_refdata", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_refdata"] = module
    spec.loader.exec_module(module)
    return module


builder = _load_builder()


def _args(output: Path, **overrides: str) -> list[str]:
    paths = {
        "communes": "v_commune_2026.csv",
        "mouvements": "v_mvt_commune_2026.csv",
        "communes-depuis-1943": "v_commune_depuis_1943.csv",
        "departements": "v_departement_2026.csv",
        "regions": "v_region_2026.csv",
        "regions-2015": "reg2015.txt",
        "pays": "v_pays_territoire_2026.csv",
        "codes-postaux": "laposte_hexasmal.csv",
    }
    paths.update(overrides)
    argv: list[str] = []
    for option, name in paths.items():
        argv += [f"--{option}", str(SOURCES / name)]
    argv += ["--cog-vintage", "2026", "--postal-vintage", "2026-11-07"]
    argv += ["--output", str(output)]
    return argv


def test_detects_comma_delimiter_and_utf8() -> None:
    table = builder.read_source(SOURCES / "v_region_2026.csv")
    assert table.delimiter == ","
    assert table.encoding == "utf-8"
    assert table.column("LIBELLE")[1] == "Hauts-de-France"


def test_detects_semicolon_delimiter() -> None:
    table = builder.read_source(SOURCES / "v_departement_2026.csv")
    assert table.delimiter == ";"
    assert table.column("LIBELLE")[3] == "Rhône"


def test_detects_tab_delimiter_and_latin1() -> None:
    table = builder.read_source(SOURCES / "reg2015.txt")
    assert table.delimiter == "\t"
    assert table.encoding == "cp1252"
    assert "Midi-Pyrénées" in table.column("NCCENR")


def test_header_match_ignores_case_accents_bom_and_hash() -> None:
    table = builder.read_source(SOURCES / "laposte_hexasmal.csv")
    assert table.column("code_commune_insee")[0] == "59350"
    assert table.column("LIBELLE_D_ACHEMINEMENT")[0] == "LILLE"


def test_missing_column_gives_clear_error() -> None:
    table = builder.read_source(SOURCES / "v_departement_missing_libelle.csv")
    with pytest.raises(builder.SourceFormatError) as excinfo:
        table.column("LIBELLE")
    message = str(excinfo.value)
    assert "LIBELLE" in message
    assert "v_departement_missing_libelle.csv" in message


def test_main_reports_missing_column(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = _args(tmp_path, departements="v_departement_missing_libelle.csv")
    assert builder.main(argv) == 2
    err = capsys.readouterr().err
    assert "LIBELLE" in err
    assert not (tmp_path / "VERSION").exists()


def test_end_to_end_output_is_loadable(tmp_path: Path) -> None:
    assert builder.main(_args(tmp_path)) == 0
    ref = load_refdata(tmp_path)

    assert ref.cog_vintage == "2026"
    assert ref.postal_vintage == "2026-11-07"
    # Only COM rows are current communes (no COMA, COMD, ARM).
    assert ref.commune_count == 7
    assert ref.commune_by_insee("59355") is None
    assert ref.commune_by_insee("69381") is None
    roubaix = ref.commune_by_insee("59512")
    assert roubaix is not None and roubaix.name == "Roubaix"
    assert roubaix.department == "59" and roubaix.region == "32"

    # Former names: association, delegated commune, chained mergers, renaming.
    def former(name: str) -> list[tuple[str, str | None]]:
        return [(m.commune.insee, m.former_name) for m in ref.communes_by_name(name)]

    assert former("Lomme") == [("59350", "Lomme")]
    assert former("Coudekerque-Village") == [("59588", "Coudekerque-Village")]
    assert former("Teteghem") == [("59588", "Téteghem")]
    assert former("Ancienville") == [("59512", "Ancienville")]
    assert former("Villemilieu") == [("59512", "Villemilieu")]
    # A movement from a commune that is still current does not make its name
    # a former name of another commune.
    assert former("Roubaix") == [("59512", None)]
    assert former("Vieilleville") == []
    assert sorted(i for i, _ in former("Merville")) == ["31341", "59400"]

    # Postal codes: deduplicated, arrondissement and delegated codes mapped
    # to their parent commune, unknown INSEE codes dropped.
    assert [c.insee for c in ref.communes_by_postal("59000")] == ["59350"]
    assert [c.insee for c in ref.communes_by_postal("69001")] == ["69123"]
    assert [c.insee for c in ref.communes_by_postal("59380")] == ["59588"]
    assert ref.communes_by_postal("00000") == []

    assert ref.department("(62)") == "62"
    assert ref.department("Haute Garonne") == "31"
    assert ref.region("Midi-Pyrénées") == ("Midi-Pyrénées", True)
    assert ref.region("Ile-de-France") == ("Île-de-France", False)
    assert ref.country("royaume de belgique") == "Belgique"

    version = (tmp_path / "VERSION").read_text(encoding="utf-8")
    assert version == "cog=2026\npostal=2026-11-07\n"


def test_output_is_reproducible(tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    assert builder.main(_args(first)) == 0
    assert builder.main(_args(second)) == 0
    for path in sorted(first.iterdir()):
        assert path.read_bytes() == (second / path.name).read_bytes()


def test_communes_depuis_1943_is_optional(tmp_path: Path) -> None:
    argv = _args(tmp_path)
    index = argv.index("--communes-depuis-1943")
    del argv[index : index + 2]
    assert builder.main(argv) == 0
    ref = load_refdata(tmp_path)
    assert [m.former_name for m in ref.communes_by_name("Teteghem")] == ["Téteghem"]


def _history() -> dict[str, tuple[str, str, str, str]]:
    cog = builder.read_communes(SOURCES / "v_commune_2026.csv")
    movements = builder.read_source(SOURCES / "v_mvt_commune_2026.csv").records(
        "MOD", "DATE_EFF", "TYPECOM_AV", "COM_AV", "LIBELLE_AV", "TYPECOM_AP", "COM_AP"
    )
    since = builder.read_source(SOURCES / "v_commune_depuis_1943.csv").records(
        "TYPECOM", "COM", "LIBELLE", "DATE_FIN"
    )
    rows = builder.build_history(cog, movements, since)
    return {
        name: (old, current, nature, date) for name, old, current, nature, date in rows
    }


def test_history_associated_commune() -> None:
    assert _history()["Lomme"] == ("59355", "59350", "associee", "2000-02-27")


def test_history_delegated_commune_keeps_its_code_and_date() -> None:
    history = _history()
    assert history["Coudekerque-Village"] == (
        "59154",
        "59588",
        "deleguee",
        "2016-01-01",
    )
    assert history["Téteghem"] == ("59588", "59588", "deleguee", "2016-01-01")


def test_history_merger_chain() -> None:
    history = _history()
    assert history["Ancienville"] == ("99001", "59512", "fusion", "1970-01-01")
    assert history["Villemilieu"] == ("99002", "59512", "fusion", "1980-01-01")


def test_history_rename_is_not_a_historical_commune() -> None:
    assert _history()["Saint-Omer-en-Artois"] == (
        "62765",
        "62765",
        "renommage",
        "1962-01-01",
    )


def test_history_header(tmp_path: Path) -> None:
    assert builder.main(_args(tmp_path)) == 0
    with gzip.open(tmp_path / "historique.csv.gz", "rt", encoding="utf-8") as f:
        assert (
            f.readline().strip()
            == "ancien_nom;ancien_insee;insee_actuel;nature;date_effet"
        )
