"""The pivot (design § 9): ``core``'s tables, plus the places decided by the user.

``build_pivot`` keeps every ``core`` table, its columns (names and relative
order) and its values. Right after each place column it inserts:

- ``<prefix>_lieu_id``: the place of the writing when its decision is
  ``validated``, else ``None`` (rejected or undecided: the original writing
  stays alone in its column);
- ``<prefix>_complement`` where ``core`` has none (``evenements`` already has
  ``complement``).

The writing key and the complement come from ``places.collect.split_place``,
so the lookup key is exactly the registry's decision key (§ 6.3).

Two tables follow ``core``'s:

- ``lieux``: the places referenced by a validated writing of these tables,
  sorted by ``lieu_id``; one column per element kind, then one
  ``<column>_origine`` per element;
- ``ecritures_lieux``: every writing of these tables that has a decision
  (validated or rejected), sorted by writing.

The registry stores English codes; the pivot writes the French values of the
design (§ 6.3) through ``STATUS_VALUES`` and ``ORIGIN_VALUES``. An unknown
stored code raises ``ValueError`` instead of passing through.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from geneweb_py.formats.tables import Column, Row, Table, TableSpec

from ..places.collect import split_place
from ..places.model import ElementKind
from ..store.registry import Decision, PlaceRegistry

STATUS_VALUES: dict[str, str] = {"validated": "valide", "rejected": "rejete"}
ORIGIN_VALUES: dict[str, str] = {
    "rule": "regle",
    "manual": "manuel",
    "reference": "referentiel",
    "llm": "llm",
}


def _french(values: dict[str, str], code: str | None, what: str) -> str | None:
    if code is None:
        return None
    try:
        return values[code]
    except KeyError:
        raise ValueError(f"unknown stored {what}: {code!r}") from None


# lieux column -> (element kind, French label for the description)
PLACE_FIELDS: tuple[tuple[str, ElementKind, str], ...] = (
    ("commune", "commune", "Commune retenue."),
    ("code_insee", "insee_code", "Code INSEE de la commune (COG)."),
    ("code_postal", "postal_code", "Code postal."),
    ("departement", "department", "Département."),
    ("region", "region", "Région (actuelle ou ancienne)."),
    ("pays", "country", "Pays."),
    ("ancien_nom", "former_name", "Ancien nom ou commune fusionnée."),
)

_ORIGIN = (
    "Origine de « {column} » : regle (règle de l'atelier), manuel (saisie), "
    "referentiel (référentiel externe) ou llm ; vide si la valeur est vide."
)

LIEUX = TableSpec(
    "lieux",
    (
        Column(
            "lieu_id",
            "text",
            "Identifiant stable du lieu (UUID) dans le référentiel personnel.",
        ),
        *(Column(column, "text", label) for column, _, label in PLACE_FIELDS),
        *(
            Column(f"{column}_origine", "text", _ORIGIN.format(column=column))
            for column, _, _ in PLACE_FIELDS
        ),
    ),
    primary_key="lieu_id",
)

ECRITURES_LIEUX = TableSpec(
    "ecritures_lieux",
    (
        Column(
            "ecriture",
            "text",
            "Écriture du lieu telle qu'écrite, complément retiré.",
        ),
        Column("lieu_id", "text", "Lieu retenu (lieux.lieu_id), vide si rejetée."),
        Column(
            "statut",
            "text",
            "valide (rattachée à un lieu) ou rejete (pas un lieu exploitable).",
        ),
    ),
    primary_key="ecriture",
)


@dataclass(frozen=True)
class _PlaceColumn:
    column: str
    place_id: Column
    complement: Column | None


def _place_id(name: str, what: str) -> Column:
    return Column(name, "text", f"{what} (lieux.lieu_id), vide si non validé.")


def _complement(name: str, what: str) -> Column:
    return Column(name, "text", f"{what} (établissement, adresse…).")


# table -> its place columns and the columns inserted after each
_PLACE_COLUMNS: dict[str, tuple[_PlaceColumn, ...]] = {
    "personnes": (
        _PlaceColumn(
            "naissance_lieu",
            _place_id("naissance_lieu_id", "Lieu de naissance validé"),
            _complement("naissance_complement", "Complément du lieu de naissance"),
        ),
        _PlaceColumn(
            "deces_lieu",
            _place_id("deces_lieu_id", "Lieu de décès validé"),
            _complement("deces_complement", "Complément du lieu de décès"),
        ),
    ),
    "familles": (
        _PlaceColumn(
            "mariage_lieu",
            _place_id("mariage_lieu_id", "Lieu du mariage validé"),
            _complement("mariage_complement", "Complément du lieu du mariage"),
        ),
    ),
    "evenements": (_PlaceColumn("lieu", _place_id("lieu_id", "Lieu validé"), None),),
}


def _spec(spec: TableSpec, places: Sequence[_PlaceColumn]) -> TableSpec:
    after = {p.column: p for p in places}
    columns: list[Column] = []
    for column in spec.columns:
        columns.append(column)
        place = after.get(column.name)
        if place is not None:
            columns.append(place.place_id)
            if place.complement is not None:
                columns.append(place.complement)
    return TableSpec(spec.name, tuple(columns), spec.primary_key)


def _writings(tables: Sequence[Table]) -> set[str]:
    found: set[str] = set()
    for table in tables:
        for place in _PLACE_COLUMNS.get(table.spec.name, ()):
            for row in table.rows:
                split = split_place(row.get(place.column))
                if split is not None:
                    found.add(split[0])
    return found


def _row(
    row: Row,
    spec: TableSpec,
    places: Sequence[_PlaceColumn],
    decisions: dict[str, Decision],
) -> Row:
    values = dict(row)
    for place in places:
        split = split_place(row.get(place.column))
        decision = decisions.get(split[0]) if split is not None else None
        values[place.place_id.name] = (
            decision.place_id
            if decision is not None and decision.status == "validated"
            else None
        )
        if place.complement is not None:
            values[place.complement.name] = split[1] if split is not None else None
    return {name: values.get(name) for name in spec.column_names}


def build_pivot(tables: Sequence[Table], registry: PlaceRegistry) -> list[Table]:
    """``core``'s tables with place ids and complements, then ``lieux`` and
    ``ecritures_lieux``. The input tables are not modified."""
    decisions = registry.decisions(_writings(tables))
    result: list[Table] = []
    for table in tables:
        places = _PLACE_COLUMNS.get(table.spec.name)
        if places is None:
            result.append(Table(table.spec, [dict(r) for r in table.rows]))
            continue
        spec = _spec(table.spec, places)
        result.append(
            Table(spec, [_row(r, spec, places, decisions) for r in table.rows])
        )
    place_ids = sorted(
        {
            d.place_id
            for d in decisions.values()
            if d.status == "validated" and d.place_id is not None
        }
    )
    place_rows: list[Row] = []
    for place_id in place_ids:
        place = registry.place(place_id)
        values: Row = {"lieu_id": place_id}
        for column, kind, _ in PLACE_FIELDS:
            values[column] = place.fields.get(kind)
        for column, kind, _ in PLACE_FIELDS:
            values[f"{column}_origine"] = _french(
                ORIGIN_VALUES, place.origins.get(kind), "origin"
            )
        place_rows.append(values)
    result.append(Table(LIEUX, place_rows))
    result.append(
        Table(
            ECRITURES_LIEUX,
            [
                {
                    "ecriture": d.writing,
                    "lieu_id": d.place_id if d.status == "validated" else None,
                    "statut": _french(STATUS_VALUES, d.status, "status"),
                }
                for d in sorted(decisions.values(), key=lambda d: d.writing)
            ],
        )
    )
    return result
