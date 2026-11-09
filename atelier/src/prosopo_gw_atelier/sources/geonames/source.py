"""GeoNames as a place source: local index first, web API as a last resort.

The API (checked on 2026-11-08, ``https://secure.geonames.org/``) is used only when a
``geonames_username`` is set and the country has no indexed file, or the name is not
in it:

* ``searchJSON?name_equals=<name>&country=<CC>&featureClass=P&featureClass=A``
  ``&maxRows=10&style=FULL&username=<user>``: ``geonames`` list of places
  (``geonameId``, ``name``, ``lat``, ``lng`` as strings, ``fcl``, ``fcode``,
  ``countryCode``, ``adminCode1/2``, ``adminName1/2``, ``adminId1/2``, ``population``).
* ``getJSON?geonameId=<id>&style=FULL&username=<user>``: one place, same fields.
* Errors come as ``{"status": {"value": N, "message": ...}}``: 18 and 20 are daily
  limits, 19 the hourly one, 10 an unknown user name.

Quotas: one request every 4 seconds (``RateLimiter``), at most 10 000 per UTC day
(counter kept in ``api_counter.json``: date and number only). A reached quota raises
``QuotaReached``: the hourly limit (19) waits for the next full hour UTC, HTTP 429
for one hour from now, daily ones for the next UTC midnight; the worker pauses the
GeoNames ``match`` jobs until then.

The user name is in the query string. It is never logged, never put in a message,
a cache key, a result or the counter file, and errors raised from API calls are built
from the status code or from the generic messages of ``fetch`` and raised outside
any ``except`` block, so no exception chain carries the URL.

Candidates carry ``identifier`` ``"<geonameid>"``, ``source_text`` ``"GeoNames <date>"``
(extraction date of the local file, or the query date for API answers), the
coordinates and the population. ``type`` is the level type of the place for its country
(``localite`` for a populated place, see ``types.level_type``; ``None`` when unknown)
and ``parents`` are proposed levels, typed the same way, for the second- and first-level
divisions (smallest first, ranks from 1).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sqlite3
import tempfile
import threading
import time
import urllib.error
import urllib.parse
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from prosopo_gw_atelier.places.cluster import name_key
from prosopo_gw_atelier.places.levels import Level, renumber
from prosopo_gw_atelier.sources.base import (
    LevelQuery,
    PermanentSourceError,
    QuotaReached,
    SourceCandidate,
    SourceError,
)
from prosopo_gw_atelier.sources.fetch import Opener, get_json
from prosopo_gw_atelier.sources.geonames.index import (
    GeoNamesIndex,
    GeoPlace,
    check_country,
)
from prosopo_gw_atelier.sources.geonames.types import level_type
from prosopo_gw_atelier.sources.queue import RateLimiter, SourceQueue
from prosopo_gw_atelier.store.config import LocalConfig

__all__ = ["GEONAMES", "GeoNamesSource", "QuotaReached", "proposals", "queries_for"]

logger = logging.getLogger(__name__)

GEONAMES = "geonames"
API_URL = "https://secure.geonames.org/"
DAILY_LIMIT = 10_000
MIN_INTERVAL = 4.0
_HOURLY_CODES = frozenset({19})
_DAILY_CODES = frozenset({18, 20})
_STATUS_TEXT = {
    10: "identifiant refusé",
    18: "plafond journalier",
    19: "plafond horaire",
    20: "plafond journalier",
    11: "service indisponible",
    12: "service indisponible",
    13: "erreur de base de données",
}


def _next_hour(now: float) -> float:
    moment = datetime.fromtimestamp(now, UTC)
    return (
        moment.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    ).timestamp()


def _next_midnight(now: float) -> float:
    moment = datetime.fromtimestamp(now, UTC)
    day = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return (day + timedelta(days=1)).timestamp()


def _num(value: object) -> float | None:
    try:
        return float(str(value))
    except ValueError:
        return None


def _int(value: object) -> int:
    try:
        return int(str(value))
    except ValueError:
        return 0


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


class GeoNamesSource:
    name = GEONAMES

    def __init__(
        self,
        index: GeoNamesIndex,
        *,
        config: LocalConfig,
        counter_path: Path,
        opener: Opener | None = None,
        limiter: RateLimiter | None = None,
        clock: Callable[[], float] = time.time,
        queue: SourceQueue | None = None,
    ) -> None:
        self._queue = queue
        self._index = index
        self._config = config
        self._counter_path = counter_path
        self._opener = opener
        self._limiter = limiter or RateLimiter(MIN_INTERVAL)
        self._clock = clock
        self._lock = threading.Lock()

    # -- Source interface -------------------------------------------------

    def covers(self, query: LevelQuery) -> bool:
        country = self._country(query)
        return country is not None and self._extraction(country) is not None

    def can_answer(self, query: LevelQuery) -> bool:
        """Country indexed, or a user name set (API) for a known country."""
        country = self._country(query)
        if country is None:
            return False
        return self._api_allowed or self._extraction(country) is not None

    def search(self, query: LevelQuery) -> list[SourceCandidate]:
        country = self._country(query)
        key = name_key(query.name)
        if country is None or not key:
            return []
        date = self._extraction(country)
        if date is not None:
            try:
                local = self._index.lookup(country, key)
            except sqlite3.Error:
                logger.warning("Index GeoNames illisible", exc_info=True)
                local = []
            if local:
                return [self._local_candidate(p, date) for p in local]
        if not self._api_allowed:
            return []
        today = self._today()
        entries = self._api_search(query.name, country)
        return [c for e in entries if (c := self._api_candidate(e, today)) is not None]

    def article(self, identifier: str) -> SourceCandidate | None:
        if not identifier.isdigit():
            return None
        geonameid = int(identifier)
        for country, date in self._countries().items():
            try:
                place = self._index.get(country, geonameid)
            except sqlite3.Error:
                continue
            if place is not None:
                return self._local_candidate(place, date)
        if not self._api_allowed:
            return None
        entry = self._api_article(geonameid)
        return None if entry is None else self._api_candidate(entry, self._today())

    # -- local helpers ----------------------------------------------------

    @property
    def _api_allowed(self) -> bool:
        return bool(self._config.geonames_username)

    @staticmethod
    def _country(query: LevelQuery) -> str | None:
        if not query.country:
            return None
        try:
            return check_country(query.country.strip().upper())
        except SourceError:
            return None

    def _countries(self) -> dict[str, str]:
        # A view must never fail because the index is busy or damaged.
        try:
            return self._index.countries()
        except sqlite3.Error:
            logger.warning("Index GeoNames illisible", exc_info=True)
            return {}

    def _extraction(self, country: str) -> str | None:
        return self._countries().get(country)

    def _today(self) -> str:
        return datetime.fromtimestamp(self._clock(), UTC).date().isoformat()

    def _parents(
        self, country: str, admin1: str, admin2: str, date: str
    ) -> tuple[Level, ...]:
        """Typed, proposed levels for ADM2 then ADM1 (names known from the index)."""
        found: list[tuple[str, int, str | None]] = []
        if admin1 and admin2:
            second = self._index.admin_name(country, admin1, admin2)
            if second is not None:
                found.append((*second, level_type("ADM2", country)))
        if admin1:
            first = self._index.admin_name(country, admin1)
            if first is not None:
                found.append((*first, level_type("ADM1", country)))
        return _levels(found, date)

    def _local_candidate(self, place: GeoPlace, date: str) -> SourceCandidate:
        try:
            parents = self._parents(place.country, place.admin1, place.admin2, date)
        except sqlite3.Error:
            parents = ()
        return SourceCandidate(
            source=GEONAMES,
            identifier=str(place.geonameid),
            name=place.name,
            type=level_type(place.feature_code, place.country),
            parents=parents,
            latitude=place.latitude,
            longitude=place.longitude,
            link=_link(place.geonameid),
            source_text=f"GeoNames {date}",
            population=place.population,
            feature_code=place.feature_code,
        )

    # -- API --------------------------------------------------------------

    def _api_candidate(
        self, entry: dict[str, object], date: str
    ) -> SourceCandidate | None:
        geonameid = _int(entry.get("geonameId"))
        name = _text(entry.get("name"))
        if not geonameid or not name:
            return None
        country = _text(entry.get("countryCode")).upper()
        found: list[tuple[str, int, str | None]] = []
        for number in ("2", "1"):
            admin = _text(entry.get(f"adminName{number}"))
            if admin and admin != name:
                found.append(
                    (
                        admin,
                        _int(entry.get(f"adminId{number}")),
                        level_type(f"ADM{number}", country),
                    )
                )
        return SourceCandidate(
            source=GEONAMES,
            identifier=str(geonameid),
            name=name,
            type=level_type(_text(entry.get("fcode")), country),
            parents=_levels(found, date),
            latitude=_num(entry.get("lat")),
            longitude=_num(entry.get("lng")),
            link=_link(geonameid),
            source_text=f"GeoNames {date}",
            population=_int(entry.get("population")),
            feature_code=_text(entry.get("fcode")) or None,
        )

    def _api_search(self, name: str, country: str) -> list[dict[str, object]]:
        params = [
            ("name_equals", name),
            ("country", country),
            ("featureClass", "P"),
            ("featureClass", "A"),
            ("maxRows", "10"),
            ("style", "FULL"),
        ]
        data = self._api_get("searchJSON", params)
        entries = data.get("geonames")
        if not isinstance(entries, list):
            raise SourceError("Requête impossible : réponse non valide (liste absente)")
        return [e for e in entries if isinstance(e, dict)]

    def _api_article(self, geonameid: int) -> dict[str, object] | None:
        data = self._api_get(
            "getJSON", [("geonameId", str(geonameid)), ("style", "FULL")]
        )
        return data if data.get("geonameId") else None

    def _api_get(self, method: str, params: list[tuple[str, str]]) -> dict[str, object]:
        """One rate-limited, counted API call; see the module docstring."""
        username = self._config.geonames_username
        if not username:
            raise SourceError("Aucun identifiant GeoNames n'est saisi.")
        if self._queue is not None:
            paused = self._queue.paused_until(GEONAMES)
            if paused is not None:
                raise QuotaReached(
                    "Requêtes GeoNames en pause (plafond atteint)", paused
                )
        self._count_request()
        self._limiter.wait()
        url = f"{API_URL}{method}?" + urllib.parse.urlencode(
            [*params, ("username", username)]
        )
        data: object = None
        message: str | None = None
        rate_limited = False
        try:
            data = get_json(url, opener=self._opener)
        except SourceError as exc:
            cause = exc.__cause__
            rate_limited = (
                isinstance(cause, urllib.error.HTTPError) and cause.code == 429
            )
            message = str(exc)
        # Raised outside the except block: no __cause__ or __context__ with the URL.
        if rate_limited:
            raise QuotaReached(
                "GeoNames limite le nombre de requêtes (HTTP 429)",
                self._clock() + 3600,
            )
        if message is not None:
            raise SourceError(message)
        if not isinstance(data, dict):
            raise SourceError("Requête impossible : réponse non valide (objet attendu)")
        self._check_status(data)
        return data

    def _check_status(self, data: dict[str, object]) -> None:
        status = data.get("status")
        if not isinstance(status, dict):
            return
        code = _int(status.get("value"))
        text = _STATUS_TEXT.get(code, "erreur")
        message = f"GeoNames a refusé la requête (code {code} : {text})"
        now = self._clock()
        if code in _HOURLY_CODES:
            raise QuotaReached(message, _next_hour(now))
        if code in _DAILY_CODES:
            raise QuotaReached(message, _next_midnight(now))
        if code == 10:
            raise PermanentSourceError(message)
        raise SourceError(message)

    # -- daily counter ----------------------------------------------------

    def _count_request(self) -> None:
        """Count one request against today's limit (UTC); raise when it is reached."""
        now = self._clock()
        today = datetime.fromtimestamp(now, UTC).date().isoformat()
        with self._lock:
            count = 0
            try:
                raw = json.loads(self._counter_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and raw.get("date") == today:
                    count = max(0, _int(raw.get("count")))
            except (OSError, ValueError):
                count = 0
            if count >= DAILY_LIMIT:
                raise QuotaReached(
                    f"Plafond de {DAILY_LIMIT} requêtes GeoNames par jour atteint",
                    _next_midnight(now),
                )
            self._write_counter(today, count + 1)

    def _write_counter(self, today: str, count: int) -> None:
        directory = self._counter_path.parent
        directory.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".counter-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"date": today, "count": count}, handle)
            os.replace(tmp, self._counter_path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise


def _levels(found: list[tuple[str, int, str | None]], date: str) -> tuple[Level, ...]:
    return tuple(
        Level(
            rank,
            name,
            type=type_,
            identifier=str(geonameid) if geonameid else None,
            source=f"GeoNames {date}",
            origin="geonames",
            status="proposed",
        )
        for rank, (name, geonameid, type_) in enumerate(found, start=1)
    )


def _link(geonameid: int) -> str:
    return f"https://www.geonames.org/{geonameid}"


# -- from candidates to proposals --------------------------------------------

MAX_ALTERNATIVES = 5


def _is_target(levels: Sequence[Level]) -> bool:
    """Level 0 is a written, validated level that nothing has typed yet."""
    return bool(levels) and (
        levels[0].status == "validated"
        and levels[0].type is None
        and levels[0].origin == "written"
    )


def _above(levels: Sequence[Level]) -> list[Level]:
    """Written levels above level 0 that can confirm a division (not the country)."""
    return [lv for lv in levels[1:] if lv.status == "validated" and lv.type != "pays"]


def queries_for(levels: Sequence[Level], country_iso: str) -> list[LevelQuery]:
    """Queries for a foreign writing: level 0 first, then each written level above it.

    ``country_iso`` is the ISO 3166 alpha-2 code of the country (the caller finds it
    from the country level). The queries for the upper levels tell ``proposals`` which
    written levels are other divisions of the country. Nothing is asked when level 0 is
    already typed or resolved, or when the code is not valid.
    """
    iso = country_iso.strip().upper()
    try:
        check_country(iso)
    except SourceError:
        return []
    if not _is_target(levels):
        return []
    above = _above(levels)
    queries = [
        LevelQuery(
            name=levels[0].name,
            parents=tuple(lv.name for lv in above),
            country=iso,
        )
    ]
    queries += [LevelQuery(name=lv.name, country=iso) for lv in above]
    return queries


def _own_parents(candidate: SourceCandidate) -> list[Level]:
    """Divisions of the candidate, smallest first, without the candidate itself."""
    return [
        p
        for p in candidate.parents
        if p.identifier is None or p.identifier != candidate.identifier
    ]


def _confirmations(candidate: SourceCandidate, keys: set[str]) -> int:
    return sum(1 for p in _own_parents(candidate) if name_key(p.name) in keys)


def _is_admin(candidate: SourceCandidate) -> bool:
    return (candidate.feature_code or "").startswith("ADM")


def _is_populated(candidate: SourceCandidate) -> bool:
    return (candidate.feature_code or "").startswith("PPL")


def _typed(level: Level, name: str, proposal: Level, source: str | None) -> Level:
    """The written ``level`` replaced by its typed proposal, at the same place.

    The GeoNames name is the proposal's name when it really differs (the written name
    then goes in ``written``); otherwise the written name stays.
    """
    same = name_key(level.name) == name_key(name)
    return replace(
        level,
        name=level.name if same else name,
        written=level.written if same else level.name,
        type=proposal.type,
        identifier=proposal.identifier,
        source=source,
        latitude=proposal.latitude,
        longitude=proposal.longitude,
        origin="geonames",
        status="proposed",
    )


def _reading(levels: Sequence[Level], candidate: SourceCandidate) -> tuple[Level, ...]:
    """``levels`` with the confirmed levels proposed and the missing ones inserted."""
    own = Level(
        0,
        candidate.name,
        type=candidate.type,
        identifier=candidate.identifier,
        latitude=candidate.latitude,
        longitude=candidate.longitude,
    )
    replaced: dict[int, Level] = {
        0: _typed(levels[0], candidate.name, own, candidate.source_text)
    }
    inserted: dict[int, list[Level]] = {}
    free = [i for i in range(1, len(levels)) if _is_above(levels[i])]
    anchor = 0
    for parent in _own_parents(candidate):
        key = name_key(parent.name)
        found = next((i for i in free if name_key(levels[i].name) == key), None)
        if found is None:
            # Missing division: right above the lowest level it contains.
            inserted.setdefault(anchor, []).append(replace(parent, status="proposed"))
            continue
        free.remove(found)
        anchor = max(anchor, found)
        if levels[found].type is None:
            replaced[found] = _typed(levels[found], parent.name, parent, parent.source)
    out: list[Level] = []
    for i, level in enumerate(levels):
        out.append(replaced.get(i, level))
        out.extend(inserted.get(i, ()))
    return renumber(out)


def _is_above(level: Level) -> bool:
    return level.status == "validated" and level.type != "pays"


def proposals(
    levels: Sequence[Level], candidates: Sequence[SourceCandidate]
) -> tuple[tuple[Level, ...], tuple[tuple[Level, ...], ...]]:
    """Chain with its levels proposed by GeoNames, and the alternative readings.

    Same contract as DicoTopo's: a confirmed, untyped written level is replaced in
    place by its proposal (``status="proposed"``, ``origin="geonames"``, type,
    identifier and source; the GeoNames name goes in ``name`` and the written one in
    ``written`` when they differ), missing divisions are inserted as proposed levels
    between the level they contain and the one that contains them, and the ranks are
    renumbered. Other levels, including a written level GeoNames does not know, are
    unchanged.

    Level 0 is read as a populated place of the country, else as an administrative
    division when there is none. The written levels above confirm candidates (a written
    level with the name of the candidate's first- or second-level division) and a
    written level that is another division of the country excludes the candidate
    (``queries_for`` also asks for the upper levels). With confirmations only the
    confirmed candidates remain. One candidate left: its chain. Several (homonyms): the
    most populous is never chosen; the chain is empty and each of the (at most 5, most
    populous first) readings is a whole alternative chain. No candidate: both empty.
    """
    if not _is_target(levels):
        return (), ()
    keys = {name_key(lv.name) for lv in _above(levels)}
    first = name_key(levels[0].name)
    pool: list[SourceCandidate] = []
    seen: set[str] = set()
    for c in candidates:
        if c.source == GEONAMES and c.identifier not in seen:
            seen.add(c.identifier)
            pool.append(c)
    divisions = {
        name_key(c.name) for c in pool if _is_admin(c) and name_key(c.name) in keys
    }

    def foreign(c: SourceCandidate) -> bool:
        mine = {name_key(p.name) for p in _own_parents(c)} | {name_key(c.name)}
        return bool((divisions & keys) - mine - {first})

    def level_zero(c: SourceCandidate) -> bool:
        # candidates of the upper-level queries are not readings of level 0
        return name_key(c.name) not in keys or name_key(c.name) == first

    for readings in (
        [c for c in pool if _is_populated(c) and level_zero(c)],
        [c for c in pool if _is_admin(c) and level_zero(c)],
    ):
        stage = [c for c in readings if not foreign(c)]
        if not stage:
            continue
        confirmed = [c for c in stage if _confirmations(c, keys) > 0]
        kept = confirmed or stage
        if len(kept) == 1:
            return _reading(levels, kept[0]), ()
        ordered = sorted(kept, key=lambda c: -(c.population or 0))
        return (), tuple(_reading(levels, c) for c in ordered[:MAX_ALTERNATIVES])
    return (), ()
