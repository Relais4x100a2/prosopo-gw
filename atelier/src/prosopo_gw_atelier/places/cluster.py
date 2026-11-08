"""Grouping of decomposed writings into clusters, one per real place (design § 6.2).

Keys
    A writing that names a former commune (fusion, association, delegation:
    ``Decomposition.historical``) goes to the cluster
    ``historique:<former code>|<name key>`` (Hesdin and Hesdin-la-Forêt share
    the code 62447, hence the name). Any other writing whose commune is
    resolved goes to ``insee:<code>``. Any other writing is keyed by its
    normalized name (the commune or former name element, else the first
    segment that is neither a code nor a department, region or country) plus
    its department when one was written: ``name:<key>`` or
    ``name:<key>|<department>``.

Partitions
    The writings of one ``name:`` key are split when their levels contradict
    (plan choice 7). Two chains are compatible when the normalized names of one
    are a subsequence of the other's. Writings are taken from the longest chain
    to the shortest (ties: the smallest writing), each into the first partition
    whose first (longest) chain is compatible, else into a new partition. The
    first partition keeps the id ``name:<key>``, the next ones get ``~2``,
    ``~3``… in creation order. A key split in several partitions is neither
    merged by similarity nor a similarity target.

Confidence of a writing
    ``high``: resolved from a code (an INSEE code element equal to the commune,
    or a postal code element serving it) or from a name plus a department
    element that agrees with the commune; ``medium``: resolved otherwise (a
    name unique in the COG; a region is not checked against the commune, as it
    may be a pre-2016 region while communes carry current region codes);
    ``low``: not resolved.

Confidence of a cluster
    The best confidence among its members (one ``Roubaix, Nord`` lifts the
    ``Roubaix`` cluster to ``high``), except that a cluster which received a
    writing by similarity, or which carries an alternative reading, is capped
    at ``medium``: neither the merge nor the reading is more than a proposal.
    A cluster without INSEE code (``name:``, every partition) is always ``low``.

Similarity
    Only writings with no candidate commune at all (a name the COG does not
    know) are merged by similarity. ``difflib.SequenceMatcher`` ratio on the
    normalized names, at least ``SIMILARITY_THRESHOLD``, inside a block: same
    first character and same department, or a department unknown on either
    side. A writing goes to the best-scoring cluster of its block (``insee:``,
    ``historique:`` or unsplit ``name:``, ties to the smallest id); unresolved
    groups are processed in id order. Writings with several candidates
    (homonyms written without department, a postal code alone…) keep their
    own ``low`` cluster: they are neither merged nor merge targets.

Anchor
    A ``historique:`` cluster is anchored only on the validated place whose
    ``historical`` equals ``<former code>|<name key>``. The other clusters
    never anchor on a place that has a ``historical``; among the others,
    ``anchor_place_id`` is the place whose INSEE code equals the cluster's,
    else whose name key equals the cluster's (not across two different INSEE
    codes, nor across two different departments when both are known: the
    place's department may be a code or a name); never by similarity alone.
    Several matches: the smallest ``place_id``.

Levels
    The longest ``rule_levels`` chain of the cluster (ties: the most frequent
    chain, then the smallest writing). For an ``insee:`` or ``historique:``
    cluster only the writings resolved to it compete, so the chain is the one
    the COG rebuilds for the commune (``rule_levels``), with the unrecognised
    written levels of the chosen writing. ``postal_code`` is the most frequent
    ``written_postal_code`` of the members (ties: the smallest value).
    ``alternatives`` lists the distinct ``alternative_levels`` of the members,
    in writing order.

The output is deterministic: clusters sorted by id, writings sorted, whatever
the order of the input mapping. Sorting for the validation queue (confidence,
then occurrences) is left to the caller.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from fractions import Fraction
from typing import Literal

from ..refdata import RefData, normalize
from .decompose import segments
from .levels import Level, alternative_levels, rule_levels, written_postal_code
from .model import Decomposition

Confidence = Literal["high", "medium", "low"]

SIMILARITY_THRESHOLD = 0.85
"""Minimum ``SequenceMatcher`` ratio between normalized names to merge.

