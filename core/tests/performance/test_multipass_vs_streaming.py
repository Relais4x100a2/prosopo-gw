"""
Comparaisons de performance : streaming lexical vs construction multi-passes.

Un fichier > 1 Mo est généré sur disque pour exercer ``parse_file`` en
``stream_mode=True`` (pipeline streaming) et en mode classique avec
``use_multipass=True``.
"""

import time
from pathlib import Path

import pytest

from geneweb_py import GeneWebParser


def _gw_chunk_template(idx: int) -> str:
    return f"""fam Fam{idx:06d} Jean 15/03/1950 + Spouse{idx:06d} Marie 20/05/1952
beg
- h Fam{idx:06d} Pierre 10/01/1975
- f Fam{idx:06d} Sophie 15/06/1978
end

"""


def _write_large_gw_file(path: Path, min_bytes: int = 1_100_000) -> int:
    """Écrit un .gw d'au moins ``min_bytes`` octets. Retourne la taille réelle."""
    parts: list[str] = []
    size = 0
    i = 0
    while size < min_bytes:
        block = _gw_chunk_template(i)
        parts.append(block)
        size += len(block.encode("utf-8"))
        i += 1
    path.write_text("".join(parts), encoding="utf-8")
    return path.stat().st_size


@pytest.mark.performance
def test_streaming_vs_multipass_on_large_file(tmp_path: Path) -> None:
    """Les deux modes parsent un même gros fichier avec des effectifs identiques."""
    gw_path = tmp_path / "large.gw"
    nbytes = _write_large_gw_file(gw_path)
    assert nbytes > 1_000_000, "le jeu de test doit dépasser 1 Mo"

    parser_stream = GeneWebParser(validate=False, stream_mode=True)
    t0 = time.perf_counter()
    g_stream = parser_stream.parse_file(gw_path)
    t_stream = time.perf_counter() - t0

    parser_mp = GeneWebParser(validate=False, stream_mode=False, use_multipass=True)
    t1 = time.perf_counter()
    g_mp = parser_mp.parse_file(gw_path)
    t_mp = time.perf_counter() - t1

    assert len(g_stream.persons) == len(g_mp.persons)
    assert len(g_stream.families) == len(g_mp.families)
    assert len(g_stream.persons) > 0

    # Journal minimal (pas d'assert sur le ratio temps : trop variable)
    print(
        f"\n[perf] fichier={nbytes // 1024} KiB streaming={t_stream:.3f}s "
        f"multipass={t_mp:.3f}s personnes={len(g_mp.persons)}"
    )
