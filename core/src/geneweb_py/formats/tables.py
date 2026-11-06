"""Tables de l'export : une définition unique, rendue en CSV, JSON et SQLite.

Chaque table est une liste de lignes (``Row``) dont les clés suivent exactement les
colonnes de sa ``TableSpec``. Les identifiants sont partagés entre les tables :
personne et famille = clés de ``Genealogy`` ; événement personnel = ``event_ref`` ;
événement familial = ``family_event_ref``. Conception : ``doc/exports_design.md``.
"""

import hashlib
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple, Union

from typing_extensions import Literal

from ..core.date import Date
from ..core.event import Event, WitnessKind
from ..core.event_to_organization import WITNESS_KIND_ROLES, WITNESS_ROLE, event_ref
from ..core.genealogy import Genealogy
from ..core.person import Gender
from ..core.place import parse_place, place_city

ColumnType = Literal["text", "int", "real", "bool"]
Value = Union[str, int, float, bool, None]
Row = Dict[str, Value]


@dataclass(frozen=True)
class Column:
    """Colonne d'une table : nom, type et description (pour le dictionnaire)."""

    name: str
    type: ColumnType
    description: str


@dataclass(frozen=True)
class TableSpec:
    """Définition d'une table, partagée par tous les rendus."""

    name: str
    columns: Tuple[Column, ...]
    primary_key: Optional[str] = None

    @property
    def column_names(self) -> List[str]:
        return [c.name for c in self.columns]


@dataclass
class Table:
    """Une table et ses lignes."""

    spec: TableSpec
    rows: List[Row]


def _text(name: str, description: str) -> Column:
    return Column(name, "text", description)


def _int(name: str, description: str) -> Column:
    return Column(name, "int", description)


EVENT_TYPE_LABELS: Dict[str, str] = {
    "birt": "Naissance",
    "bapt": "Baptême",
    "deat": "Décès",
    "buri": "Sépulture",
    "crem": "Crémation",
    "occu": "Profession",
    "resi": "Résidence",
    "educ": "Éducation",
    "grad": "Diplôme",
    "mser": "Service militaire",
    "oth": "Autre",
    "marr": "Mariage",
    "enga": "Fiançailles",
    "div": "Divorce",
    "sep": "Séparation",
    "marc": "Contrat de mariage",
    "pacs": "PACS",
    "other": "Autre",
}

PERSONNES = TableSpec(
    "personnes",
    (
        _text("personne_id", "Identifiant de la personne."),
        _text("nom", "Nom de famille."),
        _text("prenom", "Prénom."),
        _int("occurrence", "Numéro d'homonyme GeneWeb (0 par défaut)."),
        _text("sexe", "M, F ou vide si inconnu."),
        _text("naissance_date", "Date de naissance, texte GeneWeb."),
        _int("naissance_annee", "Année de naissance, pour trier."),
        _text("naissance_lieu", "Lieu de naissance, tel qu'écrit."),
        _text("deces_date", "Date de décès, texte GeneWeb."),
        _int("deces_annee", "Année de décès, pour trier."),
        _text("deces_lieu", "Lieu de décès, tel qu'écrit."),
        _text("profession", "Profession de l'état civil."),
        _text("note", "Notes de la personne, texte complet."),
    ),
    primary_key="personne_id",
)

FAMILLES = TableSpec(
    "familles",
    (
        _text("famille_id", "Identifiant de la famille."),
        _text("mari_id", "Personne : mari ou premier conjoint."),
        _text("femme_id", "Personne : femme ou second conjoint."),
        _text("mariage_date", "Date du mariage, texte GeneWeb."),
        _int("mariage_annee", "Année du mariage, pour trier."),
        _text("mariage_lieu", "Lieu du mariage, tel qu'écrit."),
        _text("note", "Commentaires de la famille, texte complet."),
    ),
    primary_key="famille_id",
)

ENFANTS = TableSpec(
    "enfants",
    (
        _text("famille_id", "Famille des parents."),
        _text("personne_id", "Enfant."),
        _int("rang", "Rang de l'enfant dans la famille (1 pour le premier)."),
    ),
)

