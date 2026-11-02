"""Oracle : compare notre lecture d'un .gw à la relecture écrite par gwu.

Usage : python compare.py <source.gw> <rt.gw> [--stream] [--examples]

Ne sort que des comptages agrégés. Les exemples (option --examples) sont masqués :
lettres -> « a », chiffres -> « 9 ».
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

from geneweb_py import GeneWebParser
from geneweb_py.core.event import Event
from geneweb_py.core.family import Family
from geneweb_py.core.genealogy import Genealogy
from geneweb_py.core.person import Person


def copy_decode(word: str) -> str:
    """Décodage de gwcomp.ml : « _ » -> espace, « \\x » -> x."""
    out: list[str] = []
    i = 0
    while i < len(word):
        c = word[i]
        if c == "\\" and i + 1 < len(word):
            i += 1
            out.append(word[i])
        elif c == "_":
            out.append(" ")
        else:
            out.append(c)
        i += 1
    return "".join(out)


def cut_space(s: str) -> str:
    if s == " ":
        return ""
    if s[:1] == " ":
        s = s[1:]
    if s[-1:] == " ":
        s = s[:-1]
    return s


def norm(value: str | None) -> str:
    """Valeur stockée par geneweb-py -> valeur GeneWeb (None -> chaîne vide)."""
    return cut_space(copy_decode(value)) if value else ""


def mask(value: str) -> str:
    out = "".join("9" if c.isdigit() else "a" if c.isalpha() else c for c in value)
    return out[:60]


@dataclass
class FieldStat:
    present: int = 0
    equal: int = 0
    raw_underscore: int = 0
    examples: list[tuple[str, str]] = field(default_factory=list)

    def add(self, ref: str, got: str) -> None:
        if not norm(ref):
            return
        self.present += 1
        if norm(ref) == norm(got):
            self.equal += 1
        elif len(self.examples) < 5:
            self.examples.append((mask(norm(ref)), mask(norm(got))))
        if "_" in (got or ""):
            self.raw_underscore += 1

    @property
    def rate(self) -> float | None:
        return self.equal / self.present if self.present else None


Stats = dict[str, FieldStat]


def _stat(stats: Stats, name: str) -> FieldStat:
    return stats.setdefault(name, FieldStat())


def load(path: str, stream: bool) -> Genealogy:
    return GeneWebParser(validate=False, stream_mode=stream).parse_file(path)


def person_key(p: Person | None) -> tuple[str, str, int]:
    if p is None:
        return ("?", "?", 0)
    return (norm(p.last_name), norm(p.first_name), p.occurrence_number or 0)


def _raw_date(d: object) -> str:
    return getattr(d, "raw_text", None) or ""


def _family_key(
    g: Genealogy, f: Family
) -> tuple[tuple[str, str, int], tuple[str, str, int]]:
    return (
        person_key(g.persons.get(f.husband_id) if f.husband_id else None),
        person_key(g.persons.get(f.wife_id) if f.wife_id else None),
    )


def _family_kind(f: Family) -> str:
    status = f.marriage_status.value
    if status in ("nm", "eng"):
        return status
    quals = [q.value for q in f.family_qualifiers]
    return quals[0] if quals else ""


def _family_divorce(f: Family) -> str:
    if f.divorce_date is not None:
        return _raw_date(f.divorce_date) or "div"
    return "div" if f.marriage_status.value == "div" else ""


def _family_fields(f: Family) -> dict[str, str]:
    return {
        "fam.marriage_date": _raw_date(f.marriage_date),
        "fam.marriage_place": f.marriage_place or "",
        "fam.marriage_source": f.marriage_source or "",
        "fam.kind": _family_kind(f),
        "fam.divorce": _family_divorce(f),
        "fam.family_source": (f.family_source or "").strip(),
        "fam.witnesses": str(len(f.witnesses)) if f.witnesses else "",
    }


def _match_families(
    got: Genealogy, ref: Genealogy
) -> tuple[list[tuple[Family, Family]], int]:
    """Apparie les familles par ordre d'apparition (clés des conjoints vérifiées)."""
    g_list = list(got.families.values())
    pairs: list[tuple[Family, Family]] = []
    unmatched = 0
    i = 0
    for r in ref.families.values():
        rk = _family_key(ref, r)
        window = range(i, min(i + 3, len(g_list)))
        hit = next((k for k in window if _family_key(got, g_list[k]) == rk), None)
        if hit is None:
            unmatched += 1
            continue
        i = hit + 1
        pairs.append((g_list[hit], r))
    return pairs, unmatched


def compare_families(got: Genealogy, ref: Genealogy, stats: Stats) -> int:
    """Compare les champs des familles ; renvoie le nombre de familles de ``ref`` sans équivalent."""
    pairs, unmatched = _match_families(got, ref)
    for gf, rf in pairs:
        gvals = _family_fields(gf)
        for name, ref_value in _family_fields(rf).items():
            _stat(stats, name).add(ref_value, gvals[name])
    return unmatched


PERSON_FIELDS: list[tuple[str, str, bool]] = [
    ("birth_date", "birth_date", True),
    ("birth_place", "birth_place", False),
    ("birth_source", "birth_source", False),
    ("baptism_date", "baptism_date", True),
    ("baptism_place", "baptism_place", False),
    ("baptism_source", "baptism_source", False),
    ("death_date", "death_date", True),
    ("death_place", "death_place", False),
    ("death_source", "death_source", False),
    ("burial_place", "burial_place", False),
    ("burial_source", "burial_source", False),
    ("occupation", "occupation", False),
    ("person_source", "person_source", False),
]


