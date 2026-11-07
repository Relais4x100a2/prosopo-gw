"""
Benchmarks de performance pour le parser GeneWeb

Ce module mesure les performances du parser sur différentes tailles de fichiers
et compare les modes normal et streaming.
"""

import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any

# Imports du projet doivent être après manipulation de sys.path
# Ajouter le chemin du projet (structure src/)
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

# ruff: noqa: E402
from geneweb_py.core.parser.gw_parser import GeneWebParser
from geneweb_py.core.parser.streaming import estimate_memory_usage, should_use_streaming


def generate_test_file(size_kb: int) -> str:
    """Génère un fichier de test .gw de taille approximative

    Args:
        size_kb: Taille approximative en KB

    Returns:
        Contenu du fichier
    """
    # Taille approximative d'une famille avec 3 enfants: ~500 bytes
    family_template = (
        "fam Dupont Jean 15/03/1950 #bp Paris #occu Ingénieur "
        "10/02/2020 #dp Lyon + Durand Marie 20/05/1952 #bp Marseille\n"
        """beg
- h Dupont Pierre 10/01/1975 #bp Paris #occu Médecin
- f Dupont Sophie 15/06/1978 #bp Lyon #occu Professeur
- h Dupont Paul 22/09/1982 #bp Nice
end

"""
    )

    num_families = (size_kb * 1024) // len(family_template.encode("utf-8"))
    content_parts = []

    for i in range(num_families):
        # Varier les noms pour éviter les collisions
        family = family_template.replace("Dupont", f"Famille{i:05d}")
        content_parts.append(family)

    return "".join(content_parts)


def benchmark_parsing(
    content: str, mode: str = "normal", validate: bool = True
) -> dict[str, Any]:
    """Benchmark le parsing d'un contenu

    Args:
        content: Contenu à parser
        mode: "normal" ou "streaming"
        validate: Si True, valide la cohérence

    Returns:
        Dictionnaire avec les métriques
    """
    # Démarrer le suivi mémoire
    tracemalloc.start()

    # Mesurer le temps
    start_time = time.perf_counter()

    # Parser
    if mode == "streaming":
        parser = GeneWebParser(validate=validate, stream_mode=True)
    else:
        parser = GeneWebParser(validate=validate, stream_mode=False)

    try:
        genealogy = parser.parse_string(content)
        success = True
        error = None
    except Exception as e:
        success = False
        error = str(e)
        genealogy = None

    # Mesurer le temps écoulé
    elapsed_time = time.perf_counter() - start_time

    # Mesurer la mémoire utilisée
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # Collecter les statistiques
    stats = {
        "mode": mode,
        "success": success,
        "error": error,
        "time_seconds": round(elapsed_time, 3),
        "memory_current_mb": round(current / 1024 / 1024, 2),
        "memory_peak_mb": round(peak / 1024 / 1024, 2),
        "num_persons": len(genealogy.persons) if genealogy else 0,
        "num_families": len(genealogy.families) if genealogy else 0,
    }

    return stats


