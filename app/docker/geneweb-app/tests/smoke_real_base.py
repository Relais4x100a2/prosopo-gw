"""Test de fumée des pages Streamlit sur une base réelle (hors dépôt).

Usage : GENEWEB_REAL_BASE=<base.gw> python tests/smoke_real_base.py

Chaque page est exécutée avec ``streamlit.testing.v1.AppTest`` après chargement de la base
par l'extracteur de l'application. Les traces complètes sont écrites dans ``$SMOKE_OUT``
(défaut : ``~/oracle_out/smoke``, hors dépôt). La sortie standard ne contient que des
messages masqués (lettres -> « a », chiffres -> « 9 ») : aucun nom ni lieu de la base.
"""

from __future__ import annotations

import os
import re
import sys
import time
import traceback
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from src.pevt_extractor import PEVTExtractor  # noqa: E402


def mask(text: str, limit: int = 120) -> str:
    return re.sub(r"\d", "9", re.sub(r"[^\W\d_]", "a", text))[:limit]


def main() -> int:
    base = os.environ.get("GENEWEB_REAL_BASE")
    if not base:
        print("GENEWEB_REAL_BASE est obligatoire")
        return 2
    out = Path(os.environ.get("SMOKE_OUT", Path.home() / "oracle_out" / "smoke"))
    out.mkdir(parents=True, exist_ok=True)

    start = time.perf_counter()
    extractor = PEVTExtractor()
    extractor.load_from_file(base)
    print(f"extraction : {extractor.stats.get('total_pevts')} pevt en {time.perf_counter() - start:.1f}s")

    failures = 0
    for page in ["app.py", *sorted(f"pages/{p.name}" for p in (APP / "pages").glob("*.py"))]:
        t0 = time.perf_counter()
        label = re.sub(r"[^\w.]", "_", page)
        try:
            at = AppTest.from_file(str(APP / page), default_timeout=120)
            at.session_state["uploaded_file_path"] = base
            at.session_state["all_pevts"] = extractor.all_pevts
            at.session_state["pevt_stats"] = extractor.stats
            at.run()
            errors = list(at.exception) + list(at.error)
        except Exception as exc:  # noqa: BLE001
            errors = []
            (out / f"{label}.trace.txt").write_text(traceback.format_exc(), encoding="utf-8")
            print(f"{label} | EXCEPTION | {mask(str(exc))}")
            failures += 1
            continue
        status = "OK" if not errors else f"{len(errors)} erreur(s)"
        print(f"{label} | {status} | {time.perf_counter() - t0:.1f}s")
        if errors:
            failures += 1
            body = "\n\n".join(str(getattr(e, "value", e)) + "\n" + "\n".join(getattr(e, "stack_trace", []) or []) for e in errors)
            (out / f"{label}.trace.txt").write_text(body, encoding="utf-8")
            for e in errors[:3]:
                print(f"  {mask(str(getattr(e, 'value', e)))}")
    print(f"traces complètes : {out}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
