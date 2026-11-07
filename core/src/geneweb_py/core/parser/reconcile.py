"""Réconciliation lignes / blocs d'événements, à la manière de ``gwc``.

Règle de GeneWeb (``bin/gwc/db1link.ml``, ``update_family_with_fevents``,
``update_fevents_with_family``, ``update_person_with_pevents``,
``update_pevents_with_person``) :

- si un bloc d'événements existe, il fait foi : les champs « principaux » de la
  famille ou de la personne sont recopiés depuis les événements ;
- sinon, les événements sont fabriqués depuis la ligne (``fam`` ou ``ind``).

La passe s'applique une fois, à la fin du parse. Les événements fabriqués
portent ``metadata["synthesized"] = True`` ; l'entité qui en reçoit porte
``metadata["events_synthesized"] = True``. Écart assumé : ``gwc`` trie d'abord
les événements d'un bloc par date puis par type ; on garde l'ordre du fichier
(``gwu``, qui produit la plupart des exports, écrit déjà les blocs triés).
"""

from dataclasses import replace
from typing import Any

from ..date import Date, DatePrefix
from ..event import EventType, FamilyEvent, FamilyEventType, PersonalEvent
from ..family import Family, FamilyQualifier, MarriageStatus
from ..genealogy import Genealogy
from ..person import Person

_FET = FamilyEventType

# Événements qui jouent le rôle de « mariage » pour les champs de la famille
_NO_MENTION_LIKE = (
    _FET.NO_MENTION,
    _FET.MARRIAGE_BANN,
    _FET.MARRIAGE_LICENSE,
    _FET.ANNULMENT,
    _FET.PACS,
)

# Qualificatif de ligne ↔ type de l'événement de mariage fabriqué
_QUALIFIER_EVENT = {
    FamilyQualifier.NO_SEX_CHECK: _FET.NO_MARRIAGE,
    FamilyQualifier.NO_SEX_CHECK_MARRIAGE: _FET.MARRIAGE,
    FamilyQualifier.NO_MENTION: _FET.NO_MENTION,
    FamilyQualifier.BANNS: _FET.MARRIAGE_BANN,
    FamilyQualifier.CONTRACT: _FET.MARRIAGE_CONTRACT,
    FamilyQualifier.LICENSE: _FET.MARRIAGE_LICENSE,
    FamilyQualifier.PACS: _FET.PACS,
    FamilyQualifier.RESIDENCE: _FET.RESIDENCE,
}


def _copy_witnesses(witnesses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(w) for w in witnesses]


def _about(date: Date | None) -> Date | None:
    """Précision « vers » d'un contrat de mariage recopié comme mariage."""
    if date is None or date.is_unknown or date.year is None:
        return date
    raw = f"~{date.raw_text}" if date.raw_text else None
    return replace(date, prefix=DatePrefix.ABOUT, raw_text=raw)


def _set_marriage_fields(family: Family, event: FamilyEvent) -> None:
    family.marriage_date = event.date
    family.marriage_place = event.place or None
    family.marriage_source = event.source or None
    family.witnesses = _copy_witnesses(event.witnesses)


def _set_kind(
    family: Family,
    status: MarriageStatus,
    qualifier: FamilyQualifier | None,
    nsck: FamilyQualifier | None,
) -> None:
    """Pose le type d'union ; ``nsck`` garde le « sans contrôle des sexes » de la ligne."""
    family.marriage_status = status
    family.family_qualifiers = (
        [nsck] if nsck is not None else ([qualifier] if qualifier is not None else [])
    )


def _family_from_events(family: Family) -> None:
    """Le bloc ``fevt`` fait foi : recopie du dernier mariage et du dernier divorce."""
    divorce = _marriage_pass(family)
    if divorce is None:
        return
    if family.marriage_status is MarriageStatus.MARRIED:
        family.marriage_status = (
            MarriageStatus.DIVORCED
            if divorce.family_event_type is _FET.DIVORCE
            else MarriageStatus.SEPARATED
        )
    if divorce.family_event_type is _FET.DIVORCE:
        family.divorce_date = divorce.date
    else:
        family.is_separated = True


