from prosopo_gw_atelier.refdata.arrondissements import (
    by_code,
    city_of,
    current,
    former_paris,
    level_id,
    level_name,
)


def test_codes_read_both_ways():
    assert by_code("75107") == ("paris", 7)
    assert by_code("75007") == ("paris", 7)
    assert by_code("75116") == ("paris", 16)
    assert by_code("69001") == ("lyon", 1)
    assert by_code("13216") == ("marseille", 16)
    assert (
        by_code("75021") is None
        and by_code("69010") is None
        and by_code("59350") is None
    )


def test_level_ids_and_names():
    assert level_id("paris", 7) == "paris-07"
    assert level_id("lyon", 1) == "69381"
    assert level_id("marseille", 1) == "13201"
    assert (
        level_name(1) == "1er arrondissement" and level_name(7) == "7e arrondissement"
    )


def test_periods():
    assert former_paris(7).id == "paris-1795-07" and former_paris(7).end == "1859-12-31"
    assert former_paris(13) is None
    assert (
        current("paris", 7).id == "75107" and current("paris", 7).start == "1860-01-01"
    )
    # Dates verified against the Lyon municipal archives (see module docstring).
    assert current("lyon", 8).start == "1959-02-09"
    assert current("marseille", 1).start == "1946-10-18"
    assert current("lyon", 10) is None
    assert city_of("13055") == "marseille" and city_of("59350") is None


def test_is_insee_code_tells_insee_from_postal():
    from prosopo_gw_atelier.refdata.arrondissements import is_insee_code

    assert is_insee_code("75107") and is_insee_code("69381") and is_insee_code("13208")
    assert not is_insee_code("75007") and not is_insee_code("69001")
    assert not is_insee_code("59350")


def test_name_of_reads_every_identifier_form():
    from prosopo_gw_atelier.refdata.arrondissements import name_of

    assert name_of("75107") == "7e arrondissement"
    assert name_of("paris-07") == "7e arrondissement"
    assert name_of("paris-1795-01") == "1er arrondissement"
    assert name_of("69381") == "1er arrondissement"
    assert name_of("13216") == "16e arrondissement"
    assert name_of("") is None and name_of("59350") is None
    assert name_of("paris-99") is None
