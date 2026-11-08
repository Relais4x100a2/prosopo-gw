"""Reading of DicoTopo department files and their local SQLite index.

DicoTopo is published under CC BY-NC-ND: nothing of it is shipped or versioned
here. The user downloads each ``DTxx.xml`` into the local cache; this module
only reads it and keeps an index of it.

Structure of a ``DTxx.xml`` file (UTF-8, no DOCTYPE and no entity declaration;
one file per department, from 3 MB to several tens of MB)::

    <DICTIONNAIRE dep="05" departement="...">
      <article id="P12345678" old-id="DT05-00001" pg="1" [type="commune"]>
        <pg>..</pg>                       (optional page marker, also seen
                                           inside <forme_ancienne>)
        <vedette><sm>Name (Le),</sm></vedette>
        <definition>
          <typologie>ferme</typologie>, <localisation>commune de
            <commune insee="05061" precision="certain">..</commune>
          </localisation>.
        </definition>
        <commentaire><p>..</p></commentaire>        (optional)
        <forme_ancienne>— <i>ancient form,</i> <date>..</date>
                          <reference>(..)</reference>.</forme_ancienne>   (0..n)
        <insee>05001</insee>             (only on a commune article)
      </article>
    </DICTIONNAIRE>

Observed variations: ``typologie`` is free text (``ferme``, ``écart``,
``hameau``, ``commune``, ``Ancien mandement``…, capitalised at times);
``localisation`` may hold several ``commune`` elements (the first is kept) or
none; an ``<i>`` can be split around bracketed text (``<i>abc</i>[<i>d</i>]``).
A few articles have no ``localisation`` and no ``<insee>``.

An article is kept when it has an ``id``, a headword and at least one INSEE code
(its own or its location); any other is counted as skipped.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from ...places.cluster import name_key

KINDS = (
    "hameau",
    "ferme",
    "ecart",
    "lieu-dit",
    "chateau",
    "moulin",
    "paroisse",
    "abbaye",
    "section",
)

_TRAILING = re.compile(r"[\s,;:.!?]+$")
_ITALIC_MARKUP = re.compile(r"</?i>|''+|\*+")


_INVERTED = re.compile(r"^(.*?)\s*\((le|la|les|l['\u2019])\)$", re.IGNORECASE)


@dataclass(frozen=True)
class Article:
    """One DicoTopo article."""

    id: str
    department: str
    headword: str
    insee: str | None  # own INSEE code (commune article)
    commune_insee: str | None  # INSEE code of the (first) location commune
    kind: str | None  # one of KINDS, else None
    forms: tuple[str, ...]  # ancient forms, in file order


def form_key(text: str) -> str:
    """Index key of a form: ``name_key`` without markup nor trailing punctuation."""
    cleaned = _ITALIC_MARKUP.sub("", text)
    return name_key(_TRAILING.sub("", cleaned.strip()))


def form_keys(text: str) -> set[str]:
    """Keys of a headword or form: ``form_key`` plus the fronted variant.

    ``Quesnoy-Fictif (Le)`` gives its own key, that of ``Le Quesnoy-Fictif`` and that of
    the bare ``Quesnoy-Fictif``.
    """
    cleaned = _TRAILING.sub("", _ITALIC_MARKUP.sub("", text).strip())
    keys = {name_key(cleaned)}
    match = _INVERTED.match(cleaned)
    if match and match.group(1):
        keys.add(name_key(match.group(1)))  # bare name, without the article
        article = match.group(2)
        sep = "" if article.endswith(("'", "\u2019")) else " "
        keys.add(name_key(f"{article}{sep}{match.group(1)}"))
    return {k for k in keys if k}


def plain(text: str) -> str:
    """Headword or form without markup nor trailing punctuation (order kept)."""
    return _TRAILING.sub("", _ITALIC_MARKUP.sub("", text).strip())


def fronted(text: str) -> str:
    """Headword or form without markup, with a trailing article put back in front.

    ``Quesnoy-Fictif (Le),`` gives ``Le Quesnoy-Fictif``.
    """
    cleaned = _TRAILING.sub("", _ITALIC_MARKUP.sub("", text).strip())
    match = _INVERTED.match(cleaned)
    if not match or not match.group(1):
        return cleaned
    article = match.group(2)
    article = article[0].upper() + article[1:]
    sep = "" if article.endswith(("'", "\u2019")) else " "
    return f"{article}{sep}{match.group(1)}"


def _text(element: ET.Element) -> str:
    return " ".join("".join(element.itertext()).split())


def _clean(text: str) -> str:
    return _TRAILING.sub("", text.strip())


def _kind(definition: ET.Element | None) -> str | None:
    if definition is None:
        return None
    typology = definition.find("typologie")
    if typology is None:
        return None
    text = unicodedata.normalize("NFD", _text(typology).lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("lieu dit", "lieu-dit")
    words = text.split()
    first = words[0] if words else ""
    return first if first in KINDS else None


def _forms(article: ET.Element) -> tuple[str, ...]:
    forms: list[str] = []
    for ancient in article.findall("forme_ancienne"):
        current = ""
        previous_tail = ""
        for child in ancient:
            if child.tag != "i":
                previous_tail = ""
                continue
            piece = "".join(child.itertext())
            if current and previous_tail.strip() in ("[", "]", ""):
                current += piece
            else:
                if current:
                    forms.append(_clean(current))
                current = piece
            previous_tail = child.tail or ""
        if current:
            forms.append(_clean(current))
    return tuple(f for f in forms if f)


def _build(element: ET.Element, department: str) -> Article | None:
    article_id = (element.get("id") or "").strip()
    vedette = element.find("vedette")
    headword = _clean(_text(vedette)) if vedette is not None else ""
    own = element.findtext("insee")
    insee = own.strip() if own and own.strip() else None
    definition = element.find("definition")
    commune_insee = None
    if definition is not None:
        for commune in definition.iter("commune"):
            code = (commune.get("insee") or "").strip()
            if code:
                commune_insee = code
                break
    if not article_id or not headword or (insee is None and commune_insee is None):
        return None
    return Article(
        article_id,
        department,
        headword,
        insee,
        commune_insee,
        _kind(definition),
        _forms(element),
    )


def _iterate(path: Path, counter: list[int] | None) -> Iterator[Article]:
    department = ""
    root: ET.Element | None = None
    for event, element in ET.iterparse(path, events=("start", "end")):
        if event == "start":
            if root is None:
                root = element
            if element.tag == "DICTIONNAIRE":
                department = (element.get("dep") or "").strip()
            continue
        if element.tag != "article":
            continue
        article = _build(element, department)
        element.clear()
        if root is not None and root is not element:
            root.clear()
        if article is None:
            if counter is not None:
                counter[0] += 1
            continue
        yield article


def parse_dicotopo(path: Path) -> Iterator[Article]:
    """Yield the usable articles of a department file, element by element."""
    return _iterate(path, None)


def parse_with_stats(path: Path) -> tuple[list[Article], int]:
    """Return the usable articles and the number of skipped ones."""
    counter = [0]
    articles = list(_iterate(path, counter))
    return articles, counter[0]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id TEXT PRIMARY KEY, department TEXT NOT NULL, headword TEXT NOT NULL,
    insee TEXT, commune_insee TEXT, kind TEXT, forms TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forms (key TEXT NOT NULL, article_id TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS forms_key ON forms (key);
CREATE INDEX IF NOT EXISTS forms_article ON forms (article_id);
CREATE TABLE IF NOT EXISTS departments (
    department TEXT PRIMARY KEY, downloaded_at TEXT NOT NULL,
    articles INTEGER NOT NULL, skipped INTEGER NOT NULL
);
"""