EVENEMENTS = TableSpec(
    "evenements",
    (
        _text("evenement_id", "Identifiant de l'événement."),
        _text("personne_id", "Personne, vide pour un événement familial."),
        _text("famille_id", "Famille, vide pour un événement personnel."),
        _text("type", "Code GeneWeb du type d'événement."),
        _text("type_libelle", "Libellé du type d'événement."),
        _text("libelle", "Étiquette libre de l'événement (tag), si présente."),
        _text("date", "Date, texte GeneWeb."),
        _int("annee", "Année, pour trier."),
        _text("lieu", "Lieu, tel qu'écrit."),
        _text("ville", "Ville tirée du lieu."),
        _text("complement", "Complément du lieu (établissement, adresse…)."),
        _text("note", "Notes de l'événement, texte complet."),
    ),
    primary_key="evenement_id",
)

TEMOINS = TableSpec(
    "temoins",
    (
        _text("evenement_id", "Événement, vide pour un témoin de la famille."),
        _text("famille_id", "Famille, vide pour un témoin d'événement."),
        _text("personne_id", "Témoin."),
        _text("role", "Rôle du témoin (Témoin, Parrain ou marraine…)."),
    ),
)


SOURCES = TableSpec(
    "sources",
    (
        _text("source_id", "Identifiant de la source."),
        _text("cible", "personne, famille ou evenement."),
        _text("cible_id", "Identifiant de la cible."),
        _text("objet", "Ce que la source documente (naissance, mariage…)."),
        _text("texte", "Texte de la source, tel qu'écrit."),
    ),
    primary_key="source_id",
)


def family_event_ref(family_id: str, index: int) -> str:
    """Identifiant d'un événement familial : ``fevt:<famille>:<index>``."""
    return f"fevt:{family_id}:{index}"


def _date(date: Optional[Date]) -> Optional[str]:
    if date is None:
        return None
    return date.raw_text or str(date)


def _year(date: Optional[Date]) -> Optional[int]:
    return date.sort_year() if date is not None else None


def _note(notes: Iterable[str]) -> Optional[str]:
    text = "\n".join(n for n in notes if n)
    return text or None


_SEX = {Gender.MALE: "M", Gender.FEMALE: "F"}


def _persons(genealogy: Genealogy) -> List[Row]:
    return [
        {
            "personne_id": pid,
            "nom": p.last_name,
            "prenom": p.first_name,
            "occurrence": p.occurrence_number,
            "sexe": _SEX.get(p.gender),
            "naissance_date": _date(p.birth_date),
            "naissance_annee": _year(p.birth_date),
            "naissance_lieu": p.birth_place,
            "deces_date": _date(p.death_date),
            "deces_annee": _year(p.death_date),
            "deces_lieu": p.death_place,
            "profession": p.occupation,
            "note": _note(p.notes),
        }
        for pid, p in genealogy.persons.items()
    ]


def _families(genealogy: Genealogy) -> List[Row]:
    return [
        {
            "famille_id": fid,
            "mari_id": f.husband_id,
            "femme_id": f.wife_id,
            "mariage_date": _date(f.marriage_date),
            "mariage_annee": _year(f.marriage_date),
            "mariage_lieu": f.marriage_place,
            "note": _note(f.comments),
        }
        for fid, f in genealogy.families.items()
    ]


def _children(genealogy: Genealogy) -> List[Row]:
    return [
        {"famille_id": fid, "personne_id": c.person_id, "rang": rank}
        for fid, f in genealogy.families.items()
        for rank, c in enumerate(f.children, start=1)
    ]


def _event_row(
    event_id: str, person_id: Optional[str], family_id: Optional[str], event: Event
) -> Row:
    code = str(event.event_type.value)
    parsed = parse_place(event.place)
    raw = event.event_type_raw
    return {
        "evenement_id": event_id,
        "personne_id": person_id,
        "famille_id": family_id,
        "type": code,
        "type_libelle": EVENT_TYPE_LABELS.get(code, code),
        "libelle": raw.replace("_", " ") if raw else None,
        "date": _date(event.date),
        "annee": _year(event.date),
        "lieu": event.place,
        "ville": place_city(event.place),
        "complement": parsed.complement if parsed else None,
        "note": _note(event.notes),
    }


