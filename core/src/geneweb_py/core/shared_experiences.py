"""Expériences proches : personnes ayant vécu un événement semblable.

Deux événements « Autre » personnels d'un même thème sont liés s'ils concernent deux
personnes distinctes, à des périodes proches (fenêtre du thème), et partagent soit la
même ville, soit un mot rare de leurs notes. Les composantes connexes réunissant au moins
deux personnes forment les expériences proches.

Module pur, sans persistance ni dépendance à l'API (voir
``core/doc/shared_experiences_design.md`` § 4). Le résultat ne dépend que de l'ordre
``(début, fin, personne, rang de l'événement)``, jamais de l'ordre de lecture du fichier.
"""

import hashlib
import heapq
import re
from collections import Counter
from dataclasses import dataclass
from typing import (
    AbstractSet,
    Dict,
    FrozenSet,
    List,
    Optional,
    Set,
    Tuple,
)

from .date import Date, DatePrefix
from .event import EventType
from .event_to_organization import RELATION_WORDS, _fold, _words, is_civil_status
from .genealogy import Genealogy
from .place import place_city

RARE_WORD_MAX_NOTES = 5
MIN_NOTE_WORD_LEN = 4
MAX_REASON_WORDS = 3

# Mots outils (forme repliée) ; seuls ceux d'au moins MIN_NOTE_WORD_LEN lettres comptent.
STOPWORDS: FrozenSet[str] = frozenset(
    {
        # articles, déterminants, pronoms
        "cette",
        "ceux",
        "celle",
        "celles",
        "celui",
        "elle",
        "elles",
        "nous",
        "vous",
        "leur",
        "leurs",
        "notre",
        "votre",
        "dont",
        "quel",
        "quelle",
        "quels",
        "quelles",
        "lequel",
        "laquelle",
        "lesquels",
        "lesquelles",
        "tout",
        "toute",
        "tous",
        "toutes",
        "autre",
        "autres",
        "meme",
        "memes",
        "chaque",
        "plusieurs",
        "quelque",
        "quelques",
        # prépositions, conjonctions, adverbes
        "dans",
        "avec",
        "pour",
        "sans",
        "sous",
        "chez",
        "vers",
        "entre",
        "depuis",
        "pendant",
        "avant",
        "apres",
        "contre",
        "parmi",
        "selon",
        "durant",
        "lors",
        "jusqu",
        "jusque",
        "aupres",
        "environ",
        "mais",
        "donc",
        "puis",
        "comme",
        "aussi",
        "ainsi",
        "alors",
        "quand",
        "encore",
        "tres",
        "plus",
        "moins",
        "deja",
        "ensuite",
        # verbes très courants
        "etre",
        "etait",
        "etaient",
        "avoir",
        "avait",
        "avaient",
        "sont",
        "fait",
        "faite",
        # temps et nombres
        "date",
        "dates",
        "annee",
        "annees",
        "mois",
        "jour",
        "jours",
        "deux",
        "trois",
        "quatre",
        "cinq",
    }
)


@dataclass(frozen=True)
class Theme:
    """Thème d'un événement : clé, libellé, fenêtre en années, préfixe de reconnaissance."""

    key: str
    label: str
    window: int
    prefix: Optional[str]


SHARED_EXPERIENCE_THEMES: Tuple[Theme, ...] = (
    Theme("deportation", "Déportation", 0, "deport"),
    Theme("internement", "Internement", 0, "intern"),
    Theme("resistance", "Résistance", 0, "resist"),
    Theme("voyage", "Voyage", 1, "voyag"),
)

RELATION_THEME = Theme("relation", "Amitié et relations", 3, None)
DEFAULT_WINDOW = 1

_LETTERS_RE = re.compile(r"[a-z]+")


@dataclass(frozen=True)
class SharedReason:
    """Raison d'un lien : même ville (``same_place``) ou mots rares communs (``rare_word``)."""

    kind: str
    place: Optional[str] = None
    words: Tuple[str, ...] = ()


@dataclass
class SharedExperienceEvent:
    """Un événement membre d'une expérience proche."""

    person_id: str
    event_index: int
    event_type_raw: str
    year_start: int
    year_end: int
    place: Optional[str]
    city: Optional[str]