``lile``/``lille`` scores 0.89 and merges; ``lille``/``lillers`` scores 0.83
and does not.
"""

# The threshold as an exact fraction, for the integer pruning bounds.
_THRESHOLD = Fraction(SIMILARITY_THRESHOLD).limit_denominator(1000)
_NUM, _DEN = _THRESHOLD.numerator, _THRESHOLD.denominator

_RANK: dict[Confidence, int] = {"low": 0, "medium": 1, "high": 2}
_CODE = re.compile(r"^(?:\d{5}|2[ABab]\d{3})$")


@dataclass(frozen=True)
class KnownPlace:
    """A place already validated in the personal reference."""

    place_id: str
    insee: str | None
    """INSEE code of the commune level; ``None`` when the first validated
    level is a ``commune_historique``."""
    name_key: str
    """Name key of the first validated level."""
    department: str | None = None
    """As stored in the place (a code, or a name the COG may know)."""
    historical: str | None = None
    """``<former code>|<name key>`` when the first validated level is a
    ``commune_historique``."""


@dataclass
class Cluster:
    """Writings proposed as one real place."""

    id: str
    writings: list[str]
    levels: tuple[Level, ...]
    postal_code: str | None
    confidence: Confidence
    anchor_place_id: str | None = None
    alternatives: tuple[tuple[Level, ...], ...] = ()


@dataclass
class _Group:
    id: str
    key: str
    department: str | None
    insee: str | None
    historical: str | None = None
    members: list[Decomposition] = field(default_factory=list)
    """Every writing of the cluster, similarity merges included."""
    own: list[Decomposition] = field(default_factory=list)
    """The writings keyed to this group (no similarity merge)."""
    merged: bool = False


def name_key(name: str) -> str:
    """Name key of a place, as compared by the anchor (``KnownPlace.name_key``).

    The same key ``build_clusters`` gives a group: the normalized commune name
    (official COG name for a resolved commune), without department.
    """
    return normalize(name)


def _name_segment(decomposition: Decomposition, ref: RefData) -> str:
    for element in decomposition.elements:
        if element.kind in ("commune", "former_name"):
            return element.value
    for segment in segments(decomposition.writing):
        if _CODE.match(segment):
            continue
        if ref.department(segment) or ref.region(segment) or ref.country(segment):
            continue
        return segment
    return decomposition.writing.strip()


def _department(decomposition: Decomposition) -> str | None:
    for element in decomposition.elements:
        if element.kind == "department":
            return element.value
    return None


def _writing_confidence(decomposition: Decomposition, ref: RefData) -> Confidence:
    insee = decomposition.insee
    if insee is None:
        return "low"
    commune = ref.commune_by_insee(insee)
    kinds = {element.kind for element in decomposition.elements}
    named = bool(kinds & {"commune", "former_name"})
    for element in decomposition.elements:
        if element.kind == "insee_code" and element.value == insee:
            return "high"
        if element.kind == "postal_code" and any(
            c.insee == insee for c in ref.communes_by_postal(element.value)
        ):
            return "high"
        if (
            named
            and element.kind == "department"
            and commune is not None
            and element.value == commune.department
        ):
            return "high"
    return "medium"


def _majority(values: Iterable[str]) -> str | None:
    counts = Counter(values)
    if not counts:
        return None
    return min(counts.items(), key=lambda item: (-item[1], item[0]))[0]


def _levels(
    group: _Group, chains: Mapping[str, tuple[Level, ...]]
) -> tuple[Level, ...]:
    contenders = group.own if group.insee is not None else group.members
    counts = Counter(chains[m.writing] for m in contenders)
    best = min(
        contenders,
        key=lambda m: (
            -len(chains[m.writing]),
            -counts[chains[m.writing]],
            m.writing,
        ),
    )
    return chains[best.writing]


def _alternatives(group: _Group, ref: RefData) -> tuple[tuple[Level, ...], ...]:
    found: list[tuple[Level, ...]] = []
    for member in sorted(group.members, key=lambda m: m.writing):
        chain = alternative_levels(member, ref)
        if chain is not None and chain not in found:
            found.append(chain)
    return tuple(found)


def _anchor(group: _Group, known: Mapping[str, KnownPlace], ref: RefData) -> str | None:
    places = sorted(known.values(), key=lambda p: p.place_id)
    if group.historical is not None:
        for place in places:
            if place.historical == group.historical:
                return place.place_id
        return None
    places = [place for place in places if place.historical is None]
    if group.insee is not None:
        for place in places:
            if place.insee == group.insee:
                return place.place_id
    for place in places:
        if place.name_key != group.key:
            continue
        if place.insee is not None and group.insee is not None:
            continue  # two different INSEE codes: not the same place
        if place.department and group.department is not None:
            department = ref.department(place.department) or place.department.strip()
            if department != group.department:
                continue  # same name, another department: not the same place
        return place.place_id
    return None


def _confidence(group: _Group, ref: RefData, alternatives: bool) -> Confidence:
    if group.insee is None:
        return "low"
    best: Confidence = "low"
    for member in group.members:
        level = _writing_confidence(member, ref)
        if _RANK[level] > _RANK[best]:
            best = level
    if (group.merged or alternatives) and best == "high":
        return "medium"
    return best


def _compatible(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    """Whether one sequence of names is a subsequence of the other."""
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    rest = iter(long)
    return all(name in rest for name in short)


def _partitions(group: _Group, chains: Mapping[str, tuple[Level, ...]]) -> list[_Group]:
    """Split a ``name:`` group whose levels contradict (plan choice 7)."""
    names = {
        m.writing: tuple(normalize(level.name) for level in chains[m.writing])
        for m in group.members
    }
    ordered = sorted(group.members, key=lambda m: (-len(names[m.writing]), m.writing))
    heads: list[tuple[str, ...]] = []
    parts: list[_Group] = []
    for member in ordered:
        chain = names[member.writing]
        index = next(
            (i for i, head in enumerate(heads) if _compatible(head, chain)), None
        )
        if index is None:
            index = len(parts)
            heads.append(chain)
            suffix = "" if index == 0 else f"~{index + 1}"
            parts.append(
                _Group(f"{group.id}{suffix}", group.key, group.department, None)
            )
        parts[index].members.append(member)
        parts[index].own.append(member)
    return parts


def _length_range(size: int) -> range:
    """Lengths ``n`` such that ``2 * min(size, n) / (size + n)`` reaches the threshold.

    Exact integer arithmetic: a float bound can mis-round at the boundary.
    """
    low = -(-_NUM * size // (2 * _DEN - _NUM))
    high = size * (2 * _DEN - _NUM) // _NUM
    return range(low, high + 1)


def _may_reach(matches: int, total: int) -> bool:
    """Whether ``2 * matches / total`` reaches the threshold (exactly)."""
    return 2 * matches * _DEN >= _NUM * total


class _Blocks:
    """Similarity targets indexed by first character, then by key length."""

    def __init__(self) -> None:
        self._targets: dict[str, dict[int, list[tuple[frozenset[str], _Group]]]] = (
            defaultdict(lambda: defaultdict(list))
        )

    def add(self, group: _Group) -> None:
        block = self._targets[group.key[:1]]
        block[len(group.key)].append((frozenset(group.key), group))

    def best(self, key: str, department: str | None) -> _Group | None:
        block = self._targets.get(key[:1])
        if not block:
            return None
        matcher = SequenceMatcher(autojunk=False)
        matcher.set_seq2(key)
        size = len(key)
        letters = frozenset(key)
        best: _Group | None = None
        best_score = SIMILARITY_THRESHOLD
        # ratio <= 2 * min(a, b) / (a + b): only these lengths can reach it.
        for length in _length_range(size):
            for target_letters, target in block.get(length, ()):
                if (
                    department is not None
                    and target.department is not None
                    and department != target.department
                ):
                    continue
                # Each distinct letter missing from the other side is at least
                # one unmatched character: a cheap bound before quick_ratio.
                matches = min(
                    size - len(letters - target_letters),
                    length - len(target_letters - letters),
                )
                if not _may_reach(matches, size + length):
                    continue
                matcher.set_seq1(target.key)
                # Float vs float: rounding is monotonic, so an exact 0.85
                # ratio still compares equal to the threshold.
                if matcher.quick_ratio() < best_score:
                    continue
                score = matcher.ratio()
                if score < best_score:
                    continue
                if best is None or score > best_score or target.id < best.id:
                    best, best_score = target, score
        return best


def build_clusters(
    decompositions: Mapping[str, Decomposition],
    ref: RefData,
    known: Mapping[str, KnownPlace],
) -> list[Cluster]:
    """Group ``decompositions`` (keyed by writing) into clusters."""
    chains = {
        writing: rule_levels(decomposition, ref)
        for writing, decomposition in decompositions.items()
    }
    keyed: dict[str, _Group] = {}
    frozen: set[str] = set()
    for writing in sorted(decompositions):
        decomposition = decompositions[writing]
        historical: str | None = None
        if decomposition.insee is not None:
            commune = ref.commune_by_insee(decomposition.insee)
            department = commune.department if commune else None
            insee: str | None = decomposition.insee
            former = decomposition.historical
            if former is not None:
                key = name_key(former.name)
                historical = f"{former.insee}|{key}"
                group_id = f"historique:{historical}"
            else:
                key = name_key(commune.name) if commune else decomposition.insee
                group_id = f"insee:{decomposition.insee}"
        else:
            key = name_key(_name_segment(decomposition, ref))
            department = _department(decomposition)
            group_id = (
                f"name:{key}" if department is None else f"name:{key}|{department}"
            )
            insee = None
            if decomposition.candidates:
                frozen.add(group_id)
        group = keyed.setdefault(
            group_id, _Group(group_id, key, department, insee, historical)
        )
        group.members.append(decomposition)
        group.own.append(decomposition)

    groups: dict[str, _Group] = {}
    for group_id in sorted(keyed):
        group = keyed[group_id]
        parts = [group] if group.insee is not None else _partitions(group, chains)
        for part in parts:
            groups[part.id] = part
            if len(parts) > 1 or group_id in frozen:
                frozen.add(part.id)

    blocks = _Blocks()
    for group_id in sorted(groups):
        if groups[group_id].insee is not None:
            blocks.add(groups[group_id])
    final: dict[str, _Group] = {}
    for group_id in sorted(groups):
        group = groups[group_id]
        if group.insee is not None or group_id in frozen:
            final[group_id] = group
            continue
        target = blocks.best(group.key, group.department)
        # Not transitive: a merged group is not a target for later groups.
        if target is None:
            final[group_id] = group
            blocks.add(group)
            continue
        target.members.extend(group.members)
        target.merged = True
        final.setdefault(target.id, target)

    clusters = []
    for group_id in sorted(final):
        group = final[group_id]
        alternatives = _alternatives(group, ref)
        clusters.append(
            Cluster(
                id=group.id,
                writings=sorted(m.writing for m in group.members),
                levels=_levels(group, chains),
                postal_code=_majority(
                    code
                    for member in group.members
                    if (code := written_postal_code(member)) is not None
                ),
                confidence=_confidence(group, ref, bool(alternatives)),
                anchor_place_id=_anchor(group, known, ref),
                alternatives=alternatives,
            )
        )
    return clusters
