"""Index des candidats organisations : agrégats par organisation et reste à classer.

Calculé à partir de ``Genealogy.organizations`` / ``organization_links`` (voir
``core/doc/organizations_candidates_design.md`` § 3.5 et § 4). Les liens sont
rattachés à leur événement d'origine via ``OrganizationLink.source_event_id``
(tolérant : une référence absente ou périmée n'est jamais une erreur).
"""

import unicodedata
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from ...core.event import Event, EventType
from ...core.event_to_organization import _words, parse_event_ref
from ...core.genealogy import Genealogy
from ...core.organization import OrganizationLink
from ...core.person import Person

COLLECTIVE_MIN_WITNESSES = 3
CANDIDATE_MIN_PERSONS = 2
UNMATCHED_MIN_WORD_LEN = 4
UNMATCHED_GROUP_CAP = 50

# Mots des événements « Autre » qui ne désignent jamais une organisation.
DEFAULT_IGNORED_WORDS: Tuple[str, ...] = ("recensement", "domicile")
IGNORED_WORDS_MAX = 50
IGNORED_WORD_MAX_LEN = 40

OTHERS_WORD = "autres"
OCCUPATION_ATTR = "occu_attr"


@dataclass
class CandidateMember:
    """Un lien personne - organisation, avec son événement d'origine."""

    person_id: str
    person_name: str
    role: Optional[str]
    date: Optional[str]
    place: Optional[str]
    source_event_type: str
    event_type_raw: Optional[str]
    event_label: str
    witness_count: int
    year: Optional[int]


@dataclass
class Candidate:
    """Organisation candidate (au moins deux personnes liées)."""

    id: str
    name: str
    type: str
    place: Optional[str]
    named_from: Optional[str]
    sources: List[str]
    trigger: Optional[str]
    confidence: Optional[float]
    needs_review: bool
    to_determine: bool
    relation: bool
    collective: bool
    person_count: int
    event_count: int
    first_year: Optional[int]
    last_year: Optional[int]
    places: List[str]
    roles: List[str]
    members: List[CandidateMember] = field(default_factory=list)


@dataclass
class UnmatchedEvent:
    """Événement « Autre » sans candidat."""

    person_id: str
    person_name: str
    event_type_raw: str
    label: str
    date: Optional[str]
    place: Optional[str]


@dataclass
class UnmatchedGroup:
    """Événements non classés partageant un même mot."""

    word: str
    count: int
    events: List[UnmatchedEvent]


@dataclass
class CandidateIndex:
    """Candidats par identifiant et reste à classer."""

    candidates: Dict[str, Candidate]
    unmatched_total: int
    unmatched_groups: List[UnmatchedGroup]
    ignored_total: int = 0


def person_display_name(person: Person) -> str:
    """``NOM Prénom`` (``_`` en espace), suffixé de ``.n`` si homonyme numéroté."""
    name = f"{person.last_name} {person.first_name}".replace("_", " ")
    if person.occurrence_number > 0:
        name += f".{person.occurrence_number}"
    return name


def _fold(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text)
    return "".join(c for c in stripped if not unicodedata.combining(c)).casefold()


def normalize_ignored_words(words: Iterable[str]) -> Tuple[str, ...]:
    """Mots repliés, dédoublonnés dans l'ordre ; les vides sont retirés.

    Lève ``ValueError`` pour un mot trop long, contenant autre chose que des
    lettres, ou au-delà de ``IGNORED_WORDS_MAX`` mots.
    """
    result: List[str] = []
    for raw in words:
        word = _fold(raw.strip())
        if not word:
            continue
        if len(word) > IGNORED_WORD_MAX_LEN or not word.isalpha():
            raise ValueError(f"mot invalide : {raw!r}")
        if word not in result:
            result.append(word)
    if len(result) > IGNORED_WORDS_MAX:
        raise ValueError(f"au plus {IGNORED_WORDS_MAX} mots")
    return tuple(result)


def _is_ignored(event: Optional[Event], ignored: Set[str]) -> bool:
    """Événement « Autre » dont le nom contient un mot ignoré (mot entier, replié)."""
    if not ignored or event is None or event.event_type is not EventType.OTHER:
        return False
    return not ignored.isdisjoint(_words(event.event_type_raw or ""))


def _resolve_event(genealogy: Genealogy, ref: Optional[str]) -> Optional[Event]:
    parsed = parse_event_ref(ref)
    if parsed is None:
        return None
    person = genealogy.persons.get(parsed[0])
    if person is None or not 0 <= parsed[1] < len(person.events):
        return None
    return person.events[parsed[1]]


def _build_member(genealogy: Genealogy, link: OrganizationLink) -> CandidateMember:
    event = _resolve_event(genealogy, link.source_event_id)
    person = genealogy.persons.get(link.person_id)
    raw = link.source_event_type
    if raw == OCCUPATION_ATTR:
        api_type = OCCUPATION_ATTR
    elif event is not None:
        api_type = event.event_type.value
    else:
        api_type = "oth"
    if api_type in ("occu", OCCUPATION_ATTR):
        label = link.role or ""
    elif api_type == "oth":
        label = raw or ""
    else:
        label = ""
    date = event.date if event is not None and event.date else link.start_date
    return CandidateMember(
        person_id=link.person_id,
        person_name=person_display_name(person) if person else link.person_id,
        role=link.role,
        date=date.display_text if date else None,
        place=event.place if event is not None else None,
        source_event_type=api_type,
        event_type_raw=raw,
        event_label=label,
        witness_count=len(event.witnesses) if event is not None else 0,
        year=date.sort_year() if date else None,
    )


