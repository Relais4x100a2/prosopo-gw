from pathlib import Path

import pytest

from prosopo_gw_atelier.refdata import Commune, NameMatch, RefData, load_refdata

MINI = Path(__file__).resolve().parents[1] / "fixtures" / "refdata_mini"


@pytest.fixture(scope="module")
def ref() -> RefData:
    return load_refdata(MINI)


def test_vintages(ref: RefData) -> None:
    assert ref.cog_vintage == "2026"
    assert ref.postal_vintage == "2026-11-07"


def test_commune_by_insee(ref: RefData) -> None:
    roubaix = ref.commune_by_insee("59512")
    assert roubaix is not None
    assert roubaix.name == "Roubaix"
    assert roubaix == Commune("59512", "Roubaix", "59", "32")
    assert ref.commune_by_insee("00000") is None
    assert ref.commune_count > 5


def test_communes_by_postal(ref: RefData) -> None:
    assert [c.insee for c in ref.communes_by_postal("59100")] == ["59512"]
    assert ref.communes_by_postal("99999") == []


def test_postal_code_of_municipal_arrondissement_maps_to_commune(
    ref: RefData,
) -> None:
    assert [c.insee for c in ref.communes_by_postal("69001")] == ["69123"]


def test_department(ref: RefData) -> None:
    assert ref.department("Nord") == ref.department("(59)") == "59"
    assert ref.department("59") == "59"
    assert ref.department("PAS-DE-CALAIS") == "62"
    assert ref.department("Rhone") == "69"
    assert ref.department("Atlantide") is None
    assert ref.department("") is None


def test_region(ref: RefData) -> None:
    assert ref.region("Nord-Pas-de-Calais") == ("Nord-Pas-de-Calais", True)
    assert ref.region("Hauts-de-France") == ("Hauts-de-France", False)
    assert ref.region("hauts de france") == ("Hauts-de-France", False)
    assert ref.region("Nord") is None


def test_country(ref: RefData) -> None:
    assert ref.country("FRANCE") == "France"
    assert ref.country("République française") == "France"
    assert ref.country("Belgique") == "Belgique"
    assert ref.country("Nord") is None


def test_current_name(ref: RefData) -> None:
    matches = ref.communes_by_name("ROUBAIX")
    assert [m.commune.insee for m in matches] == ["59512"]
    assert matches[0].former_name is None


def test_homonyms_in_two_departments(ref: RefData) -> None:
    matches = ref.communes_by_name("Merville")
    assert sorted(m.commune.department for m in matches) == ["31", "59"]
    assert all(m.former_name is None for m in matches)


def test_abbreviated_saint(ref: RefData) -> None:
    assert [m.commune.insee for m in ref.communes_by_name("ST-OMER")] == ["62765"]


def test_merged_commune(ref: RefData) -> None:
    matches = ref.communes_by_name("Lomme")
    assert len(matches) == 1
    lille = ref.commune_by_insee("59350")
    assert lille is not None
    assert matches[0] == NameMatch(commune=lille, former_name="Lomme")


def test_unknown_name(ref: RefData) -> None:
    assert ref.communes_by_name("Atlantide") == []


def test_load_is_cached() -> None:
    assert load_refdata(MINI) is load_refdata(MINI)
    assert load_refdata(MINI / ".." / "refdata_mini") is load_refdata(MINI)


def test_missing_directory_has_clear_message(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="build_refdata.py"):
        load_refdata(tmp_path)


def test_default_directory_is_package_data(monkeypatch: pytest.MonkeyPatch) -> None:
    from prosopo_gw_atelier.refdata import loader

    assert loader.DEFAULT_DATA_DIR.parts[-2:] == ("refdata", "data")
    monkeypatch.setattr(loader, "DEFAULT_DATA_DIR", MINI)
    assert load_refdata().cog_vintage == "2026"