def _all_events(
    genealogy: Genealogy,
) -> List[Tuple[str, Optional[str], Optional[str], Event]]:
    """(identifiant, personne, famille, événement), personnels puis familiaux."""
    result: List[Tuple[str, Optional[str], Optional[str], Event]] = []
    for pid, p in genealogy.persons.items():
        for i, e in enumerate(p.events):
            result.append((event_ref(pid, i), pid, None, e))
    for fid, f in genealogy.families.items():
        for i, fe in enumerate(f.events):
            result.append((family_event_ref(fid, i), None, fid, fe))
    return result


def _role(witness: Dict[str, object]) -> str:
    kind = witness.get("witness_kind")
    return WITNESS_KIND_ROLES[kind] if isinstance(kind, WitnessKind) else WITNESS_ROLE


def _witness_row(
    event_id: Optional[str], family_id: Optional[str], witness: Dict[str, object]
) -> Row:
    person = witness.get("person_id")
    return {
        "evenement_id": event_id,
        "famille_id": family_id,
        "personne_id": str(person) if person is not None else None,
        "role": _role(witness),
    }


def _witnesses(
    genealogy: Genealogy,
    events: List[Tuple[str, Optional[str], Optional[str], Event]],
) -> List[Row]:
    rows = [
        _witness_row(None, fid, w)
        for fid, f in genealogy.families.items()
        for w in f.witnesses
    ]
    rows.extend(
        _witness_row(eid, None, w) for eid, _, _, e in events for w in e.witnesses
    )
    return rows


_PERSON_SOURCES = (
    ("person_source", "generale"),
    ("birth_source", "naissance"),
    ("baptism_source", "bapteme"),
    ("death_source", "deces"),
    ("burial_source", "sepulture"),
)
_FAMILY_SOURCES = (
    ("family_source", "generale"),
    ("marriage_source", "mariage"),
    ("common_children_source", "enfants"),
)
# Événements dont la source double un champ de la personne ou de la famille.
_PERSON_EVENT_FIELDS = {
    "birt": "birth_source",
    "bapt": "baptism_source",
    "deat": "death_source",
    "buri": "burial_source",
}
_FAMILY_EVENT_FIELDS = {"marr": "marriage_source"}


def _source_row(
    cible: str, cible_id: str, objet: str, texte: Optional[str]
) -> Optional[Row]:
    if texte is None or not texte.strip():
        return None
    key = f"{cible}|{cible_id}|{objet}".encode()
    return {
        "source_id": "s-" + hashlib.sha1(key).hexdigest()[:12],
        "cible": cible,
        "cible_id": cible_id,
        "objet": objet,
        "texte": texte,
    }


def _duplicate_source(
    genealogy: Genealogy,
    person_id: Optional[str],
    family_id: Optional[str],
    event: Event,
) -> bool:
    code = str(event.event_type.value)
    owner: object = None
    field: Optional[str] = None
    if person_id is not None:
        owner, field = genealogy.persons[person_id], _PERSON_EVENT_FIELDS.get(code)
    elif family_id is not None:
        owner, field = genealogy.families[family_id], _FAMILY_EVENT_FIELDS.get(code)
    return field is not None and getattr(owner, field) == event.source


def _sources(
    genealogy: Genealogy,
    events: List[Tuple[str, Optional[str], Optional[str], Event]],
) -> List[Row]:
    candidates: List[Optional[Row]] = []
    for pid, p in genealogy.persons.items():
        candidates.extend(
            _source_row("personne", pid, objet, getattr(p, attr))
            for attr, objet in _PERSON_SOURCES
        )
    for fid, f in genealogy.families.items():
        candidates.extend(
            _source_row("famille", fid, objet, getattr(f, attr))
            for attr, objet in _FAMILY_SOURCES
        )
    for eid, event_pid, event_fid, e in events:
        if not _duplicate_source(genealogy, event_pid, event_fid, e):
            candidates.append(_source_row("evenement", eid, "evenement", e.source))
    return [row for row in candidates if row is not None]


def build_base_tables(genealogy: Genealogy) -> List[Table]:
    """Tables tirées de la base seule, dans l'ordre de l'export."""
    events = _all_events(genealogy)
    return [
        Table(PERSONNES, _persons(genealogy)),
        Table(FAMILLES, _families(genealogy)),
        Table(ENFANTS, _children(genealogy)),
        Table(EVENEMENTS, [_event_row(*item) for item in events]),
        Table(TEMOINS, _witnesses(genealogy, events)),
        Table(SOURCES, _sources(genealogy, events)),
    ]
