"""Copie filtrée d'un .gw : retire les seules lignes que GeneWeb officiel refuse.

Usage : python filter.py <src.gw> <dst.gw> [--drop REGEX]...
Les blocs ``fevt`` sont conservés (règle de gwc, voir la note de conception).
Sortie standard : décompte JSON des lignes retirées, sans aucun contenu.
"""

import argparse
import collections
import json
import re

DEFAULT_DROP = r"^wnote "


def filter_lines(
    lines: list[str], drop: list[re.Pattern[str]]
) -> tuple[list[str], collections.Counter[str]]:
    out: list[str] = []
    counts: collections.Counter[str] = collections.Counter()
    for line in lines:
        if line.startswith("comm ") and out and out[-1].startswith("comm "):
            counts["comm répété"] += 1
            continue
        hit = next((p.pattern for p in drop if p.search(line)), None)
        if hit:
            counts[hit] += 1
            continue
        out.append(line)
    return out, counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--drop", action="append", default=None)
    args = ap.parse_args()
    patterns = [re.compile(p) for p in (args.drop or [DEFAULT_DROP])]
    with open(args.src, encoding="utf-8") as f:
        lines = f.read().replace("\r\n", "\n").split("\n")
    out, counts = filter_lines(lines, patterns)
    with open(args.dst, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(json.dumps(dict(counts), ensure_ascii=False))


if __name__ == "__main__":
    main()