def _build_candidates(
    genealogy: Genealogy, ignored: Set[str]
) -> Tuple[Dict[str, Candidate], Set[Tuple[str, int]]]:
    members: Dict[str, List[CandidateMember]] = {}
    refs: Dict[str, Set[Tuple[str, int]]] = {}
    for link in genealogy.organization_links:
        if link.organization_id not in genealogy.organizations:
            continue
        if _is_ignored(_resolve_event(genealogy, link.source_event_id), ignored):
            continue
        members.setdefault(link.organization_id, []).append(
            _build_member(genealogy, link)
        )
        parsed = parse_event_ref(link.source_event_id)
        if parsed is not None:
            refs.setdefault(link.organization_id, set()).add(parsed)

    candidates: Dict[str, Candidate] = {}
    matched: Set[Tuple[str, int]] = set()
    for org_id, org_members in members.items():
        persons = {m.person_id for m in org_members}
        if len(persons) < CANDIDATE_MIN_PERSONS:
            continue
        org = genealogy.organizations[org_id]
        years = [m.year for m in org_members if m.year is not None]
        candidates[org_id] = Candidate(
            id=org.id,
            name=org.name,
            type=org.type.value,
            place=org.place,
            named_from=org.metadata.get("named_from"),
            sources=sorted({m.source_event_type for m in org_members}),
            trigger=org.metadata.get("trigger"),
            confidence=org.confidence,
            needs_review=org.needs_review,
            to_determine=bool(org.metadata.get("to_determine", False)),
            relation="relation" in org.notes,
            collective=any(
                m.witness_count >= COLLECTIVE_MIN_WITNESSES for m in org_members
            ),
            person_count=len(persons),
            event_count=len(org_members),
            first_year=min(years) if years else None,
            last_year=max(years) if years else None,
            places=sorted({m.place for m in org_members if m.place}),
            roles=sorted({m.role for m in org_members if m.role}),
            members=org_members,
        )
        matched |= refs.get(org_id, set())
    return candidates, matched


def _build_unmatched(
    genealogy: Genealogy, matched: Set[Tuple[str, int]], ignored: Set[str]
) -> Tuple[int, List[UnmatchedGroup], int]:
    entries: List[Tuple[UnmatchedEvent, Set[str]]] = []
    ignored_total = 0
    for person_id, person in genealogy.persons.items():
        for index, event in enumerate(person.events):
            if event.event_type is not EventType.OTHER:
                continue
            if _is_ignored(event, ignored):
                ignored_total += 1
                continue
            if (person_id, index) in matched:
                continue
            tag = (event.event_type_raw or "").strip()
            entries.append(
                (
                    UnmatchedEvent(
                        person_id=person_id,
                        person_name=person_display_name(person),
                        event_type_raw=tag,
                        label=tag.replace("_", " "),
                        date=event.date.display_text if event.date else None,
                        place=event.place,
                    ),
                    {
                        w
                        for w in _words(tag)
                        if len(w) >= UNMATCHED_MIN_WORD_LEN and w.isalpha()
                    },
                )
            )

    counts: Dict[str, int] = {}
    for _, words in entries:
        for word in words:
            counts[word] = counts.get(word, 0) + 1
    kept = {w for w, n in counts.items() if n >= 2}

    grouped: Dict[str, List[UnmatchedEvent]] = {w: [] for w in kept}
    others: List[UnmatchedEvent] = []
    for entry, words in entries:
        retained = words & kept
        if not retained:
            others.append(entry)
        for word in retained:
            grouped[word].append(entry)

    groups = [
        UnmatchedGroup(word, len(evts), evts[:UNMATCHED_GROUP_CAP])
        for word, evts in sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]
    if others:
        groups.append(
            UnmatchedGroup(OTHERS_WORD, len(others), others[:UNMATCHED_GROUP_CAP])
        )
    return len(entries), groups, ignored_total


def build_candidate_index(
    genealogy: Genealogy, ignored_words: Sequence[str] = DEFAULT_IGNORED_WORDS
) -> CandidateIndex:
    """Calcule l'index ; infère les organisations si la base n'en a aucune.

    Les événements « Autre » dont le nom contient un mot de ``ignored_words``
    (recensement, domicile…) ne nourrissent ni les candidats ni le reste à classer.
    """
    if not genealogy.organizations:
        genealogy.infer_organizations()
    ignored = set(normalize_ignored_words(ignored_words))
    candidates, matched = _build_candidates(genealogy, ignored)
    total, groups, ignored_total = _build_unmatched(genealogy, matched, ignored)
    return CandidateIndex(candidates, total, groups, ignored_total)


def sort_candidates(candidates: Iterable[Candidate], sort: str) -> List[Candidate]:
    """Tri par ``persons`` (effectif décroissant), ``period`` ou ``name``."""
    items = list(candidates)
    if sort == "period":
        return sorted(
            items,
            key=lambda c: (c.first_year is None, c.first_year or 0, c.name.casefold()),
        )
    if sort == "name":
        return sorted(items, key=lambda c: c.name.casefold())
    return sorted(items, key=lambda c: (-c.person_count, c.name.casefold()))


def filter_candidates(
    candidates: Iterable[Candidate],
    type_: Optional[str] = None,
    named_from: Optional[str] = None,
    q: Optional[str] = None,
) -> List[Candidate]:
    """Filtre par type, origine du nom et sous-chaîne repliée du nom."""
    needle = _fold(q) if q else None
    return [
        c
        for c in candidates
        if (not type_ or c.type == type_)
        and (not named_from or c.named_from == named_from)
        and (needle is None or needle in _fold(c.name))
    ]
