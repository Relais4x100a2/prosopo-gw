"""Exports des organisations candidates : fichier compagnon et deux CSV.

Voir ``core/doc/organizations_candidates_design.md`` § 4. Les CSV sont en UTF-8 avec
BOM, séparés par ``;`` (ouverture directe dans un Excel français).
"""

import csv
import io
from typing import Any, Dict, List, Optional

from ...core.genealogy import Genealogy
from ...core.shared_experiences import SharedExperienceIndex
from ...formats.org_sidecar import sidecar_payload
from .organization_candidates import (
    Candidate,
    CandidateIndex,
    shared_experience_persons,
)

BOM = "﻿"
LIST_SEPARATOR = "|"

# Libellés français des codes (mêmes textes que l'onglet Organisations de la webapp).
TYPE_LABELS: Dict[str, str] = {
    "company": "Entreprise",
    "school": "École",
    "association": "Association",
    "institution": "Institution",
    "religious": "Religieux",
    "military": "Militaire",
    "other": "Autre",
}
NAMED_FROM_LABELS: Dict[str, str] = {
    "tag": "Nom personnalisé",
    "place": "Lieu",
    "typed_event": "Événement typé",
    "occupation_text": "Profession",
    "address": "Adresse",
}
SOURCE_LABELS: Dict[str, str] = {
    "oth": "événement libre",
    "occu": "profession",
    "educ": "éducation",
    "grad": "diplôme",
    "degr": "diplôme",
    "adhe": "adhésion",
    "hosp": "hospitalisation",
    "mser": "service militaire",
    "demm": "service militaire",
    "elec": "élection",
    "ordn": "ordination",
    "occu_attr": "profession (attribut)",
}

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

SHARED_EXPERIENCES_CSV_HEADER: List[str] = [
    "experience",
    "theme",
    "periode",
    "lieux",
    "raison",
    "personne",
    "evenement",
    "annee",
    "lieu",
]

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _safe(text: str) -> str:
    """Neutralise l'interprétation en formule d'un tableur (préfixe ``'``)."""
    return "'" + text if text.startswith(FORMULA_PREFIXES) else text


def _text(value: Optional[Any]) -> str:
    """Cellule de texte : jamais interprétée comme une formule."""
    return "" if value is None else _safe(str(value))


def _label(labels: Dict[str, str], code: Optional[str]) -> str:
    """Libellé français d'un code ; le code lui-même s'il est inconnu."""
    return "" if code is None else _safe(labels.get(code, code))


def _decimal(value: Optional[float]) -> str:
    """Nombre décimal à virgule, lu comme un nombre par un Excel français."""
    return "" if value is None else f"{value:g}".replace(".", ",")


def _sorted(index: CandidateIndex) -> List[Candidate]:
    return sorted(index.candidates.values(), key=lambda c: (c.name.casefold(), c.id))


def _bool(value: bool) -> str:
    return "oui" if value else "non"


def _render(header: List[str], rows: List[List[str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return BOM + buffer.getvalue()


def candidates_csv(index: CandidateIndex) -> str:
    """Une ligne par candidat, triée par nom."""
    rows = [
        [
            _text(c.id),
            _text(c.name),
            _label(TYPE_LABELS, c.type),
            _text(c.place),
            _label(NAMED_FROM_LABELS, c.named_from),
            LIST_SEPARATOR.join(_label(SOURCE_LABELS, s) for s in c.sources),
            _text(c.trigger),
            _decimal(c.confidence),
            _bool(c.needs_review),
            _bool(c.collective),
            str(c.person_count),
            str(c.event_count),
            _text(c.first_year),
            _text(c.last_year),
            _text(LIST_SEPARATOR.join(c.places)),
            _text(LIST_SEPARATOR.join(c.roles)),
        ]
        for c in _sorted(index)
    ]
    return _render(CANDIDATES_CSV_HEADER, rows)


def links_csv(index: CandidateIndex) -> str:
    """Une ligne par membre, triée par organisation puis personne.

    ``statut`` et ``nom_retenu`` sont laissés vides, à remplir par l'utilisateur.
    """
    rows = [
        [
            _text(c.id),
            _text(c.name),
            _text(m.person_id),
            _text(m.person_name),
            _text(m.role),
            _text(m.date),
            _text(m.place),
            _label(SOURCE_LABELS, m.source_event_type),
            _text(m.event_label.replace("_", " ")),
            str(m.witness_count),
            "",
            "",
        ]
        for c in _sorted(index)
        for m in sorted(
            c.members, key=lambda m: (m.person_name.casefold(), m.year or 0)
        )
    ]
    return _render(LINKS_CSV_HEADER, rows)


def _years(start: int, end: int) -> str:
    return str(start) if start == end else f"{start}-{end}"


def _reason_label(kind: str, place: Optional[str], words: Any) -> str:
    if kind == "rare_word":
        return "mot commun : " + ", ".join(words)
    return "même lieu"


def shared_experiences_csv(genealogy: Genealogy, index: SharedExperienceIndex) -> str:
    """Une ligne par événement, dans l'ordre des expériences puis nom replié et année."""
    rows: List[List[str]] = []
    for e in index.items:
        period = _years(e.year_min, e.year_max)
        places = ", ".join(e.places)
        reasons = " ; ".join(_reason_label(r.kind, r.place, r.words) for r in e.reasons)
        for p in shared_experience_persons(genealogy, e):
            rows.append(
                [
                    _text(e.id),
                    _text(e.label),
                    period,
                    _text(places),
                    _text(reasons),
                    _text(p["person_name"]),
                    _text(p["label"]),
                    _years(p["year_start"], p["year_end"]),
                    _text(p["place"]),
                ]
            )
    return _render(SHARED_EXPERIENCES_CSV_HEADER, rows)


def candidates_sidecar(genealogy: Genealogy, index: CandidateIndex) -> Dict[str, Any]:
    """Fichier compagnon limité aux candidats et à leurs liens."""
    return sidecar_payload(genealogy, set(index.candidates))