@dataclass
class SharedExperience:
    """Composante d'événements liés réunissant au moins deux personnes."""

    id: str
    theme: str
    label: str
    year_min: int
    year_max: int
    places: List[str]
    reasons: List[SharedReason]
    events: List[SharedExperienceEvent]
    person_count: int
    event_count: int


@dataclass
class SharedExperienceIndex:
    """Expériences proches triées (thème, année de début, id) et nombre d'événements non datés."""

    items: List[SharedExperience]
    undated_total: int


@dataclass
class _Entry:
    """Événement retenu, avec ses données précalculées (une seule fois)."""

    event: SharedExperienceEvent
    theme: Theme
    city_key: str
    words: FrozenSet[str]


def theme_of(tag: str) -> Optional[Theme]:
    """Thème d'un tag « Autre » ; ``None`` pour l'état civil ou un tag sans lettre.

    Premier thème nommé dont un mot du tag commence par le préfixe, puis « relation »
    si un mot est dans ``RELATION_WORDS``, sinon un thème propre au tag (clé : ses mots
    alphabétiques repliés joints par ``_``, chiffres retirés ; fenêtre d'un an).
    """
    if not tag or is_civil_status(tag):
        return None
    key = "_".join(_LETTERS_RE.findall(_fold(tag)))
    if not key:
        return None
    words = _words(tag)
    for theme in SHARED_EXPERIENCE_THEMES:
        prefix = theme.prefix or ""
        if any(w.startswith(prefix) for w in words):
            return theme
    if any(w in RELATION_WORDS for w in words):
        return RELATION_THEME
    label = tag.replace("_", " ").strip()
    return Theme(key=key, label=label, window=DEFAULT_WINDOW, prefix=None)


def event_period(date: Optional[Date]) -> Optional[Tuple[int, int]]:
    """Période ``(début, fin)`` en années ; ``None`` si non datée.

    Sont non datées : date absente, inconnue, textuelle, ou bornée par avant / après.
    """
    if date is None or date.is_unknown or date.text_date:
        return None
    if date.prefix in (DatePrefix.BEFORE, DatePrefix.AFTER):
        return None
    years = date.filter_years_for_range()
    if not years:
        return None
    return min(years), max(years)


def period_gap(a: Tuple[int, int], b: Tuple[int, int]) -> int:
    """Écart en années entre deux périodes ; 0 dès qu'elles se chevauchent."""
    return max(0, max(a[0], b[0]) - min(a[1], b[1]))


def singularize(word: str) -> str:
    """Singulier naïf : un mot de 5 lettres ou plus perd un ``s`` ou un ``x`` final."""
    if len(word) >= 5 and word[-1] in "sx":
        return word[:-1]
    return word


def note_words(text: str) -> FrozenSet[str]:
    """Mots d'un texte : repliés, alphabétiques, d'au moins 4 lettres, hors mots outils, au singulier."""
    result: Set[str] = set()
    for word in _LETTERS_RE.findall(_fold(text or "")):
        if len(word) < MIN_NOTE_WORD_LEN or word in STOPWORDS:
            continue
        single = singularize(word)
        if single not in STOPWORDS:
            result.add(single)
    return frozenset(result)


def _city_key(city: Optional[str]) -> str:
    """Ville repliée comparable ; chaîne vide si la ville est absente ou inconnue (``?``)."""
    key = _fold(city or "").strip()
    return "" if key == "?" else key


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # La plus petite racine (premier dans l'ordre de parcours) l'emporte.
            if rb < ra:
                ra, rb = rb, ra
            self.parent[rb] = ra


