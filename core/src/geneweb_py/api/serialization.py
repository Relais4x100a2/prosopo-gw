"""
Sérialisation des modèles domaine (core) vers les charges utiles API.

Centralise conversion des dates GeneWeb, des listes (enfants, événements,
familles liées) pour des réponses JSON cohérentes sans champs fantômes vides.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Union

from ..core.date import Date
from ..core.event import Event, FamilyEvent, PersonalEvent
from ..core.family import Child, ChildSex
from ..core.genealogy import Genealogy
from ..core.person import Person, Title
from .models.event import EventSchema
from .models.family import ChildSchema
from .models.person import TitleSchema


def date_to_api_string(date_val: Optional[Date]) -> Optional[str]:
    """Convertit une ``Date`` core en chaîne GeneWeb pour l'API.

    Args:
        date_val: Date domaine ou ``None``.

    Returns:
        ``display_text`` si une date est présente, sinon ``None`` (pas de
        chaîne vide artificielle).
    """
    if date_val is None:
        return None
    return date_val.display_text


def parse_api_date_string(raw: Optional[str]) -> Optional[Date]:
    """Parse une date fournie par le corps API (GeneWeb ou vide).

    Args:
        raw: Chaîne reçue du client ou ``None``.

    Returns:
        Instance ``Date`` ou ``None`` si aucune date à enregistrer.
    """
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    return Date.parse_with_fallback(text)


def title_to_schema(title: Title) -> TitleSchema:
    """Convertit un titre domaine en schéma API."""
    return TitleSchema(
        name=title.name,
        title_type=title.title_type,
        place=title.place,
        start_date=date_to_api_string(title.start_date),
        end_date=date_to_api_string(title.end_date),
        number=title.number,
        is_main=title.is_main,
    )


def titles_from_create_schemas(
    title_data_list: List[Any],
) -> List[Title]:
    """Construit des ``Title`` à partir des schémas de création / mise à jour."""
    titles: List[Title] = []
    for title_data in title_data_list:
        start_d: Optional[Date] = None
        end_d: Optional[Date] = None
        if (
            getattr(title_data, "start_date", None) is not None
            and str(title_data.start_date).strip()
        ):
            start_d = parse_api_date_string(title_data.start_date)
        if (
            getattr(title_data, "end_date", None) is not None
            and str(title_data.end_date).strip()
        ):
            end_d = parse_api_date_string(title_data.end_date)
        titles.append(
            Title(
                name=title_data.name,
                title_type=title_data.title_type,
                place=title_data.place,
                start_date=start_d,
                end_date=end_d,
                number=title_data.number,
                is_main=title_data.is_main,
            )
        )
    return titles


def person_source_fields(person: Person) -> List[str]:
    """Agrège les champs source renseignés sur une personne."""
    out: List[str] = []
    for raw in (
        person.birth_source,
        person.death_source,
        person.baptism_source,
        person.burial_source,
        person.person_source,
    ):
        if raw and str(raw).strip():
            out.append(str(raw).strip())
    return out


def child_to_schema(
    child: Union[Child, str],
) -> ChildSchema:
    """Convertit un enfant domaine (ou identifiant brut) en schéma API."""
    if isinstance(child, str):
        return ChildSchema(person_id=child, sex=ChildSex.UNKNOWN, last_name=None)
    return ChildSchema(
        person_id=child.person_id,
        sex=child.sex,
        last_name=child.last_name,
    )


def stable_event_id(
    event: Event,
    *,
    scope: str,
    scope_key: str,
    index: int,
) -> str:
    """Calcule un identifiant stable pour un événement sans ``unique_id`` core.

    Args:
        event: Événement domaine.
        scope: ``person`` ou ``family``.
        scope_key: Identifiant de la personne ou de la famille.
        index: Indice dans la liste d'événements du parent.

    Returns:
        Identifiant déterministe du type ``evt_{scope}_{key}_{index}_{suffix}``.
    """
    suffix = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"geneweb-py|{scope}|{scope_key}|{index}|{id(event)}",
    ).hex[:12]
    return f"evt_{scope}_{scope_key}_{index}_{suffix}"


def event_witnesses_to_api_strings(witnesses: List[Any]) -> List[str]:
    """Normalise les témoins (dict ou chaîne) en liste de chaînes."""
    out: List[str] = []
    for w in witnesses:
        if isinstance(w, str):
            if w.strip():
                out.append(w.strip())
        elif isinstance(w, dict):
            pid = w.get("person_id")
            if pid:
                out.append(str(pid))
    return out


def event_sources_list(event: Event) -> List[str]:
    """Liste des sources pour l'API à partir d'un événement domaine."""
    if event.source and str(event.source).strip():
        return [str(event.source).strip()]
    return []


# Codes « Autre » (personnel et familial) : le tag libre porte le vrai nom.
_CUSTOM_EVENT_CODES = frozenset({"oth", "other"})


def event_to_schema(
    event: Event,
    *,
    event_id: str,
    person_id: Optional[str],
    family_id: Optional[str],
    genealogy: Optional[Genealogy] = None,
) -> EventSchema:
    """Construit un ``EventSchema`` à partir d'un événement domaine."""
    if isinstance(event, PersonalEvent):
        evt_type: Any = event.event_type
    elif isinstance(event, FamilyEvent) and event.family_event_type is not None:
        evt_type = event.family_event_type
    else:
        evt_type = event.event_type

    note_joined: Optional[str] = None
    if event.notes:
        joined = "\n".join(str(n) for n in event.notes if n is not None)
        note_joined = joined if joined else None

    # Name resolution (requires genealogy)
    resolved_person_name: Optional[str] = None
    resolved_family_label: Optional[str] = None
    resolved_witness_names: List[str] = []
    date_sort_year: Optional[int] = None

    if genealogy is not None:
        if person_id is not None:
            p = genealogy.persons.get(person_id)
            if p is not None:
                resolved_person_name = f"{p.first_name} {p.last_name}".replace(
                    "_", " "
                ).strip()

        if family_id is not None:
            fam = genealogy.families.get(family_id)
            if fam is not None:
                parts: List[str] = []
                if fam.husband_id:
                    h = genealogy.persons.get(fam.husband_id)
                    if h:
                        parts.append(
                            f"{h.first_name} {h.last_name}".replace("_", " ").strip()
                        )
                if fam.wife_id:
                    w = genealogy.persons.get(fam.wife_id)
                    if w:
                        parts.append(
                            f"{w.first_name} {w.last_name}".replace("_", " ").strip()
                        )
                if parts:
                    resolved_family_label = " × ".join(parts)

        raw_witness_ids = event_witnesses_to_api_strings(event.witnesses)
        for wid in raw_witness_ids:
            wp = genealogy.persons.get(wid)
            if wp is not None:
                resolved_witness_names.append(
                    f"{wp.first_name} {wp.last_name}".replace("_", " ").strip()
                )
            else:
                resolved_witness_names.append(wid)

    if event.date is not None:
        date_sort_year = event.date.sort_year()

    custom_type: Optional[str] = None
    if str(getattr(evt_type, "value", evt_type)) in _CUSTOM_EVENT_CODES:
        custom_type = (event.event_type_raw or "").strip() or None

    return EventSchema(
        id=event_id,
        event_type=evt_type,
        date=date_to_api_string(event.date),
        place=event.place,
        reason=event.reason,
        note=note_joined,
        witnesses=event_witnesses_to_api_strings(event.witnesses),
        sources=event_sources_list(event),
        person_id=person_id,
        family_id=family_id,
        person_name=resolved_person_name,
        family_label=resolved_family_label,
        witness_names=resolved_witness_names,
        date_sort_year=date_sort_year,
        custom_type=custom_type,
    )


