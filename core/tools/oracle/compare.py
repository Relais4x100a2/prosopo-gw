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


def compare_families(got: Genealogy, ref: Genealogy, stats: Stats) -> int:
    """Apparie les familles par ordre d'apparition (clés des conjoints vérifiées).

    Renvoie le nombre de familles de ``ref`` sans équivalent.
    """
    g_list = list(got.families.values())
    r_list = list(ref.families.values())
    unmatched = 0
    i = 0
    for r in r_list:
        rk = _family_key(ref, r)
        window = range(i, min(i + 3, len(g_list)))
        hit = next((k for k in window if _family_key(got, g_list[k]) == rk), None)
        if hit is None:
            unmatched += 1
            continue
        i = hit + 1
        gf = _family_fields(g_list[hit])
        for name, ref_value in _family_fields(r).items():
            _stat(stats, name).add(ref_value, gf[name])
    return unmatched


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
    unmatched = {"familles": compare_families(got, ref, stats)}
    print(render_table(stats, unmatched))
    if args.examples:
        for name in sorted(stats):
            for r, g in stats[name].examples:
                print(f"  {name}: gwu={r!r} geneweb-py={g!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
