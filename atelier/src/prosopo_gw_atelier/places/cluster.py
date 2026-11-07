"""Grouping of decomposed writings into clusters, one per real place (design § 6.2).

Keys
    A writing whose commune is resolved goes to the cluster ``insee:<code>``.
    Any other writing is keyed by its normalized name (the commune or former
    name element, else the first segment that is neither a code nor a
    department, region or country) plus its department when one was written:
    ``name:<key>`` or ``name:<key>|<department>``.

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
    writing by similarity is capped at ``medium``: the merge itself is never
    more than a proposal. A cluster without INSEE code is always ``low``.

Similarity
    Only writings with no candidate commune at all (a name the COG does not
    know) are merged by similarity. ``difflib.SequenceMatcher`` ratio on the
    normalized names, at least ``SIMILARITY_THRESHOLD``, inside a block: same
    first character and same department, or a department unknown on either
    side. A writing goes to the best-scoring cluster of its block (resolved or
    not, ties to the smallest id); unresolved groups are processed in id order.
    Writings with several candidates (homonyms written without department, a
    postal code alone…) keep their own ``low`` cluster: they are neither merged
    nor merge targets.

Anchor
    ``anchor_place_id`` is the already validated place whose INSEE code equals
    the cluster's, else whose name key equals the cluster's (not across two
    different INSEE codes); never by similarity alone. Several matches: the
    smallest ``place_id``.

Proposal
    For each element kind, the value most often written in the cluster (ties
    to the smallest value); for a cluster without commune element, the most
    frequent name segment as commune. When the INSEE code is known, the COG
    fills ``commune`` (official name), ``department`` (code), ``region`` (name)
    and ``insee_code``.

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
from .model import Decomposition, ElementKind

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
    name_key: str


@dataclass
class Cluster:
    """Writings proposed as one real place."""

    id: str
    writings: list[str]
    proposal: dict[ElementKind, str]
    confidence: Confidence
    anchor_place_id: str | None = None


@dataclass
class _Group:
    id: str
    key: str
    department: str | None
    insee: str | None
    members: list[Decomposition] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
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


def _proposal(group: _Group, ref: RefData) -> dict[ElementKind, str]:
    by_kind: dict[ElementKind, list[str]] = defaultdict(list)
    for member in group.members:
        for element in member.elements:
            by_kind[element.kind].append(element.value)
    proposal: dict[ElementKind, str] = {}
    for kind in sorted(by_kind):
        value = _majority(by_kind[kind])
        if value is not None:
            proposal[kind] = value
    if "commune" not in proposal and "former_name" not in proposal:
        name = _majority(n for n in group.names if n)
        if name is not None:
            proposal["commune"] = name
    commune = ref.commune_by_insee(group.insee) if group.insee else None
    if commune is not None:
        proposal["commune"] = commune.name
        proposal["department"] = commune.department
        region = ref.region_name(commune.region)
        if region is not None:
            proposal["region"] = region
        proposal["insee_code"] = commune.insee
    return proposal


def _anchor(group: _Group, known: Mapping[str, KnownPlace]) -> str | None:
    places = sorted(known.values(), key=lambda p: p.place_id)
    if group.insee is not None:
        for place in places:
            if place.insee == group.insee:
                return place.place_id
    for place in places:
        if place.name_key != group.key:
            continue
        if place.insee is not None and group.insee is not None:
            continue  # two different INSEE codes: not the same place
        return place.place_id
    return None


def _confidence(group: _Group, ref: RefData) -> Confidence:
    if group.insee is None:
        return "low"
    best: Confidence = "low"
    for member in group.members:
        level = _writing_confidence(member, ref)
        if _RANK[level] > _RANK[best]:
            best = level
    if group.merged and best == "high":
        return "medium"
    return best


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
    groups: dict[str, _Group] = {}
    frozen: set[str] = set()
    for writing in sorted(decompositions):
        decomposition = decompositions[writing]
        name = ""
        if decomposition.insee is not None:
            commune = ref.commune_by_insee(decomposition.insee)
            group_id = f"insee:{decomposition.insee}"
            key = name_key(commune.name) if commune else decomposition.insee
            department = commune.department if commune else None
            insee: str | None = decomposition.insee
        else:
            name = _name_segment(decomposition, ref)
            key = name_key(name)
            department = _department(decomposition)
            group_id = (
                f"name:{key}" if department is None else f"name:{key}|{department}"
            )
            insee = None
            if decomposition.candidates:
                frozen.add(group_id)
        group = groups.setdefault(group_id, _Group(group_id, key, department, insee))
        group.members.append(decomposition)
        if insee is None:
            group.names.append(name)

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
        target.names.extend(group.names)
        target.merged = True
        final.setdefault(target.id, target)

    clusters = []
    for group_id in sorted(final):
        group = final[group_id]
        clusters.append(
            Cluster(
                id=group.id,
                writings=sorted(m.writing for m in group.members),
                proposal=_proposal(group, ref),
                confidence=_confidence(group, ref),
                anchor_place_id=_anchor(group, known),
            )
        )
    return clusters
