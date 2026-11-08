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

Four tables follow ``core``'s:

- ``lieux``: the places referenced by a validated writing of these tables,
  sorted by ``lieu_id``; the French view of the validated levels (``french_view``,
  with the former commune), the ``libelle`` (``chain_label``), the coordinates of
  the most precise validated level that has some, then one ``<column>_origine``
  per view column (the postal code takes the place's postal origin). A place
  without validated level gets empty columns;
- ``niveaux_lieux``: the validated levels of those places, ranks renumbered
  0..n-1 (``validated``), sorted by place then rank; proposed levels are never
  exported;
- ``precisions_occurrences``: the arrondissement precision of each occurrence
  (``build_pivot``'s ``precisions``), one row per candidate (a ``conflit`` or
  ``ambigu`` gives several); an empty arrondissement id is "no arrondissement"
  and exports empty ``arrondissement`` and ``arrondissement_id``; an undated
  occurrence exports an empty ``periode``;
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
from ..places.levels import (
    Level,
    ViewField,
    chain_label,
    french_view,
    validated,
    view_origins,
)
from ..project import OccurrencePrecision
from ..refdata.arrondissements import name_of
from ..sources.dicotopo.source import article_link
from ..store.registry import Decision, PlaceRegistry

STATUS_VALUES: dict[str, str] = {"validated": "valide", "rejected": "rejete"}
ORIGIN_VALUES: dict[str, str] = {
    "written": "ecrit",
    "rule": "regle",
    "manual": "manuel",
    "insee": "insee",
    "paris": "paris",
    "dicotopo": "dicotopo",
    "geonames": "geonames",
    "llm": "llm",
}


def _level_source(level: Level) -> str | None:
    """The level's source; a DicoTopo level without one gets its article link."""
    if level.source is None and level.origin == "dicotopo" and level.identifier:
        return article_link(level.identifier)
    return level.source


def _french(values: dict[str, str], code: str | None, what: str) -> str | None:
    if code is None:
        return None
    try:
        return values[code]
    except KeyError:
        raise ValueError(f"unknown stored {what}: {code!r}") from None


# lieux column -> (french view field, French label for the description)
PLACE_FIELDS: tuple[tuple[str, ViewField, str], ...] = (
    ("commune", "commune", "Commune actuelle retenue."),
    ("code_insee", "insee_code", "Code INSEE de la commune (COG)."),
    ("code_postal", "postal_code", "Code postal."),
    ("departement", "department", "Département."),
    ("region", "region", "Région (actuelle ou ancienne)."),
    ("pays", "country", "Pays."),
    (
        "commune_historique",
        "historical_commune",
        "Ancienne commune (fusion, association ou délégation), si le lieu en est une.",
    ),
    (
        "code_insee_historique",
        "historical_insee",
        "Code INSEE de l'ancienne commune.",
    ),
)

_ORIGIN = (
    "Origine de « {column} » : ecrit (écrit dans la base), regle (règle de "
    "l'atelier), manuel (saisie), insee (référentiel INSEE), paris, dicotopo, "
    "geonames ou llm ; vide si la valeur est vide."
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
        Column(
            "libelle",
            "text",
            "Noms des niveaux validés, du plus précis au plus large, "
            "séparés par une virgule.",
        ),
        Column(
            "latitude",
            "real",
            "Latitude du niveau validé le plus précis qui en a une.",
        ),
        Column(
            "longitude",
            "real",
            "Longitude du niveau validé le plus précis qui en a une.",
        ),
        *(
            Column(f"{column}_origine", "text", _ORIGIN.format(column=column))
            for column, _, _ in PLACE_FIELDS
        ),
    ),
    primary_key="lieu_id",
)

NIVEAUX_LIEUX = TableSpec(
    "niveaux_lieux",
    (
        Column("lieu_id", "text", "Lieu (lieux.lieu_id)."),
        Column(
            "rang",
            "int",
            "Rang du niveau validé dans la chaîne : 0 = le plus précis, puis 1, 2…",
        ),
        Column("nom", "text", "Nom du niveau (normalisé)."),
        Column("nom_ecrit", "text", "Nom tel qu'écrit dans la base, si différent."),
        Column(
            "type",
            "text",
            "Type du niveau (commune, departement, commune_historique…) ; "
            "vide si non reconnu.",
        ),
        Column(
            "nature",
            "text",
            "Pour une commune historique : fusion, associee ou deleguee.",
        ),
        Column("identifiant", "text", "Code du niveau (INSEE, code de département…)."),
        Column("source", "text", "Référentiel et millésime du niveau (COG 2026…)."),
        Column("debut", "text", "Début de validité du niveau, si connu."),
        Column("fin", "text", "Fin de validité du niveau, si connue."),
        Column("latitude", "real", "Latitude du niveau, si connue."),
        Column("longitude", "real", "Longitude du niveau, si connue."),
        Column("origine", "text", _ORIGIN.format(column="le niveau")),
    ),
)

CLUE_VALUES = {
    "code": "code",
    "number": "numero",
    "street": "rue",
    "manual": "manuel",
}
PRECISION_STATUS_VALUES = {
    "applied": "applique",
    "conflict": "conflit",
    "uncertain": "incertain",
    "ambiguous": "ambigu",
}

