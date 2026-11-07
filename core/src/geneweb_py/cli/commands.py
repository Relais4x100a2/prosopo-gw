"""
Commandes Click pour le binaire ``geneweb-py``.

Les erreurs utilisateur sont affichées sur stderr via Rich (panneaux).
"""

from pathlib import Path
from typing import Any

import click
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from geneweb_py import __version__
from geneweb_py.core.exceptions import GeneWebEncodingError, GeneWebParseError
from geneweb_py.core.genealogy import Genealogy
from geneweb_py.core.parser import GeneWebParser
from geneweb_py.formats import (
    ConversionError,
    GEDCOMExporter,
    JSONExporter,
    XMLExporter,
)

_stderr = Console(stderr=True)
_stdout = Console()


def _emit_error_panel(title: str, detail: str) -> None:
    """Affiche un message d'erreur formaté avec Rich."""
    _stderr.print(
        Panel(
            detail,
            title=title,
            border_style="red",
            title_align="left",
        )
    )


def _parse_genealogy(gw_path: Path) -> Genealogy:
    """Parse un fichier ``.gw`` / ``.gwplus`` et propage les erreurs métier."""
    parser = GeneWebParser()
    return parser.parse_file(gw_path)


def _render_parse_summary(genealogy: Genealogy, source: Path) -> None:
    """Affiche un résumé lisible du fichier parsé."""
    meta = genealogy.metadata
    stats = genealogy.get_statistics()

    table = Table(
        title=f"Résumé — {source}",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold",
    )
    table.add_column("Indicateur", style="cyan", no_wrap=True)
    table.add_column("Valeur")

    rows: list[tuple[str, str]] = [
        ("Fichier source", str(source)),
        ("Encodage détecté", meta.encoding),
        ("Format gwplus", "oui" if meta.is_gwplus else "non"),
        ("Valide (validation)", "oui" if genealogy.is_valid else "non"),
        ("Personnes", str(stats.get("total_persons", 0))),
        ("Familles", str(stats.get("total_families", 0))),
        ("Enfants (liens)", str(stats.get("total_children", 0))),
    ]
    if genealogy.validation_errors:
        rows.append(
            (
                "Avertissements / erreurs",
                str(len(genealogy.validation_errors)),
            )
        )

    for label, value in rows:
        table.add_row(label, value)

    _stdout.print(table)


def _get_exporter(export_format: str) -> tuple[Any, str]:
    """Retourne une instance d'exporteur et une étiquette de format."""
    mapping: dict[str, tuple[Any, str]] = {
        "gedcom": (GEDCOMExporter(), "GEDCOM"),
        "json": (JSONExporter(), "JSON"),
        "xml": (XMLExporter(), "XML"),
    }
    return mapping[export_format.lower()]


@click.group(
    context_settings={
        "help_option_names": ["-h", "--help"],
    }
)
@click.version_option(version=__version__, prog_name="geneweb-py")
def cli() -> None:
    """Outils CLI : parser et exporter des fichiers GeneWeb (.gw / .gwplus)."""


@cli.command("parse")
@click.argument(
    "gw_file",
    type=click.Path(
        exists=True,
        dir_okay=False,
        readable=True,
        path_type=Path,
    ),
)
def parse_command(gw_file: Path) -> None:
    """Affiche un résumé après parsing d'un fichier .gw ou .gwplus."""
    try:
        genealogy = _parse_genealogy(gw_file)
    except GeneWebEncodingError as exc:
        _emit_error_panel("Erreur d'encodage", str(exc))
        raise SystemExit(1) from exc
    except GeneWebParseError as exc:
        _emit_error_panel("Erreur de parsing", str(exc))
        raise SystemExit(1) from exc
    except Exception as exc:  # noqa: BLE001 — filet de sécurité CLI
        _stderr.print_exception(show_locals=False)
        raise SystemExit(1) from exc

    _render_parse_summary(genealogy, gw_file)


@cli.command("export")
@click.argument(
    "gw_file",
    type=click.Path(
        exists=True,
        dir_okay=False,
        readable=True,
        path_type=Path,
    ),
)
@click.option(
    "--format",
    "export_format",
    type=click.Choice(["gedcom", "json", "xml"], case_sensitive=False),
    required=True,
    help="Format de sortie : gedcom, json ou xml.",
)
@click.option(
    "-o",
    "--output",
    "output_path",
    type=click.Path(path_type=Path),
    required=True,
    help="Chemin du fichier de sortie.",
)
def export_command(
    gw_file: Path,
    export_format: str,
    output_path: Path,
) -> None:
    """Exporte une généalogie .gw vers GEDCOM, JSON ou XML."""
    try:
        genealogy = _parse_genealogy(gw_file)
    except GeneWebEncodingError as exc:
        _emit_error_panel("Erreur d'encodage", str(exc))
        raise SystemExit(1) from exc
    except GeneWebParseError as exc:
        _emit_error_panel("Erreur de parsing", str(exc))
        raise SystemExit(1) from exc
    except Exception as exc:  # noqa: BLE001
        _stderr.print_exception(show_locals=False)
        raise SystemExit(1) from exc

    exporter, label = _get_exporter(export_format)
    try:
        exporter.export(genealogy, output_path)
    except ConversionError as exc:
        _emit_error_panel(f"Erreur d'export {label}", str(exc))
        raise SystemExit(1) from exc
    except OSError as exc:
        _emit_error_panel("Erreur d'écriture", str(exc))
        raise SystemExit(1) from exc
    except Exception as exc:  # noqa: BLE001
        _stderr.print_exception(show_locals=False)
        raise SystemExit(1) from exc

    _stdout.print(
        Panel(
            f"[green]Export {label} réussi vers[/green] [bold]{output_path}[/bold]",
            border_style="green",
            title="OK",
            title_align="left",
        )
    )