def _marriage_pass(family: Family) -> FamilyEvent | None:
    """Recopie le mariage ; renvoie le divorce ou la séparation retenus, s'il y en a."""
    nsck = next(
        (
            q
            for q in family.family_qualifiers
            if q
            in (FamilyQualifier.NO_SEX_CHECK, FamilyQualifier.NO_SEX_CHECK_MARRIAGE)
        ),
        None,
    )
    nsck_std = nsck is not None
    found_marriage = False
    divorce: FamilyEvent | None = None
    for event in reversed(family.events):
        fet = event.family_event_type
        if fet is _FET.MARRIAGE:
            # Le mariage l'emporte et arrête la lecture (comme gwc)
            _set_marriage_fields(family, event)
            _set_kind(
                family,
                MarriageStatus.MARRIED,
                None,
                FamilyQualifier.NO_SEX_CHECK_MARRIAGE if nsck_std else None,
            )
            return divorce
        if fet in (_FET.DIVORCE, _FET.SEPARATION):
            if divorce is None:
                divorce = event
            continue
        if found_marriage:
            continue
        if fet is _FET.ENGAGEMENT:
            _set_marriage_fields(family, event)
            _set_kind(
                family,
                MarriageStatus.NOT_MARRIED if nsck_std else MarriageStatus.ENGAGED,
                None,
                nsck,
            )
        elif fet is _FET.MARRIAGE_CONTRACT:
            _set_marriage_fields(family, event)
            family.marriage_date = _about(event.date)
            family.marriage_place = None
            _set_kind(
                family,
                MarriageStatus.MARRIED,
                None,
                FamilyQualifier.NO_SEX_CHECK_MARRIAGE if nsck_std else None,
            )
        elif fet in _NO_MENTION_LIKE:
            _set_marriage_fields(family, event)
            _set_kind(
                family,
                MarriageStatus.MARRIED,
                FamilyQualifier.NO_MENTION,
                nsck,
            )
        elif fet is _FET.NO_MARRIAGE:
            _set_marriage_fields(family, event)
            _set_kind(
                family,
                MarriageStatus.NOT_MARRIED,
                None,
                nsck,
            )
        else:
            continue
        found_marriage = True
    return divorce


def _marriage_event_type(family: Family) -> FamilyEventType:
    if family.marriage_status is MarriageStatus.NOT_MARRIED:
        return _FET.NO_MARRIAGE
    if family.marriage_status is MarriageStatus.ENGAGED:
        return _FET.ENGAGEMENT
    for qualifier in family.family_qualifiers:
        if qualifier in _QUALIFIER_EVENT:
            return _QUALIFIER_EVENT[qualifier]
    return _FET.MARRIAGE


def _new_family_event(
    family: Family, fet: FamilyEventType, date: Date | None = None
) -> FamilyEvent:
    try:
        generic = EventType(fet.value)
    except ValueError:
        generic = EventType.OTHER
    event = FamilyEvent(
        event_type=generic,
        family_event_type=fet,
        date=date,
        family_id=family.family_id,
        metadata={"synthesized": True},
    )
    return event


def _events_from_family(family: Family) -> None:
    """Pas de bloc ``fevt`` : événements fabriqués depuis la ligne ``fam``."""
    marriage = _new_family_event(
        family, _marriage_event_type(family), family.marriage_date
    )
    marriage.place = family.marriage_place or None
    marriage.source = family.marriage_source or None
    marriage.witnesses = _copy_witnesses(family.witnesses)
    family.events.append(marriage)
    if (
        family.divorce_date is not None
        or family.marriage_status is MarriageStatus.DIVORCED
    ):
        family.events.append(
            _new_family_event(family, _FET.DIVORCE, family.divorce_date)
        )
    elif family.is_separated or family.marriage_status is MarriageStatus.SEPARATED:
        family.events.append(_new_family_event(family, _FET.SEPARATION))
    family.metadata["events_synthesized"] = True


