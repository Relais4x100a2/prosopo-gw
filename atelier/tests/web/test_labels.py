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


def test_proposed_arrondissement_is_not_shown() -> None:
    chain = (
        Level(0, "16e arrondissement", type="arrondissement", status="proposed"),
        Level(1, "Paris", type="commune", identifier="75056"),
    )
    assert _chain_name(chain, None) == "Paris"


def test_former_paris_arrondissement_shows_its_period() -> None:
    chain = (
        Level(
            0,
            "7e arrondissement",
            type="arrondissement",
            identifier="paris-1795-07",
            start="1795-10-11",
            end="1859-12-31",
        ),
        Level(1, "Paris", type="commune", identifier="75056"),
    )
    assert _chain_name(chain, None) == "Paris 7e (1795-1859)"


def test_finest_arrondissement_wins_whatever_the_order() -> None:
    chain = (
        Level(2, "3e arrondissement", type="arrondissement"),
        Level(0, "7e arrondissement", type="arrondissement"),
        Level(3, "Paris", type="commune", identifier="75056"),
    )
    assert _chain_name(chain, None) == "Paris 7e"


def test_arrondissement_named_with_its_city_is_not_doubled() -> None:
    chain = _city("Paris 16e arrondissement", "Paris", "75056")
    assert _chain_name(chain, None) == "Paris 16e"


def test_current_arrondissement_does_not_show_its_open_period() -> None:
    chain = (
        Level(0, "7e arrondissement", type="arrondissement", start="1860-01-01"),
        Level(1, "Paris", type="commune", identifier="75056"),
    )
    assert _chain_name(chain, None) == "Paris 7e"


def test_former_arrondissement_without_start_shows_its_end() -> None:
    chain = (
        Level(0, "7e arrondissement", type="arrondissement", end="1859-12-31"),
        Level(1, "Paris", type="commune", identifier="75056"),
    )
    assert _chain_name(chain, None) == "Paris 7e (-1859)"