_COLUMNS = "id, department, headword, insee, commune_insee, kind, forms"


def _row_article(
    row: tuple[str, str, str, str | None, str | None, str | None, str],
) -> Article:
    return Article(
        row[0], row[1], row[2], row[3], row[4], row[5], tuple(json.loads(row[6]))
    )


class DicoTopoIndex:
    """SQLite index of the indexed DicoTopo departments (forms by key)."""

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)

    def add_department(
        self, department: str, xml: Path, downloaded_at: str
    ) -> tuple[int, int]:
        """(Re)index a department in one transaction: ``(indexed, skipped)``."""
        counter = [0]
        indexed = 0
        db = self._connect()
        try:
            with db:  # rolled back on any parse or SQL error
                self._delete(db, department)
                for article in _iterate(xml, counter):
                    db.execute("DELETE FROM forms WHERE article_id = ?", (article.id,))
                    db.execute(
                        f"INSERT OR REPLACE INTO articles ({_COLUMNS}) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            article.id,
                            department,
                            article.headword,
                            article.insee,
                            article.commune_insee,
                            article.kind,
                            json.dumps(article.forms, ensure_ascii=False),
                        ),
                    )
                    keys: set[str] = set()
                    for text in (article.headword, *article.forms):
                        keys |= form_keys(text)
                    db.executemany(
                        "INSERT INTO forms (key, article_id) VALUES (?, ?)",
                        [(k, article.id) for k in sorted(keys)],
                    )
                    indexed += 1
                db.execute(
                    "INSERT OR REPLACE INTO departments VALUES (?, ?, ?, ?)",
                    (department, downloaded_at, indexed, counter[0]),
                )
        finally:
            db.close()
        return indexed, counter[0]

    @staticmethod
    def _delete(db: sqlite3.Connection, department: str) -> None:
        db.execute(
            "DELETE FROM forms WHERE article_id IN "
            "(SELECT id FROM articles WHERE department = ?)",
            (department,),
        )
        db.execute("DELETE FROM articles WHERE department = ?", (department,))
        db.execute("DELETE FROM departments WHERE department = ?", (department,))

    def remove(self, department: str) -> None:
        """Drop a department from the index."""
        db = self._connect()
        try:
            with db:
                self._delete(db, department)
        finally:
            db.close()

    def departments(self) -> dict[str, str]:
        """Indexed departments with their download date."""
        db = self._connect()
        try:
            rows = db.execute(
                "SELECT department, downloaded_at FROM departments ORDER BY rowid"
            ).fetchall()
        finally:
            db.close()
        return {str(d): str(t) for d, t in rows}

    def lookup(self, key: str, department: str) -> list[Article]:
        """Articles of a department with a headword or form of this key.

        ``key`` is already normalised: pass ``form_key(text)``.
        """
        db = self._connect()
        try:
            rows = db.execute(
                f"SELECT {_COLUMNS} FROM articles WHERE department = ? AND id IN "
                "(SELECT article_id FROM forms WHERE key = ?) ORDER BY id",
                (department, key),
            ).fetchall()
        finally:
            db.close()
        return [_row_article(r) for r in rows]

    def get(self, article_id: str) -> Article | None:
        """One article by its identifier."""
        db = self._connect()
        try:
            row = db.execute(
                f"SELECT {_COLUMNS} FROM articles WHERE id = ?", (article_id,)
            ).fetchone()
        finally:
            db.close()
        return None if row is None else _row_article(row)
