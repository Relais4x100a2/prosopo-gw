"""DicoTopo as a place source: local index first, API as a last resort.

DicoTopo is published under CC BY-NC-ND: nothing of it is shipped here. Candidates
are built on the fly from the user's local copy (or from the API) and only proposed.

DicoTopo localises its articles with the INSEE code of 2011; every candidate carries
``parents`` already brought back to the current COG (``commune_historique`` with its
``nature`` when the 2011 commune has disappeared, then ``commune`` of origin
``insee``). DicoTopo never decides the current commune.

API (checked on 2026-11-08, JSON:API, no key): ``https://dicotopo.cths.fr/api/1.0/``

* ``GET search?query=<label>`` returns ``data`` mixing ``place`` entries (``place-id``,
  ``place-label``, ``old-labels`` as ``<dfn>`` HTML, ``localization-insee-code``,
  ``commune-label``, ``dpt``) and ``place-old-label`` entries. The ``dpt`` parameter is
  ignored by the server: the department is filtered here, on the ``dpt`` attribute.
  Only the first page is read.
* ``GET places/<P id>`` returns ``data.attributes`` with the same fields (a commune
  article is recognised by a label equal to its ``commune-label``).
* ``GET places`` (the collection) answers HTTP 500: it is never used.
* Public link of an article: ``https://dicotopo.cths.fr/places/<P id>``.
"""

from __future__ import annotations

import html
import logging
import re
import sqlite3
import urllib.parse
from collections.abc import Sequence
from dataclasses import replace

from ...places.levels import Level, renumber
from ...places.model import Decomposition
from ...refdata import Commune, Former, RefData
from ..base import LevelQuery, SourceCandidate, SourceError
from ..fetch import Opener, get_json
from ..queue import RateLimiter
from .download import DICOTOPO
from .index import Article, DicoTopoIndex, form_key, form_keys, fronted, plain

API_URL = "https://dicotopo.cths.fr/api/1.0/"
LINK_URL = "https://dicotopo.cths.fr/places/"
logger = logging.getLogger(__name__)
_ID = re.compile(r"\AP\d{1,12}\Z")
_DFN = re.compile(r"<dfn>(.*?)</dfn>", re.DOTALL)
_TAG = re.compile(r"<[^>]+>")

__all__ = [
    "API_URL",
    "DICOTOPO",
    "DicoTopoSource",
    "article_link",
    "proposals",
    "queries_for",
]


SUB_TYPES = ("lieu_dit", "hameau")
"""Level types of a DicoTopo article below its commune."""


def _sub_type(kind: str | None) -> str:
    """Level type of a non-commune article: ``hameau`` when its typology says so."""
    return "hameau" if kind == "hameau" else "lieu_dit"


def article_link(identifier: str) -> str:
    """Public page of an article."""
    return f"{LINK_URL}{identifier}"


def _source_text(identifier: str) -> str:
    return f"DicoTopo, {article_link(identifier)}"


def _plain(text: str) -> str:
    return " ".join(html.unescape(_TAG.sub("", text)).split())


