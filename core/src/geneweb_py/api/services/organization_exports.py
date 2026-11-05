"""Exports des organisations candidates : fichier compagnon et deux CSV.

Voir ``core/doc/organizations_candidates_design.md`` § 4. Les CSV sont en UTF-8 avec
BOM, séparés par ``;`` (ouverture directe dans un Excel français).
"""

import csv
import io
from typing import Any, Dict, List, Optional

from ...core.genealogy import Genealogy
from ...formats.org_sidecar import sidecar_payload
from .organization_candidates import CandidateIndex

BOM = "﻿"
LIST_SEPARATOR = "|"

CANDIDATES_CSV_HEADER: List[str] = [
    "id",
    "nom",
    "type",
    "lieu",
    "source_du_nom",
    "sources",
    "mot_declencheur",
    "confiance",
    "a_revoir",
    "collectif",
    "nb_personnes",
    "nb_evenements",
    "premiere_annee",
    "derniere_annee",
    "lieux",
    "roles",
]

LINKS_CSV_HEADER: List[str] = [
    "organisation_id",
    "organisation",
    "personne_id",
    "personne",
    "role",
    "date",
    "lieu",
    "type_evenement",
    "evenement",
    "nb_temoins",
    "statut",
    "nom_retenu",
]


def _text(value: Optional[Any]) -> str:
    return "" if value is None else str(value)


def _bool(value: bool) -> str:
    return "oui" if value else "non"


def _render(header: List[str], rows: List[List[str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return BOM + buffer.getvalue()


def candidates_csv(index: CandidateIndex) -> str:
    """Une ligne par candidat."""
    rows = [
        [
            c.id,
            c.name,
            c.type,
            _text(c.place),
            _text(c.named_from),
            LIST_SEPARATOR.join(c.sources),
            _text(c.trigger),
            "" if c.confidence is None else f"{c.confidence:g}",
            _bool(c.needs_review),
            _bool(c.collective),
            str(c.person_count),
            str(c.event_count),
            _text(c.first_year),
            _text(c.last_year),
            LIST_SEPARATOR.join(c.places),
            LIST_SEPARATOR.join(c.roles),
        ]
        for c in index.candidates.values()
    ]
    return _render(CANDIDATES_CSV_HEADER, rows)


def links_csv(index: CandidateIndex) -> str:
    """Une ligne par membre de candidat ; ``statut`` et ``nom_retenu`` à remplir."""
    rows = [
        [
            c.id,
            c.name,
            m.person_id,
            m.person_name,
            _text(m.role),
            _text(m.date),
            _text(m.place),
            m.source_event_type,
            m.event_label.replace("_", " "),
            str(m.witness_count),
            "",
            "",
        ]
        for c in index.candidates.values()
        for m in c.members
    ]
    return _render(LINKS_CSV_HEADER, rows)


def candidates_sidecar(genealogy: Genealogy, index: CandidateIndex) -> Dict[str, Any]:
    """Fichier compagnon limité aux candidats et à leurs liens."""
    return sidecar_payload(genealogy, set(index.candidates))
