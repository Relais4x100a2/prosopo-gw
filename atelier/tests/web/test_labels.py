from prosopo_gw_atelier.places.levels import Level
from prosopo_gw_atelier.web.app import _chain_name


def _city(arrondissement: str | None, city: str, insee: str) -> tuple[Level, ...]:
    levels: list[Level] = []
    if arrondissement is not None:
        levels.append(Level(0, arrondissement, type="arrondissement"))
    levels.append(Level(len(levels), city, type="commune", identifier=insee))
    levels.append(Level(len(levels), "France", type="pays", origin="written"))
    return tuple(levels)


def test_arrondissement_shortened_after_its_city() -> None:
    assert (
        _chain_name(_city("16e arrondissement", "Paris", "75056"), None) == "Paris 16e"
    )
    assert _chain_name(_city("1er arrondissement", "Lyon", "69123"), None) == "Lyon 1er"


def test_city_without_arrondissement_keeps_its_name() -> None:
    assert _chain_name(_city(None, "Paris", "75056"), None) == "Paris"


def test_free_arrondissement_name_is_kept_whole() -> None:
    chain = _city("Quartier latin", "Paris", "75056")
    assert _chain_name(chain, None) == "Paris Quartier latin"


def test_other_finer_levels_are_not_shown() -> None:
    chain = (
        Level(0, "Fictimont", type="hameau", origin="written"),
        Level(1, "Hesdin-la-Forêt", type="commune", identifier="62447"),
    )
    assert _chain_name(chain, None) == "Hesdin-la-Forêt"