def _collect_entries(
    genealogy: Genealogy,
    exclude: AbstractSet[Tuple[str, int]],
    ignored: AbstractSet[str],
) -> Tuple[List[_Entry], int]:
    """Événements retenus et nombre d'événements non datés ; une seule passe sur la base."""
    raw_words: Dict[Tuple[str, int], FrozenSet[str]] = {}
    df: Counter[str] = Counter()
    for person_id, person in genealogy.persons.items():
        for index, event in enumerate(person.events):
            words = note_words(" ".join(event.notes)) if event.notes else frozenset()
            raw_words[(person_id, index)] = words
            df.update(words)

    entries: List[_Entry] = []
    undated = 0
    for person_id, person in genealogy.persons.items():
        for index, event in enumerate(person.events):
            if event.event_type is not EventType.OTHER:
                continue
            tag = (event.event_type_raw or "").strip()
            if is_civil_status(tag):
                continue
            if ignored and not ignored.isdisjoint(_words(tag)):
                continue
            if (person_id, index) in exclude:
                continue
            theme = theme_of(tag)
            if theme is None:
                continue
            period = event_period(event.date)
            if period is None:
                undated += 1
                continue
            city = place_city(event.place)
            removed = note_words(city or "") | note_words(tag)
            words = frozenset(
                w
                for w in raw_words[(person_id, index)] - removed
                if df[w] <= RARE_WORD_MAX_NOTES
                and not (theme.prefix and w.startswith(theme.prefix))
            )
            entries.append(
                _Entry(
                    event=SharedExperienceEvent(
                        person_id=person_id,
                        event_index=index,
                        event_type_raw=tag,
                        year_start=period[0],
                        year_end=period[1],
                        place=event.place,
                        city=city,
                    ),
                    theme=theme,
                    city_key=_city_key(city),
                    words=words,
                )
            )
    return entries, undated


def _sort_key(entry: _Entry) -> Tuple[int, int, str, int]:
    ev = entry.event
    return ev.year_start, ev.year_end, ev.person_id, ev.event_index


def _slices(entries: List[_Entry], window: int) -> List[List[_Entry]]:
    """Tranches chronologiques d'étendue ``max(1, 2 × fenêtre)`` (§ 4.1, point 2)."""
    span = max(1, 2 * window)
    placed = [False] * len(entries)
    result: List[List[_Entry]] = []
    for i, first in enumerate(entries):
        if placed[i]:
            continue
        placed[i] = True
        limit = first.event.year_start + span
        current = [first]
        for j in range(i + 1, len(entries)):
            other = entries[j].event
            if other.year_start > limit:
                break  # trié par début : aucune fin suivante ne peut être <= limit
            if not placed[j] and other.year_end <= limit:
                placed[j] = True
                current.append(entries[j])
        result.append(current)
    return result


def _close(a: _Entry, b: _Entry, window: int) -> bool:
    """Conditions 1 et 2 du lien : personnes distinctes, écart de périodes <= fenêtre."""
    ea, eb = a.event, b.event
    if ea.person_id == eb.person_id:
        return False
    gap = period_gap((ea.year_start, ea.year_end), (eb.year_start, eb.year_end))
    return gap <= window


def _link_same_place(
    chunk: List[_Entry],
    members: List[int],
    window: int,
    uf: "_UnionFind",
    reasons: List[Tuple[int, SharedReason]],
) -> None:
    """Liens « même lieu » d'une ville, par balayage, sans comparer toutes les paires.

    ``members`` suit l'ordre de parcours (début croissant). Pour ``s_i <= s_j``, l'écart
    vaut ``max(0, s_j - f_i)`` : les événements encore « actifs » (``f_i >= s_j - fenêtre``)
    sont exactement ceux que ``j`` peut rejoindre. Deux actifs de personnes distinctes sont
    liés entre eux ; dès que les actifs comptent deux personnes, ils forment donc déjà une
    seule composante, et un seul rattachement suffit. Les composantes obtenues sont celles
    du calcul par paires.
    """
    place = SharedReason(kind="same_place", place=chunk[members[0]].event.city)
    heap: List[Tuple[int, int]] = []
    active: Dict[str, List[int]] = {}
    for j in members:
        ev = chunk[j].event
        while heap and heap[0][0] < ev.year_start - window:
            _, old = heapq.heappop(heap)
            person = chunk[old].event.person_id
            active[person].remove(old)
            if not active[person]:
                del active[person]
        others = [p for p in active if p != ev.person_id]
        if others:
            if len(active) >= 2:
                targets = active[others[0]][:1]
            else:
                targets = list(active[others[0]])
            for i in targets:
                uf.union(i, j)
            reasons.append((j, place))
        active.setdefault(ev.person_id, []).append(j)
        heapq.heappush(heap, (ev.year_end, j))


