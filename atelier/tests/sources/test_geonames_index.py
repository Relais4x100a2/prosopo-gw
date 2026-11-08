import sqlite3
import threading
import tracemalloc
import zipfile
from pathlib import Path

import pytest

from prosopo_gw_atelier.places.cluster import name_key
from prosopo_gw_atelier.sources.base import SourceError
from prosopo_gw_atelier.sources.geonames import index as gn
from prosopo_gw_atelier.sources.geonames.index import (
    GeoNamesIndex,
    read_admin_codes,
    read_country_info,
    read_dump,
    read_names,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "geonames"
CA = FIXTURES / "CA.zip"
GB = FIXTURES / "GB.zip"
ADMIN1 = FIXTURES / "admin1CodesASCII.txt"
ADMIN2 = FIXTURES / "admin2Codes.txt"


@pytest.fixture
def idx(tmp_path: Path) -> GeoNamesIndex:
    index = GeoNamesIndex(tmp_path / "geonames")
    index.build("CA", CA, ADMIN1, ADMIN2, "2026-11-08")
    index.build("GB", GB, ADMIN1, ADMIN2, "2026-11-09")
    return index


def test_read_dump_keeps_p_and_a() -> None:
    places = {p.geonameid: p for p in read_dump(CA, "CA")}
    assert set(places) == {
        9000001,
        9000002,
        9000003,
        9000004,
        9000005,
        9000006,
        9000007,
    }
    winnipeg = places[9000001]
    assert (winnipeg.name, winnipeg.feature_code, winnipeg.admin1) == (
        "Winnipeg",
        "PPLA",
        "03",
    )
    assert winnipeg.population == 705000
    assert winnipeg.latitude == pytest.approx(49.88)


def test_alternate_names_filtered() -> None:
    names = {n for gid, n in read_names(CA, "CA") if gid == 9000001}
    assert names == {"Ouinipègue", "Winnipeg", "Winipeg"}
    gb = {n for gid, n in read_names(GB, "GB") if gid == 9100001}
    assert gb == {"Storrington", "Storrington and Sullington", "Storringtown", "ZZZ"}


def test_admin_codes() -> None:
    admin1 = read_admin_codes(ADMIN1)
    assert admin1["CA.03"] == ("Manitoba", 9000002)
    assert read_admin_codes(ADMIN2)["GB.ENG.P5"] == ("East Sussex", 9100003)
    info = read_country_info(FIXTURES / "countryInfo.txt")
    assert info == {"CA": "Canada", "GB": "United Kingdom"}


def test_lookup_by_name_and_alternate(idx: GeoNamesIndex) -> None:
    assert [p.geonameid for p in idx.lookup("CA", name_key("Winnipeg"))] == [9000001]
    assert [p.geonameid for p in idx.lookup("CA", name_key("ouinipegue"))] == [9000001]
    assert idx.lookup("CA", name_key("R3C")) == []
    beaumont = idx.lookup("CA", name_key("Beaumont"))
    assert [(p.geonameid, p.admin1) for p in beaumont] == [
        (9000004, "03"),
        (9000005, "08"),
    ]
    assert idx.lookup("XX", "winnipeg") == []
    assert idx.lookup("CA", "nothing") == []


def test_get_and_admin_name(idx: GeoNamesIndex) -> None:
    storrington = idx.get("GB", 9100001)
    assert storrington is not None and storrington.admin2 == "P5"
    assert idx.get("GB", 1) is None
    assert idx.admin_name("GB", "ENG") == ("England", 9100002)
    assert idx.admin_name("GB", "ENG", "P5") == ("East Sussex", 9100003)
    assert idx.admin_name("CA", "03") == ("Manitoba", 9000002)
    assert idx.admin_name("CA", "99") is None
    assert idx.admin_name("CA", "A1") is None  # FR rows are not copied


def test_countries_and_remove(idx: GeoNamesIndex) -> None:
    assert idx.countries() == {"CA": "2026-11-08", "GB": "2026-11-09"}
    idx.build("CA", CA, ADMIN1, ADMIN2, "2027-01-01")
    assert idx.countries()["CA"] == "2027-01-01"
    idx.remove("CA")
    assert idx.countries() == {"GB": "2026-11-09"}
    assert idx.lookup("CA", "winnipeg") == []


def test_invalid_country(idx: GeoNamesIndex, tmp_path: Path) -> None:
    for bad in ("ca", "CAN", "../x", "C", ""):
        with pytest.raises(SourceError):
            idx.build(bad, CA, ADMIN1, ADMIN2, "d")
    with pytest.raises(SourceError):
        list(read_dump(CA, "../CA"))


def test_zip_member_with_path_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "CA.zip"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("sub/CA.txt", "x")
        archive.writestr("../CA.txt", "x")
    with pytest.raises(SourceError):
        list(read_dump(bad, "CA"))
    notzip = tmp_path / "GB.zip"
    notzip.write_bytes(b"not a zip")
    with pytest.raises(SourceError):
        list(read_dump(notzip, "GB"))


def test_index_build_is_atomic(
    idx: GeoNamesIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(zip_path: Path, country: str) -> object:
        yield "winnipeg", 9000001
        raise RuntimeError("boom")

    monkeypatch.setattr(gn, "_keyed_names", boom)
    with pytest.raises(RuntimeError):
        idx.build("CA", CA, ADMIN1, ADMIN2, "2030-01-01")
    directory = next(iter(idx._directory.parent.glob("geonames")))
    assert not list(directory.glob("*.part*"))
    assert idx.countries()["CA"] == "2026-11-08"
    assert [p.geonameid for p in idx.lookup("CA", "winnipeg")] == [9000001]


def test_reader_works_while_another_country_builds(idx: GeoNamesIndex) -> None:
    errors: list[BaseException] = []

    def rebuild() -> None:
        try:
            for _ in range(5):
                idx.build("GB", GB, ADMIN1, ADMIN2, "x")
        except BaseException as error:  # noqa: BLE001
            errors.append(error)

    thread = threading.Thread(target=rebuild)
    thread.start()
    for _ in range(50):
        assert idx.lookup("CA", "winnipeg")
    thread.join()
    assert not errors


def _letters(i: int) -> str:
    out = ""
    while True:
        i, rest = divmod(i, 26)
        out += chr(97 + rest)
        if not i:
            return out


def test_large_file_streams(tmp_path: Path) -> None:
    big = tmp_path / "CA.zip"
    with zipfile.ZipFile(big, "w", zipfile.ZIP_DEFLATED) as archive:
        with archive.open("CA.txt", "w") as out:
            for i in range(200_000):
                fields = [
                    str(1_000_000 + i), f"Place{i}", f"Place{i}", f"Autre{_letters(i)}",
                    "50.0", "-97.0", "P", "PPL", "CA", "", "03", "", "", "", "10", "",
                    "1", "UTC", "2024-01-01",
                ]  # fmt: skip
                out.write(("\t".join(fields) + "\n").encode("utf-8"))
    tracemalloc.start()
    try:
        # tracemalloc slows everything down: measure the streaming reader only.
        total = sum(1 for _ in read_dump(big, "CA"))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert total == 200_000
    assert peak < 50 * 1024 * 1024
    index = GeoNamesIndex(tmp_path / "idx")
    assert index.build("CA", big, ADMIN1, ADMIN2, "d") == 200_000
    assert [
        p.geonameid for p in index.lookup("CA", name_key(f"Autre{_letters(123)}"))
    ] == [1_000_123]
    with sqlite3.connect(tmp_path / "idx" / "CA.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM places").fetchone() == (200_000,)


def test_ascii_name_indexed_and_keys_deduplicated(tmp_path: Path) -> None:
    zip_path = tmp_path / "CA.zip"
    fields = [
        "9500001", "Montréal", "Montreal", "Montréal,Montreal,Mont-Royal", "45.5",
        "-73.5", "P", "PPLA2", "CA", "", "10", "", "", "", "1000", "", "1", "UTC", "d",
    ]  # fmt: skip
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("CA.txt", "\t".join(fields) + "\n")
    index = GeoNamesIndex(tmp_path / "idx")
    index.build("CA", zip_path, ADMIN1, ADMIN2, "d")
    assert [p.geonameid for p in index.lookup("CA", "montreal")] == [9500001]
    with sqlite3.connect(tmp_path / "idx" / "CA.sqlite") as db:
        rows = db.execute("SELECT key FROM names ORDER BY key").fetchall()
    assert len(rows) == 2 == len(set(rows))


def test_readers_never_create_files(idx: GeoNamesIndex) -> None:
    idx.remove("CA")
    assert idx.lookup("CA", "winnipeg") == []
    assert idx.get("CA", 9000001) is None
    assert idx.admin_name("CA", "03") is None
    assert not (idx._directory / "CA.sqlite").exists()
    assert sorted(p.name for p in idx._directory.iterdir()) == ["GB.sqlite"]