def _str(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _dept(value: object) -> str:
    """Department code normalised: stripped, upper case, 1-digit zero-padded."""
    text = str(value).strip().upper() if isinstance(value, (str, int)) else ""
    return f"0{text}" if len(text) == 1 and text.isdigit() else text


class DicoTopoSource:
    name = DICOTOPO

    def __init__(
        self,
        index: DicoTopoIndex,
        ref: RefData,
        *,
        api_enabled: bool,
        opener: Opener | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        self._index = index
        self._ref = ref
        self._api_enabled = api_enabled
        self._opener = opener
        self._limiter = limiter or RateLimiter(1.0)

    # -- Source interface -------------------------------------------------

    def covers(self, query: LevelQuery) -> bool:
        department = self._department(query)
        return department is not None and self._indexed(department)

    def can_answer(self, query: LevelQuery) -> bool:
        """Department indexed, or the API allowed (and a department known)."""
        department = self._department(query)
        return department is not None and (
            self._api_enabled or self._indexed(department)
        )

    def _indexed(self, department: str) -> bool:
        # A view must never fail because the index is busy or damaged.
        try:
            return department in self._index.departments()
        except sqlite3.Error:
            logger.warning("Index DicoTopo illisible", exc_info=True)
            return False

    def search(self, query: LevelQuery) -> list[SourceCandidate]:
        department = self._department(query)
        if department is None:
            return []
        key = form_key(query.name)
        if not key:
            return []
        if department in self._index.departments():
            hits = [(a, key) for a in self._index.lookup(key, department)]
        elif self._api_enabled:
            hits = [(a, key) for a in self._api_search(query.name, department, key)]
        else:
            return []
        out: list[SourceCandidate] = []
        for article, hit_key in hits:
            candidate = self._candidate(article, hit_key)
            if candidate.insee is None:
                continue
            if query.insee is not None and candidate.insee != query.insee:
                continue
            out.append(candidate)
        return out

    def article(self, identifier: str) -> SourceCandidate | None:
        found = self._index.get(identifier)
        if found is None and self._api_enabled and _ID.match(identifier):
            found = self._api_article(identifier)
        return None if found is None else self._candidate(found, None)

    # -- helpers ----------------------------------------------------------

    def _department(self, query: LevelQuery) -> str | None:
        if query.department:
            return _dept(query.department)
        if query.insee:
            commune = self._ref.commune_by_insee(query.insee)
            if commune is not None:
                return commune.department
        return None

    def _candidate(self, article: Article, key: str | None) -> SourceCandidate:
        """Candidate of an article.

        ``name`` is the form that matched ``key``, as written in DicoTopo (an inverted
        headword stays ``Quesnoy-Fictif (Le)``): ``form_keys(name)`` holds the key.
        """
        headword = fronted(article.headword)
        name = headword
        if key is not None:
            for text in (article.headword, *article.forms):
                if key in form_keys(text):
                    name = plain(text)
                    break
        code = article.insee or article.commune_insee
        parents: tuple[Level, ...] = ()
        insee: str | None = None
        if code is not None:
            found = self._ref.current_of(code, headword if article.insee else None)
            if found is not None:
                commune, former = found
                parents = self._parents(commune, former)
                insee = commune.insee
        return SourceCandidate(
            source=DICOTOPO,
            identifier=article.id,
            name=name,
            type="commune" if article.insee else _sub_type(article.kind),
            parents=parents,
            link=article_link(article.id),
            insee=insee,
        )

    def _parents(self, commune: Commune, former: Former | None) -> tuple[Level, ...]:
        source = f"COG {self._ref.cog_vintage}"
        levels: list[Level] = []
        if former is not None:
            levels.append(
                Level(
                    0,
                    former.name,
                    type="commune_historique",
                    identifier=former.insee,
                    source=source,
                    end=former.date or None,
                    nature=None if former.nature == "renommage" else former.nature,
                    origin="insee",
                )
            )
        levels.append(
            Level(
                0,
                commune.name,
                type="commune",
                identifier=commune.insee,
                source=source,
                origin="insee",
            )
        )
        return renumber(levels)

    # -- API --------------------------------------------------------------

    def _get(self, url: str) -> dict[str, object]:
        self._limiter.wait()
        data = get_json(url, opener=self._opener)
        if not isinstance(data, dict):
            raise SourceError("Requête impossible : réponse non valide (objet attendu)")
        return data

    def _api_search(self, name: str, department: str, key: str) -> list[Article]:
        data = self._get(f"{API_URL}search?query={urllib.parse.quote(name)}")
        entries = data.get("data")
        if not isinstance(entries, list):
            raise SourceError("Requête impossible : réponse non valide (data absent)")
        meta = data.get("meta")
        total = meta.get("total-count") if isinstance(meta, dict) else None
        if isinstance(total, int) and total > len(entries):
            logger.debug("DicoTopo: %d results, only %d read", total, len(entries))
        found: dict[str, Article] = {}
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("type") != "place":
                continue
            article = _api_article(entry)
            if article is None or _dept(article.department) != department:
                continue
            if any(key in form_keys(t) for t in (article.headword, *article.forms)):
                found.setdefault(article.id, article)
        return list(found.values())

    def _api_article(self, identifier: str) -> Article | None:
        data = self._get(f"{API_URL}places/{identifier}")
        entry = data.get("data")
        return _api_article(entry) if isinstance(entry, dict) else None


def _is_commune_type(terms: object) -> bool:
    """True when no feature type is given, or when one of them is ``commune``."""
    if not isinstance(terms, list) or not terms:
        return True
    return any(isinstance(t, str) and t.strip().casefold() == "commune" for t in terms)


def _api_article(entry: dict[str, object]) -> Article | None:
    """Article from a JSON:API ``place`` entry (see the module docstring)."""
    raw = entry.get("attributes")
    attributes: dict[str, object] = raw if isinstance(raw, dict) else {}
    identifier = _str(entry.get("id")) or _str(attributes.get("place-id"))
    label = _plain(_str(attributes.get("place-label")))
    code = _str(attributes.get("localization-insee-code"))
    if not _ID.match(identifier) or not label or not code:
        return None
    commune_label = _plain(_str(attributes.get("commune-label")))
    same = bool(commune_label) and form_key(label) == form_key(commune_label)
    # A label equal to the commune label means a commune, unless the entry says that
    # it is another kind of place (a lieu-dit named like its commune).
    own = (
        code
        if same and _is_commune_type(attributes.get("place-feature-types"))
        else None
    )
    old = attributes.get("old-labels")
    forms: list[str] = []
    for text in old if isinstance(old, list) else []:
        match = _DFN.search(str(text))
        form = _plain(match.group(1) if match else str(text))
        if form:
            forms.append(form)
    return Article(
        identifier, _dept(attributes.get("dpt")), label, own, code, None, tuple(forms)
    )


# -- Proposal rules (choix 7 of the plan) ----------------------------------


def _commune_level(levels: Sequence[Level]) -> Level | None:
    return next((lv for lv in levels if lv.type == "commune" and lv.identifier), None)


def _department_code(levels: Sequence[Level], commune: Level | None) -> str | None:
    for level in levels:
        if level.type == "departement" and level.identifier:
            return level.identifier
    if commune is not None and commune.identifier:
        code = commune.identifier
        return code[:3] if code.startswith("97") else code[:2]
    return None


def _targets(levels: Sequence[Level]) -> list[Level]:
    """Written levels with no type: under the resolved commune, or anywhere if none."""
    commune = _commune_level(levels)
    return [
        lv
        for lv in levels
        if lv.status == "validated"
        and lv.type is None
        and lv.origin == "written"
        and (commune is None or lv.rank < commune.rank)
    ]


def queries_for(
    levels: Sequence[Level], decomposition: Decomposition
) -> list[LevelQuery]:
    """Queries for the levels DicoTopo can recognise.

    A level written but not recognised under a resolved commune, or (no resolved
    commune) any such level of a writing whose department is known.
    """
    commune = _commune_level(levels) if decomposition.insee is not None else None
    if commune is None:
        department = _department_code(levels, None)
        if department is None:
            for element in decomposition.elements:
                if element.kind == "department":
                    department = element.value
                    break
    else:
        department = _department_code(levels, commune)
    if department is None:
        return []
    return [
        LevelQuery(
            name=level.name,
            type="lieu_dit",
            parents=(commune.name,) if commune is not None else (),
            country="France",
            department=department,
            insee=commune.identifier if commune is not None else None,
        )
        for level in _targets(levels)
    ]


def _reading(
    chain: Sequence[Level],
    target: Level,
    candidate: SourceCandidate,
    commune: Level | None,
) -> tuple[Level, ...] | None:
    """The chain with ``target`` replaced by the reading of ``candidate``.

    ``commune`` is the commune level resolved before any proposal (or ``None``).
    """
    source = _source_text(candidate.identifier)
    if commune is not None:
        if candidate.type not in SUB_TYPES or candidate.insee != commune.identifier:
            return None
        place = replace(
            target,
            type=candidate.type,
            identifier=candidate.identifier,
            source=source,
            origin="dicotopo",
            status="proposed",
        )
        return renumber([place if lv is target else lv for lv in chain])
    if not candidate.parents:
        return None
    parents = [replace(p, status="proposed") for p in candidate.parents]
    if candidate.type in SUB_TYPES:
        block = [
            replace(
                target,
                type=candidate.type,
                identifier=candidate.identifier,
                source=source,
                origin="dicotopo",
                status="proposed",
            ),
            *parents,
        ]
    else:
        # The article is the commune itself: the written name is one of its old names.
        first = parents[0]
        written = target.name if target.name != first.name else None
        block = [replace(first, written=written), *parents[1:]]
    out: list[Level] = []
    for level in chain:
        if level is target:
            out.extend(block)
        elif (
            level.type not in ("commune", "commune_historique")
            or level.status != "validated"
        ):
            out.append(level)
        # a stray validated commune level is superseded by the proposed commune
    return renumber(out)


def proposals(
    levels: Sequence[Level], candidates: Sequence[SourceCandidate]
) -> tuple[tuple[Level, ...], tuple[tuple[Level, ...], ...]]:
    """Chain with its levels proposed by DicoTopo, and the alternative readings.

    Each written, untyped level (see ``queries_for``) is matched to the candidates
    whose name has the same form key. A level with exactly one reading is replaced in
    the chain (``origin="dicotopo"``, ``status="proposed"``, ``identifier`` ``P…`` and
    ``source`` with the article link). A level with several readings (homonyms, or
    different communes) is never settled silently: each reading becomes a whole
    alternative chain. As soon as one level is ambiguous the chain is empty (never a
    partly changed chain); without any reading at all both results are empty.
    Candidates of another commune than the resolved one are ignored: DicoTopo never
    changes the commune.
    """
    unique = {c.identifier: c for c in candidates if c.source == DICOTOPO}
    chain: tuple[Level, ...] = tuple(levels)
    changed = False
    commune = _commune_level(levels)
    settled = False  # without a resolved commune only one target can settle the chain
    for target in _targets(levels):
        key = form_key(target.name)
        base = chain if commune is not None else tuple(levels)
        readings = [
            r
            for c in sorted(unique.values(), key=lambda c: c.identifier)
            if key in form_keys(c.name)
            for r in [_reading(base, _same(base, target), c, commune)]
            if r is not None
        ]
        if len(readings) > 1:
            return (), tuple(readings)
        if readings and not settled:
            chain, changed = readings[0], True
            settled = commune is None
    return (chain if changed else ()), ()


def _same(chain: Sequence[Level], target: Level) -> Level:
    """The level of ``chain`` that stands for ``target`` (ranks may have moved)."""
    for level in chain:
        if (
            level.name == target.name
            and level.type is None
            and level.origin == "written"
        ):
            return level
    return target
