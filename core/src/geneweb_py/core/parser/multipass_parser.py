"""
Parser multi-passes pour fichiers GeneWeb complexes.

Ce module complète le pipeline lexical → syntaxique en appliquant une passe
supplémentaire de consolidation des références croisées après que toutes les
personnes aient été fusionnées dans le conteneur ``Genealogy``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import Genealogy
from .syntax import SyntaxNode

if TYPE_CHECKING:
    from .gw_parser import GeneWebParser


class MultiPassParser:
    """Construit une :class:`Genealogy` avec une passe de références croisées renforcée.

    Le mode multi-passes réutilise la construction incrémentale du
    :class:`GeneWebParser`, puis applique une mise à jour supplémentaire des
    liens personnes ↔ familles une fois toutes les personnes du fichier
    intégrées (y compris témoins et blocs secondaires).

    Attributes:
        content: Texte source .gw optionnel (réservé au diagnostic ou extensions).
    """

    def __init__(
        self,
        content: str | None = None,
        gene_web_parser: GeneWebParser | None = None,
    ) -> None:
        """Initialise le parser multi-passes.

        Args:
            content: Contenu brut du fichier (optionnel).
            gene_web_parser: Parser principal déjà configuré (validate, strict, etc.).
        """
        self.content = content
        self._gene_web_parser = gene_web_parser

    def parse_syntax_nodes(self, syntax_nodes: list[SyntaxNode]) -> Genealogy:
        """Interprète les nœuds syntaxiques et retourne une généalogie complète.

        Args:
            syntax_nodes: Liste produite par :class:`SyntaxParser`.

        Returns:
            Objet :class:`Genealogy` peuplé.

        Raises:
            ValueError: Si aucun ``gene_web_parser`` n'a été fourni à la construction.
        """
        if self._gene_web_parser is None:
            raise ValueError(
                "gene_web_parser est requis pour interpréter les nœuds syntaxiques"
            )
        return self._gene_web_parser._build_genealogy_incremental(
            syntax_nodes,
            second_cross_ref_pass=True,
        )