def _persons_by_key(g: Genealogy) -> dict[tuple[str, str, int], Person]:
    out: dict[tuple[str, str, int], Person] = {}
    for p in g.persons.values():
        out.setdefault(person_key(p), p)
    return out


def _person_value(p: Person, attr: str, is_date: bool) -> str:
    value = getattr(p, attr, None)
    return _raw_date(value) if is_date else (value or "")


def compare_persons(got: Genealogy, ref: Genealogy, stats: Stats) -> int:
    """Compare les champs des personnes appariées par clé ; renvoie les personnes de ``ref`` sans équivalent."""
    g_by_key = _persons_by_key(got)
    unmatched = 0
    for key, rp in _persons_by_key(ref).items():
        gp = g_by_key.get(key)
        if gp is None:
            unmatched += 1
            continue
        for name, attr, is_date in PERSON_FIELDS:
            _stat(stats, f"pers.{name}").add(
                _person_value(rp, attr, is_date), _person_value(gp, attr, is_date)
            )
    return unmatched


def _event_kind(e: Event) -> str:
    fam_type = getattr(e, "family_event_type", None)
    if getattr(e, "event_type_raw", None):
        return str(e.event_type_raw)
    if fam_type is not None:
        return str(fam_type.value)
    return str(e.event_type.value)


def _events_by_key(events: list[Event]) -> dict[tuple[str, str], Event]:
    out: dict[tuple[str, str], Event] = {}
    for e in events:
        out.setdefault((_event_kind(e), norm(_raw_date(e.date))), e)
    return out


def _compare_event_lists(
    prefix: str, got: list[Event], ref: list[Event], stats: Stats
) -> int:
    g_by_key = _events_by_key(got)
    unmatched = 0
    for key, re_ in _events_by_key(ref).items():
        ge = g_by_key.get(key)
        if ge is None:
            unmatched += 1
            continue
        _stat(stats, f"{prefix}.place").add(re_.place or "", ge.place or "")
        _stat(stats, f"{prefix}.source").add(re_.source or "", ge.source or "")
        _stat(stats, f"{prefix}.witnesses").add(
            str(len(re_.witnesses)) if re_.witnesses else "", str(len(ge.witnesses))
        )
    return unmatched


def compare_events(got: Genealogy, ref: Genealogy, stats: Stats) -> int:
    """Compare les événements ``pevt`` (personnes appariées) et ``fevt`` (familles appariées)."""
    g_by_key = _persons_by_key(got)
    unmatched = 0
    for key, rp in _persons_by_key(ref).items():
        gp = g_by_key.get(key)
        if gp is not None:
            unmatched += _compare_event_lists(
                "pevt", list(gp.events), list(rp.events), stats
            )
    pairs, _ = _match_families(got, ref)
    for gf, rf in pairs:
        unmatched += _compare_event_lists(
            "fevt", list(gf.events), list(rf.events), stats
        )
    return unmatched


NAIVE_TAGS = ("#bp", "#bs", "#dp", "#ds", "#occu", "#src", "#mp", "#ms")


def naive_tag_counts(text: str) -> dict[str, int]:
    """Contrôle indépendant de notre lecture : découpage naïf sur les espaces, hors blocs de notes."""
    counts = dict.fromkeys((*NAIVE_TAGS, "wit"), 0)
    in_notes = False
    for line in text.split("\n"):
        if line.startswith(("begin notes", "notes-db", "page-ext", "wizard-note")):
            in_notes = True
            continue
        if line.startswith("end ") and in_notes:
            in_notes = False
            continue
        if in_notes:
            continue
        if line.startswith("wit "):
            counts["wit"] += 1
        for word in line.split(" "):
            if word in NAIVE_TAGS:
                counts[word] += 1
    return counts


def render_table(stats: Stats, unmatched: dict[str, int]) -> str:
    lines = [
        "| champ | présents (gwu) | identiques | écarts | encore bruts | taux |",
        "|---|---|---|---|---|---|",
    ]
    for name in sorted(stats):
        s = stats[name]
        rate = "n/a" if s.rate is None else f"{s.rate * 100:.1f} %"
        lines.append(
            f"| {name} | {s.present} | {s.equal} | {s.present - s.equal} | {s.raw_underscore} | {rate} |"
        )
    lines.append("")
    lines.extend(f"- {k} non appariés : {v}" for k, v in sorted(unmatched.items()))
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source")
    ap.add_argument("rt")
    ap.add_argument("--stream", action="store_true")
    ap.add_argument("--examples", action="store_true")
    args = ap.parse_args(argv)
    got, ref = load(args.source, args.stream), load(args.rt, args.stream)
    stats: Stats = {}
    unmatched = {
        "familles": compare_families(got, ref, stats),
        "personnes": compare_persons(got, ref, stats),
        "événements": compare_events(got, ref, stats),
    }
    print(render_table(stats, unmatched))
    with open(args.rt, encoding="utf-8") as f:
        naive = naive_tag_counts(f.read())
    print(
        "\ncontrôle naïf (rt.gw) : " + ", ".join(f"{k}={v}" for k, v in naive.items())
    )
    if args.examples:
        for name in sorted(stats):
            for r, g in stats[name].examples:
                print(f"  {name}: gwu={r!r} geneweb-py={g!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