def _link_chunk(
    chunk: List[_Entry], window: int, uf: "_UnionFind"
) -> List[Tuple[int, SharedReason]]:
    """Relie les événements d'une tranche ; renvoie les raisons (événement, raison)."""
    cities: Dict[str, List[int]] = {}
    words: Dict[str, List[int]] = {}
    for i, entry in enumerate(chunk):
        if entry.city_key:
            cities.setdefault(entry.city_key, []).append(i)
        for word in entry.words:
            words.setdefault(word, []).append(i)

    reasons: List[Tuple[int, SharedReason]] = []
    for key in sorted(cities):
        _link_same_place(chunk, cities[key], window, uf, reasons)

    # Mots rares : au plus RARE_WORD_MAX_NOTES événements par mot, paires peu nombreuses.
    pairs: Set[Tuple[int, int]] = set()
    for members in words.values():
        for x, i in enumerate(members):
            for j in members[x + 1 :]:
                pairs.add((i, j))
    for i, j in sorted(pairs):
        if not _close(chunk[i], chunk[j], window):
            continue
        common = chunk[i].words & chunk[j].words
        uf.union(i, j)
        found = tuple(sorted(common)[:MAX_REASON_WORDS])
        reasons.append((i, SharedReason(kind="rare_word", words=found)))
    return reasons


def _experiences_of_chunk(chunk: List[_Entry]) -> List[SharedExperience]:
    window = chunk[0].theme.window
    uf = _UnionFind(len(chunk))
    reasons_by_event = _link_chunk(chunk, window, uf)

    components: Dict[int, List[int]] = {}
    for i in range(len(chunk)):
        components.setdefault(uf.find(i), []).append(i)
    component_reasons: Dict[int, Set[SharedReason]] = {}
    for i, reason in reasons_by_event:
        component_reasons.setdefault(uf.find(i), set()).add(reason)

    result: List[SharedExperience] = []
    for root, members in components.items():
        events = [chunk[i].event for i in members]
        persons = {ev.person_id for ev in events}
        if len(persons) < 2:
            continue
        theme = chunk[members[0]].theme
        refs = sorted(f"{ev.person_id}:{ev.event_index}" for ev in events)
        digest = hashlib.sha1("|".join([theme.key, *refs]).encode("utf-8")).hexdigest()
        result.append(
            SharedExperience(
                id="exp-" + digest[:10],
                theme=theme.key,
                label=theme.label,
                year_min=min(ev.year_start for ev in events),
                year_max=max(ev.year_end for ev in events),
                places=sorted(
                    {
                        ev.city
                        for ev, i in zip(events, members)
                        if ev.city and chunk[i].city_key
                    }
                ),
                reasons=sorted(
                    component_reasons.get(root, set()),
                    key=lambda r: (r.kind, r.place or "", r.words),
                ),
                events=events,
                person_count=len(persons),
                event_count=len(events),
            )
        )
    return result


def find_shared_experiences(
    genealogy: Genealogy,
    exclude: AbstractSet[Tuple[str, int]] = frozenset(),
    ignored_words: AbstractSet[str] = frozenset(),
) -> SharedExperienceIndex:
    """Regroupe les événements « Autre » personnels en expériences proches (§ 4.1).

    Args:
        genealogy: Généalogie chargée.
        exclude: Références ``(person_id, rang de l'événement)`` déjà rattachées à une
            organisation de la liste ; elles n'entrent pas dans les expériences.
        ignored_words: Mots ignorés par l'utilisateur (mot entier du tag, replié).

    Returns:
        Index trié par thème, année de début puis identifiant.
    """
    ignored = frozenset(_fold(w).strip() for w in ignored_words) - {""}
    entries, undated = _collect_entries(genealogy, exclude, ignored)

    by_theme: Dict[str, List[_Entry]] = {}
    for entry in entries:
        by_theme.setdefault(entry.theme.key, []).append(entry)

    items: List[SharedExperience] = []
    for key in sorted(by_theme):
        themed = sorted(by_theme[key], key=_sort_key)
        window = themed[0].theme.window
        for chunk in _slices(themed, window):
            if len(chunk) >= 2:
                items.extend(_experiences_of_chunk(chunk))
    items.sort(key=lambda e: (e.theme, e.year_min, e.id))
    return SharedExperienceIndex(items=items, undated_total=undated)