def reconcile_family(family: Family) -> None:
    """Applique la règle de ``gwc`` à une famille."""
    if family.events:
        _family_from_events(family)
    else:
        _events_from_family(family)


# --------------------------------------------------------------------------- personnes

_PERSON_TYPES = (
    EventType.BIRTH,
    EventType.BAPTISM,
    EventType.DEATH,
    EventType.BURIAL,
    EventType.CREMATION,
)


def _real_date(date: Date | None) -> bool:
    return date is not None and not date.is_unknown


def _person_from_events(person: Person) -> None:
    """Le bloc ``pevt`` fait foi : le premier événement de chaque type est recopié."""
    seen = set()
    for event in person.events:
        kind = event.event_type
        if kind not in _PERSON_TYPES:
            continue
        slot = EventType.BURIAL if kind is EventType.CREMATION else kind
        if slot in seen:
            continue
        seen.add(slot)
        place = event.place or None
        source = event.source or None
        if kind is EventType.BIRTH:
            # Écart toléré : une date absente du bloc n'efface pas une date connue
            if _real_date(event.date) or person.birth_date is None:
                person.birth_date = event.date
            person.birth_place, person.birth_source = place, source
        elif kind is EventType.BAPTISM:
            if _real_date(event.date) or person.baptism_date is None:
                person.baptism_date = event.date
            person.baptism_place, person.baptism_source = place, source
        elif kind is EventType.DEATH:
            # Sans date, l'état « mort, date inconnue » existant est conservé
            if _real_date(event.date):
                person.death_date = event.date
            person.death_place, person.death_source = place, source
        else:
            person.burial_place, person.burial_source = place, source
            person.burial_type = "crem" if kind is EventType.CREMATION else "buri"


def _new_person_event(
    person: Person,
    kind: EventType,
    date: Date | None,
    place: str | None,
    source: str | None,
) -> PersonalEvent:
    return PersonalEvent(
        event_type=kind,
        # Sans date réelle : date inconnue, comme un ``#birt`` nu d'un bloc pevt
        date=date if _real_date(date) else Date(is_unknown=True),
        place=place,
        source=source,
        person_id=person.unique_id,
        metadata={"synthesized": True},
    )


def _events_from_person(person: Person) -> None:
    """Pas de bloc ``pevt`` : événements fabriqués depuis les champs de la personne."""
    events: list[PersonalEvent] = []
    if _real_date(person.birth_date) or person.birth_place or person.birth_source:
        events.append(
            _new_person_event(
                person,
                EventType.BIRTH,
                person.birth_date,
                person.birth_place,
                person.birth_source,
            )
        )
    if _real_date(person.baptism_date) or person.baptism_place or person.baptism_source:
        events.append(
            _new_person_event(
                person,
                EventType.BAPTISM,
                person.baptism_date,
                person.baptism_place,
                person.baptism_source,
            )
        )
    if (
        person.death_date is not None
        or person.is_deceased
        or person.is_obviously_dead
        or person.is_young_death
        or person.death_place
        or person.death_source
    ):
        events.append(
            _new_person_event(
                person,
                EventType.DEATH,
                person.death_date,
                person.death_place,
                person.death_source,
            )
        )
    if person.burial_place or person.burial_source:
        kind = EventType.CREMATION if person.burial_type == "crem" else EventType.BURIAL
        events.append(
            _new_person_event(
                person, kind, None, person.burial_place, person.burial_source
            )
        )
    if events:
        person.events.extend(events)
        person.metadata["events_synthesized"] = True


def reconcile_person(person: Person) -> None:
    """Applique la règle de ``gwc`` à une personne."""
    if person.events:
        _person_from_events(person)
    else:
        _events_from_person(person)


def reconcile_genealogy(genealogy: Genealogy) -> None:
    """Passe de fin de parse : familles puis personnes."""
    for family in genealogy.families.values():
        reconcile_family(family)
    for person in genealogy.persons.values():
        reconcile_person(person)
