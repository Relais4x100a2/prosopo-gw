"""Table ``pistes`` : passages de notes qui évoquent une organisation.

Voir ``core/doc/exports_design.md`` § 6. Sont lues les notes des personnes, de
leurs événements, des familles et des événements familiaux ; une note de famille
est rattachée au mari, à défaut à la femme. Le contexte (nom, date, lieu) n'est
pas recopié : il se joint par les identifiants des autres tables.
"""

import hashlib
from typing import AbstractSet, Iterable, List, Optional, Tuple

from ..core.event import Event, EventType
from ..core.event_to_organization import EventToOrganizationMapper, event_ref
from ..core.family import Family
from ..core.genealogy import Genealogy
from ..core.note_leads import find_note_leads
from .tables import Column, Row, Table, TableSpec, _text, family_event_ref

ORGANISATION = "organisation"

PISTES = TableSpec(
    "pistes",
    (
        _text("piste_id", "Identifiant de la piste."),
        _text(
            "personne_id",
            "Personne concernée (mari, à défaut femme, pour une famille).",
        ),
        _text(
            "evenement_id",
            "Événement dont la note est tirée ; vide pour une note de personne ou de famille.",
        ),
        _text("famille_id", "Famille concernée ; vide hors famille."),
        _text("nature", "Nature de la piste : organisation (source est réservé)."),
        _text(
            "origine", "Note lue : personne, evenement, famille ou evenement_familial."
        ),
        _text(
            "mots",
            "Mots déclencheurs, sans accents ni majuscules, séparés par une espace.",
        ),
        _text(
            "type_devine",
            "Type d'organisation deviné du premier déclencheur (company, school…).",
        ),
        Column(
            "forte",
            "bool",
            "Vrai si un nom propre accompagne le déclencheur (« Société Durand », « Durand SA »).",
        ),
        _text(
            "extrait",
            "Passage de la note autour des déclencheurs (600 caractères au plus).",
        ),
    ),
    primary_key="piste_id",
)


def _lead_id(origin: str, target: str, rank: int, start: int) -> str:
    digest = hashlib.sha1(f"{origin}|{target}|{rank}|{start}".encode())
    return "p-" + digest.hexdigest()[:12]


def _family_owner(genealogy: Genealogy, family: Family) -> Optional[str]:
    for spouse in (family.husband_id, family.wife_id):
        if spouse and spouse in genealogy.persons:
            return spouse
    return None


def _occupation_note_named_org(
    mapper: EventToOrganizationMapper, event: Event, matched: bool
) -> bool:
    """La première note d'une Profession rattachée a nommé l'organisation."""
    if not matched or event.event_type is not EventType.OCCUPATION or not event.notes:
        return False
    city = event.place_parts.city if event.place_parts else None
    proposal = mapper.propose_from_occupation(event.notes[0], city)
    return proposal is not None and proposal.trigger is not None


def build_leads_table(
    genealogy: Genealogy,
    matched: AbstractSet[Tuple[str, int]],
    ignored_words: Iterable[str],
) -> Table:
    """Une ligne par piste, personnes puis familles, dans l'ordre de la base."""
    ignored = list(ignored_words)
    mapper = EventToOrganizationMapper()
    rows: List[Row] = []

    def add(
        origin: str,
        target: str,
        notes: Iterable[str],
        person_id: Optional[str],
        event_id: Optional[str] = None,
        family_id: Optional[str] = None,
        skip_first: bool = False,
    ) -> None:
        for rank, note in enumerate(notes):
            if not note or (rank == 0 and skip_first):
                continue
            for lead in find_note_leads(note, ignored):
                rows.append(
                    {
                        "piste_id": _lead_id(origin, target, rank, lead.start),
                        "personne_id": person_id,
                        "evenement_id": event_id,
                        "famille_id": family_id,
                        "nature": ORGANISATION,
                        "origine": origin,
                        "mots": " ".join(lead.words),
                        "type_devine": lead.guessed_type,
                        "forte": lead.strong,
                        "extrait": lead.excerpt,
                    }
                )

    for pid, person in genealogy.persons.items():
        add("personne", pid, person.notes, pid)
        for index, event in enumerate(person.events):
            ref = event_ref(pid, index)
            skip = _occupation_note_named_org(mapper, event, (pid, index) in matched)
            add("evenement", ref, event.notes, pid, event_id=ref, skip_first=skip)
    for fid, family in genealogy.families.items():
        owner = _family_owner(genealogy, family)
        add("famille", fid, family.comments, owner, family_id=fid)
        for index, fevent in enumerate(family.events):
            ref = family_event_ref(fid, index)
            add(
                "evenement_familial",
                ref,
                fevent.notes,
                owner,
                event_id=ref,
                family_id=fid,
            )
    return Table(PISTES, rows)