PRECISIONS_OCCURRENCES = TableSpec(
    "precisions_occurrences",
    (
        Column("table", "text", "Table de l'occurrence (personnes, familles…)."),
        Column("ligne_id", "text", "Identifiant de la ligne dans cette table."),
        Column("colonne", "text", "Colonne du lieu dans cette table."),
        Column(
            "lieu_id",
            "text",
            "Lieu validé de l'écriture (lieux.lieu_id), vide sinon.",
        ),
        Column(
            "periode",
            "text",
            "Période de l'arrondissement : paris-1795 (avant 1860), paris-1860, "
            "lyon, marseille ; vide si l'occurrence n'est pas datée.",
        ),
        Column(
            "arrondissement",
            "text",
            "Nom de l'arrondissement ; vide si aucun arrondissement.",
        ),
        Column(
            "arrondissement_id",
            "text",
            "Identifiant de l'arrondissement (75107, paris-1795-07, 69381…, "
            "ou paris-07 et 751NN pour une occurrence sans date) ; "
            "vide si aucun arrondissement.",
        ),
        Column("quartier", "text", "Quartier de Paris, si connu."),
        Column("quartier_id", "text", "Identifiant du quartier, si connu."),
        Column(
            "indice",
            "text",
            "Indice qui désigne cet arrondissement : code, numero, rue ou manuel.",
        ),
        Column(
            "statut",
            "text",
            "applique, conflit (une ligne par candidat), incertain ou ambigu "
            "(une ligne par candidat).",
        ),
    ),
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


def _precision_rows(
    precisions: Sequence[OccurrencePrecision], decisions: dict[str, Decision]
) -> list[Row]:
    rows: list[Row] = []
    for item in precisions:
        precision = item.precision
        status = _french(PRECISION_STATUS_VALUES, precision.status, "status")
        # same rule as the core rows: only a validated writing has a place id
        decision = decisions.get(item.writing)
        place_id = (
            decision.place_id
            if decision is not None and decision.status == "validated"
            else None
        )
        for candidate in precision.candidates:
            # an empty arrondissement id means "no arrondissement": no name invented
            known = candidate.arrondissement_id != ""
            rows.append(
                {
                    "table": item.occurrence.table,
                    "ligne_id": item.occurrence.row_id,
                    "colonne": item.occurrence.column,
                    "lieu_id": place_id,
                    "periode": precision.period or None,
                    "arrondissement": (
                        name_of(candidate.arrondissement_id) if known else None
                    ),
                    "arrondissement_id": candidate.arrondissement_id if known else None,
                    "quartier": candidate.quartier,
                    "quartier_id": candidate.quartier_id,
                    "indice": _french(CLUE_VALUES, candidate.clue, "clue"),
                    "statut": status,
                }
            )
    return rows


def build_pivot(
    tables: Sequence[Table],
    registry: PlaceRegistry,
    precisions: Sequence[OccurrencePrecision] = (),
) -> list[Table]:
    """``core``'s tables with place ids and complements, then ``lieux``,
    ``niveaux_lieux``, ``precisions_occurrences`` and ``ecritures_lieux``.
    The input tables are not modified."""
    decisions = registry.decisions(_writings(tables))
    precision_writings = {p.writing for p in precisions} - decisions.keys()
    precision_decisions = {**decisions, **registry.decisions(precision_writings)}
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
    wanted = set(place_ids)
    place_rows: list[Row] = []
    level_rows: list[Row] = []
    for place in registry.places():
        if place.place_id not in wanted:
            continue
        chain = validated(place.levels)
        view = french_view(chain, place.postal_code)
        origins = view_origins(chain)
        values: Row = {"lieu_id": place.place_id}
        for column, field, _ in PLACE_FIELDS:
            values[column] = view.get(field)
        located = next(
            (x for x in chain if x.latitude is not None and x.longitude is not None),
            None,
        )
        values["libelle"] = chain_label(chain) or None
        values["latitude"] = located.latitude if located else None
        values["longitude"] = located.longitude if located else None
        for column, field, _ in PLACE_FIELDS:
            origin = (
                place.postal_origin if field == "postal_code" else origins.get(field)
            )
            values[f"{column}_origine"] = _french(ORIGIN_VALUES, origin, "origin")
        place_rows.append(values)
        for level in chain:
            level_rows.append(
                {
                    "lieu_id": place.place_id,
                    "rang": level.rank,
                    "nom": level.name,
                    "nom_ecrit": level.written,
                    "type": level.type,
                    "nature": level.nature,
                    "identifiant": level.identifier,
                    "source": _level_source(level),
                    "debut": level.start,
                    "fin": level.end,
                    "latitude": level.latitude,
                    "longitude": level.longitude,
                    "origine": _french(ORIGIN_VALUES, level.origin, "origin"),
                }
            )
    result.append(Table(LIEUX, place_rows))
    result.append(Table(NIVEAUX_LIEUX, level_rows))
    result.append(
        Table(PRECISIONS_OCCURRENCES, _precision_rows(precisions, precision_decisions))
    )
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