def related_family_ids_for_person(person: Person) -> List[str]:
    """Retourne les IDs des familles où la personne est conjoint(e)."""
    return list(person.families_as_spouse)


def century_key_from_year(year: Optional[int]) -> str:
    """Retourne la clé de siècle du type ``19`` pour 1900–1999."""
    if year is None:
        return "unknown"
    if year <= 0:
        return "unknown"
    century = (year - 1) // 100 + 1
    return str(century)


def count_by_birth_century(genealogy: Genealogy) -> Dict[str, int]:
    """Répartition des personnes par siècle de naissance (année principale)."""
    counts: Dict[str, int] = {}
    for person in genealogy.persons.values():
        y = person.birth_date.sort_year() if person.birth_date else None
        key = century_key_from_year(y)
        counts[key] = counts.get(key, 0) + 1
    return counts


def count_marriage_century(genealogy: Genealogy) -> Dict[str, int]:
    """Répartition des familles par siècle de la date de mariage."""
    counts: Dict[str, int] = {}
    for family in genealogy.families.values():
        y = family.marriage_date.sort_year() if family.marriage_date else None
        key = century_key_from_year(y)
        counts[key] = counts.get(key, 0) + 1
    return counts


def count_event_century(genealogy: Genealogy) -> Dict[str, int]:
    """Répartition de tous les événements par siècle (date principal)."""
    counts: Dict[str, int] = {}

    def bump(ed: Optional[Date]) -> None:
        y = ed.sort_year() if ed else None
        key = century_key_from_year(y)
        counts[key] = counts.get(key, 0) + 1

    for person in genealogy.persons.values():
        for pev in person.events:
            bump(pev.date)
    for family in genealogy.families.values():
        for fev in family.events:
            bump(fev.date)
    return counts


def _date_has_usable_parts(d: Date) -> bool:
    """Indique si la date porte au moins une information exploitable."""
    if d.text_date:
        return True
    if d.is_unknown:
        return False
    return d.year is not None or d.month is not None or d.day is not None


def family_events_breakdown(genealogy: Genealogy) -> Dict[str, int]:
    """Nombre de familles avec date de mariage / divorce (présence)."""
    with_marriage = 0
    with_divorce = 0
    for f in genealogy.families.values():
        md = f.marriage_date
        if md is not None and _date_has_usable_parts(md):
            with_marriage += 1
        dd = f.divorce_date
        if dd is not None and _date_has_usable_parts(dd):
            with_divorce += 1
    return {
        "with_marriage_date": with_marriage,
        "with_divorce_date": with_divorce,
    }
