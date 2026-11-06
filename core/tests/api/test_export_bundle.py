"""Archive zip de l'export (fixtures 100 % synthétiques)."""

import io
import json
import sqlite3
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import List, Tuple

from geneweb_py.api.services.export_bundle import build_export_bundle
from geneweb_py.api.services.organization_candidates import build_candidate_index
from geneweb_py.api.services.organization_tables import build_organization_tables
from geneweb_py.core.genealogy import Genealogy
from geneweb_py.core.parser.gw_parser import GeneWebParser
from geneweb_py.core.shared_experiences import find_shared_experiences
from geneweb_py.formats.table_writers import archive_name, table_to_csv
from geneweb_py.formats.tables import Table, build_base_tables

NOW = datetime(2026, 11, 6, 10, 30, 0)
TABLE_NAMES = [
    "personnes",
    "familles",
    "enfants",
    "evenements",
    "temoins",
    "sources",
    "organisations",
    "liens",
    "reste_a_classer",
    "pistes",
    "experiences_proches",
]

GW = """encoding: utf-8

fam DUPONT Jean + MARTIN Marie
beg
end

pevt DUPONT Jean
#occu 1900 #p [Banque Fictive] - Lyon
#Voyage_Italie 1950 #p Montfictif
end pevt

pevt MARTIN Marie
#occu 1902 #p [Banque Fictive] - Lyon
#resi 1903 #p Lyon
note Logée près de la fabrique du quartier
end pevt

notes DUPONT Jean
beg
Associé de la Société des Forges Fictives.
end notes
"""

IGNORED = ("vacances",)


def _bundle(genealogy: Genealogy, source: str = "ma_base.gw") -> Tuple[str, bytes]:
    index = build_candidate_index(genealogy, IGNORED)
    shared = find_shared_experiences(genealogy, index.matched, set(IGNORED))
    return build_export_bundle(genealogy, index, shared, IGNORED, source, NOW)


def _genealogy() -> Genealogy:
    return GeneWebParser(validate=False).parse_string(GW)


def _zip(data: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(data))


def _tables(genealogy: Genealogy) -> List[Table]:
    index = build_candidate_index(genealogy, IGNORED)
    shared = find_shared_experiences(genealogy, index.matched, set(IGNORED))
    return build_base_tables(genealogy) + build_organization_tables(
        genealogy, index, shared, IGNORED
    )


def test_zip_file_list() -> None:
    name, data = _bundle(_genealogy())
    assert name == "prosopo-ma_base-2026-11-06.zip"
    archive = _zip(data)
    assert archive.namelist() == [
        "LISEZMOI.txt",
        "dictionnaire.csv",
        "base.org.json",
        "base.sqlite",
        "base.json",
    ] + [f"csv/{t}.csv" for t in TABLE_NAMES]
    assert all(i.compress_type == zipfile.ZIP_DEFLATED for i in archive.infolist())


def test_archive_name_sanitized() -> None:
    day = date(2026, 11, 6)
    assert archive_name("ma base été.gw", day) == "prosopo-ma_base_ete-2026-11-06.zip"
    assert archive_name(None, day) == "prosopo-base-2026-11-06.zip"
    assert archive_name("", day) == "prosopo-base-2026-11-06.zip"
    assert archive_name("../x/a;b.gw", day) == "prosopo-a_b-2026-11-06.zip"


def test_companion_has_ignored_words() -> None:
    payload = json.loads(_zip(_bundle(_genealogy())[1]).read("base.org.json"))
    assert {"version", "organizations", "links", "ignored_words"} <= set(payload)
    assert payload["ignored_words"] == list(IGNORED)
    assert payload["organizations"]


def test_readme_mentions_base_and_date() -> None:
    text = _zip(_bundle(_genealogy())[1]).read("LISEZMOI.txt").decode("utf-8")
    assert text.startswith("Export prosopo-gw — base « ma_base », 2026-11-06\n")
    assert "Ne le publiez pas et ne le versionnez pas." in text
    assert "dictionnaire.csv" in text


def test_csv_in_zip_match_tables() -> None:
    g = _genealogy()
    archive = _zip(_bundle(g)[1])
    for t in _tables(g):
        assert archive.read(f"csv/{t.spec.name}.csv").decode("utf-8") == table_to_csv(t)
    payload = json.loads(archive.read("base.json"))
    assert payload["base"] == "ma_base"
    assert list(payload["tables"]) == TABLE_NAMES


def test_empty_genealogy_bundle(tmp_path: Path) -> None:
    archive = _zip(_bundle(Genealogy(), source="")[1])
    for t in TABLE_NAMES:
        lines = archive.read(f"csv/{t}.csv").decode("utf-8").splitlines()
        assert len(lines) == 1
    path = tmp_path / "base.sqlite"
    path.write_bytes(archive.read("base.sqlite"))
    conn = sqlite3.connect(str(path))
    names = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert names == set(TABLE_NAMES)
    for t in TABLE_NAMES:
        assert conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone() == (0,)


def _sqlite(data: bytes, tmp_path: Path) -> sqlite3.Connection:
    path = tmp_path / "base.sqlite"
    path.write_bytes(_zip(data).read("base.sqlite"))
    return sqlite3.connect(str(path))


def test_lead_ids_resolve(tmp_path: Path) -> None:
    conn = _sqlite(_bundle(_genealogy())[1], tmp_path)
    assert conn.execute("SELECT COUNT(*) FROM pistes").fetchone()[0] >= 2
    for column, table in (
        ("personne_id", "personnes"),
        ("evenement_id", "evenements"),
        ("famille_id", "familles"),
    ):
        dangling = conn.execute(
            f"SELECT COUNT(*) FROM pistes p LEFT JOIN {table} t "
            f"ON t.{column} = p.{column} "
            f"WHERE p.{column} IS NOT NULL AND t.{column} IS NULL"
        ).fetchone()[0]
        assert dangling == 0, column


def test_dictionary_lists_pistes() -> None:
    text = _zip(_bundle(_genealogy())[1]).read("dictionnaire.csv").decode("utf-8")
    rows = [line.split(";") for line in text.lstrip("\ufeff").splitlines()]
    columns = [r[1] for r in rows if r[0] == "pistes"]
    assert len(columns) == 10
    assert columns[0] == "piste_id" and columns[-1] == "extrait"
