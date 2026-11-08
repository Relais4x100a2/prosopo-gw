from pathlib import Path

import pytest

from prosopo_gw_atelier.refdata import Commune, Former, RefData, load_refdata

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
    assert matches[0].former == Former(
        "Lomme", "59355", "59350", "associee", "2000-02-27"
    )
    assert matches[0].former_name == "Lomme"


def test_delegated_commune_sharing_the_new_code(ref: RefData) -> None:
    [match] = ref.communes_by_name("Hesdin")
    assert match.commune.insee == "62447"
    assert match.former == Former("Hesdin", "62447", "62447", "deleguee", "2025-01-01")


def test_current_name_and_former_name_elsewhere(ref: RefData) -> None:
    matches = ref.communes_by_name("Sainte-Austreberthe")
    readings = sorted((m.commune.insee, m.former is not None) for m in matches)
    assert readings == [("62447", True), ("76566", False)]


def test_rename(ref: RefData) -> None:
    [match] = ref.communes_by_name("Saint-Omer-en-Artois")
    assert match.former is not None and match.former.nature == "renommage"


def test_former_communes(ref: RefData) -> None:
    names = [f.name for f in ref.former_communes("62447")]
    assert names == ["Hesdin", "Marconne", "Sainte-Austreberthe"]
    assert ref.former_communes("59512") == []


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


def test_embedded_reference_data() -> None:
    ref = load_refdata()
    assert ref.cog_vintage
    assert ref.postal_vintage
    assert ref.commune_count > 34_000
    roubaix = ref.commune_by_insee("59512")
    assert roubaix is not None and roubaix.name == "Roubaix"
    assert [c.insee for c in ref.communes_by_postal("59100")] == ["59512"]


def test_region_name(ref: RefData) -> None:
    assert ref.region_name("32") == "Hauts-de-France"
    assert ref.region_name("31") == "Nord-Pas-de-Calais"
    assert ref.region_name(" 84 ") == "Auvergne-Rhône-Alpes"
    assert ref.region_name("99") is None


def test_department_name(ref: RefData) -> None:
    assert ref.department_name("62") == "Pas-de-Calais"
    assert ref.department_name(" 59 ") == "Nord"
    assert ref.department_name("99") is None


def test_current_of_current_code(ref: RefData) -> None:
    result = ref.current_of("59350")
    assert result is not None
    commune, former = result
    assert commune.name == "Lille"
    assert former is None


def test_current_of_former_code_2011(ref: RefData) -> None:
    result = ref.current_of("59355")
    assert result is not None
    commune, former = result
    assert commune.insee == "59350"
    assert former is not None
    assert former.name == "Lomme"
    assert ref.current_of("00000") is None


def test_current_of_shared_code_uses_name(ref: RefData) -> None:
    plain = ref.current_of("62447")
    assert plain is not None
    assert plain[0].name == "Hesdin-la-Forêt"
    assert plain[1] is None
    named = ref.current_of("62447", name="Hesdin")
    assert named is not None
    assert named[0].insee == "62447"
    assert named[1] is not None
    assert named[1].name == "Hesdin"
    same = ref.current_of("62447", name="Hesdin-la-Forêt")
    assert same is not None
    assert same[1] is None


def test_country_iso(ref: RefData) -> None:
    assert ref.country_iso("Canada") == "CA"
    assert ref.country_iso("royaume-uni") == "GB"
    assert ref.country_iso("Royaume de Belgique") == "BE"
    assert ref.country_iso("Prusse") is None