def run_benchmark_suite():
    """Exécute une suite complète de benchmarks"""

    print("=" * 80)
    print("BENCHMARKS DE PERFORMANCE - Parser GeneWeb".center(80))
    print("=" * 80)
    print()

    # Tailles de fichiers à tester
    test_sizes = [
        ("1KB", 1),
        ("10KB", 10),
        ("100KB", 100),
        ("1MB", 1024),
        ("5MB", 5 * 1024),
        ("10MB", 10 * 1024),
    ]

    results = []

    for size_name, size_kb in test_sizes:
        print(f"\n{'─' * 80}")
        print(f"Test: {size_name} ({size_kb} KB)")
        print(f"{'─' * 80}")

        # Générer le fichier de test
        print("  Génération du fichier de test...", end="")
        content = generate_test_file(size_kb)
        actual_size_kb = len(content.encode("utf-8")) / 1024
        print(f" OK ({actual_size_kb:.1f} KB)")

        # Test en mode normal
        print("  Parsing en mode NORMAL...", end="")
        sys.stdout.flush()
        try:
            stats_normal = benchmark_parsing(content, mode="normal", validate=False)
            print(" OK")
            print(f"    Temps: {stats_normal['time_seconds']}s")
            print(f"    Mémoire pic: {stats_normal['memory_peak_mb']} MB")
            print(f"    Personnes: {stats_normal['num_persons']}")
        except Exception as e:
            print(f" ERREUR: {e}")
            stats_normal = None

        # Test en mode streaming (seulement pour les gros fichiers)
        if size_kb >= 1024:
            print("  Parsing en mode STREAMING...", end="")
            sys.stdout.flush()
            try:
                stats_streaming = benchmark_parsing(
                    content, mode="streaming", validate=False
                )
                print(" OK")
                print(f"    Temps: {stats_streaming['time_seconds']}s")
                print(f"    Mémoire pic: {stats_streaming['memory_peak_mb']} MB")
                print(f"    Personnes: {stats_streaming['num_persons']}")

                # Calculer les gains
                if stats_normal:
                    time_ratio = (
                        stats_normal["time_seconds"] / stats_streaming["time_seconds"]
                    )
                    memory_ratio = (
                        stats_normal["memory_peak_mb"]
                        / stats_streaming["memory_peak_mb"]
                    )
                    print(f"    Gain temps: {time_ratio:.2f}x")
                    print(f"    Gain mémoire: {memory_ratio:.2f}x")
            except Exception as e:
                print(f" ERREUR: {e}")
                stats_streaming = None
        else:
            stats_streaming = None

        results.append(
            {
                "size_name": size_name,
                "size_kb": actual_size_kb,
                "normal": stats_normal,
                "streaming": stats_streaming,
            }
        )

    # Résumé des résultats
    print(f"\n\n{'═' * 80}")
    print("RÉSUMÉ DES RÉSULTATS".center(80))
    print(f"{'═' * 80}\n")

    print(
        f"{'Taille':<10} {'Mode':<12} {'Temps (s)':<12} {'Mémoire (MB)':<15} {'Personnes':<12}"  # noqa: E501
    )
    print(f"{'─' * 10} {'─' * 12} {'─' * 12} {'─' * 15} {'─' * 12}")

    for result in results:
        size_name = result["size_name"]

        if result["normal"]:
            stats = result["normal"]
            print(
                f"{size_name:<10} {'Normal':<12} "
                f"{stats['time_seconds']:<12.3f} "
                f"{stats['memory_peak_mb']:<15.2f} "
                f"{stats['num_persons']:<12}"
            )

        if result["streaming"]:
            stats = result["streaming"]
            print(
                f"{'':<10} {'Streaming':<12} "
                f"{stats['time_seconds']:<12.3f} "
                f"{stats['memory_peak_mb']:<15.2f} "
                f"{stats['num_persons']:<12}"
            )

            # Calculer les gains
            if result["normal"]:
                time_gain = (
                    1 - stats["time_seconds"] / result["normal"]["time_seconds"]
                ) * 100
                memory_gain = (
                    1 - stats["memory_peak_mb"] / result["normal"]["memory_peak_mb"]
                ) * 100
                print(
                    f"{'':<10} {'Gain (%)':<12} {time_gain:<12.1f} {memory_gain:<15.1f}"
                )

    print(f"\n{'═' * 80}\n")

    # Recommandations
    print("RECOMMANDATIONS:")
    print("  - Fichiers < 10MB: Mode normal (plus simple, performances équivalentes)")
    print("  - Fichiers > 10MB: Mode streaming (économie mémoire significative)")
    print("  - Le mode streaming est automatiquement activé pour les fichiers > 10MB")
    print()


def benchmark_real_file(file_path: str):
    """Benchmark sur un fichier réel

    Args:
        file_path: Chemin vers le fichier .gw
    """
    from pathlib import Path

    file_path = Path(file_path)

    if not file_path.exists():
        print(f"Erreur: Fichier non trouvé: {file_path}")
        return

    print(f"\n{'═' * 80}")
    print(f"BENCHMARK SUR FICHIER RÉEL: {file_path.name}".center(80))
    print(f"{'═' * 80}\n")

    # Informations sur le fichier
    size_mb = file_path.stat().st_size / (1024 * 1024)
    print(f"Taille du fichier: {size_mb:.2f} MB")

    # Estimation mémoire
    memory_est = estimate_memory_usage(file_path)
    print("\nEstimations mémoire:")
    print(f"  Mode normal: {memory_est['estimated_normal_memory_mb']:.2f} MB")
    print(f"  Mode streaming: {memory_est['estimated_streaming_memory_mb']:.2f} MB")
    print(f"  Économie: {memory_est['memory_saving_percent']:.1f}%")
    print(f"  Mode recommandé: {memory_est['recommended_mode']}")

    # Lire le fichier
    print("\nLecture du fichier...", end="")
    with open(file_path, encoding="utf-8", errors="replace") as f:
        content = f.read()
    print(" OK")

    # Test en mode normal
    print("\nParsing en mode NORMAL...")
    stats_normal = benchmark_parsing(content, mode="normal", validate=False)
    print(f"  Temps: {stats_normal['time_seconds']}s")
    print(f"  Mémoire pic: {stats_normal['memory_peak_mb']} MB")
    print(f"  Personnes: {stats_normal['num_persons']}")
    print(f"  Familles: {stats_normal['num_families']}")

    # Test en mode streaming si recommandé
    if should_use_streaming(file_path):
        print("\nParsing en mode STREAMING...")
        stats_streaming = benchmark_parsing(content, mode="streaming", validate=False)
        print(f"  Temps: {stats_streaming['time_seconds']}s")
        print(f"  Mémoire pic: {stats_streaming['memory_peak_mb']} MB")
        print(f"  Personnes: {stats_streaming['num_persons']}")
        print(f"  Familles: {stats_streaming['num_families']}")

        # Gains
        time_gain = (
            1 - stats_streaming["time_seconds"] / stats_normal["time_seconds"]
        ) * 100
        memory_gain = (
            1 - stats_streaming["memory_peak_mb"] / stats_normal["memory_peak_mb"]
        ) * 100

        print("\nGains avec le streaming:")
        print(f"  Temps: {time_gain:+.1f}%")
        print(f"  Mémoire: {memory_gain:+.1f}%")

    print(f"\n{'═' * 80}\n")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # Benchmark sur un fichier spécifique
        benchmark_real_file(sys.argv[1])
    else:
        # Suite complète de benchmarks
        run_benchmark_suite()
