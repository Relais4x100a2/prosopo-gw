"""
Classes de base pour les convertisseurs de formats.

Ce module définit les interfaces communes pour tous les exporteurs et importeurs
de formats généalogiques.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..core.exceptions import GeneWebConversionError
from ..core.genealogy import Genealogy


class ConversionError(GeneWebConversionError):
    """Exception levée lors d'erreurs de conversion de formats."""

    def __init__(self, message: str, details: dict[str, Any] | None = None, **kwargs):
        """
        Initialise l'erreur de conversion.

        Args:
            message: Message d'erreur
            details: Détails supplémentaires de l'erreur
            **kwargs: Arguments supplémentaires pour la classe parente
        """
        super().__init__(message, **kwargs)
        self.details = details or {}


class BaseExporter(ABC):
    """Classe de base pour tous les exporteurs de formats."""

    def __init__(self, encoding: str = "utf-8"):
        """
        Initialise l'exporteur.

        Args:
            encoding: Encodage à utiliser pour l'export (défaut: utf-8)
        """
        self.encoding = encoding

    @abstractmethod
    def export(self, genealogy: Genealogy, output_path: str | Path) -> None:
        """
        Exporte une généalogie vers un fichier.

        Args:
            genealogy: Objet Genealogy à exporter
            output_path: Chemin du fichier de sortie

        Raises:
            ConversionError: En cas d'erreur de conversion
        """
        pass

    @abstractmethod
    def export_to_string(self, genealogy: Genealogy) -> str:
        """
        Exporte une généalogie vers une chaîne de caractères.

        Args:
            genealogy: Objet Genealogy à exporter

        Returns:
            Chaîne de caractères contenant les données exportées

        Raises:
            ConversionError: En cas d'erreur de conversion
        """
        pass

    def _validate_genealogy(self, genealogy: Genealogy) -> None:
        """
        Valide qu'un objet Genealogy est valide pour l'export.

        Args:
            genealogy: Objet Genealogy à valider

        Raises:
            ConversionError: Si la généalogie n'est pas valide
        """
        if not isinstance(genealogy, Genealogy):
            raise ConversionError("L'objet fourni n'est pas une instance de Genealogy")

        if not genealogy.persons and not genealogy.families:
            raise ConversionError("La généalogie est vide (aucune personne ni famille)")


class BaseImporter(ABC):
    """Classe de base pour tous les importeurs de formats."""

    def __init__(self, encoding: str = "utf-8"):
        """
        Initialise l'importeur.

        Args:
            encoding: Encodage à utiliser pour l'import (défaut: utf-8)
        """
        self.encoding = encoding

    @abstractmethod
    def import_from_file(self, input_path: str | Path) -> Genealogy:
        """
        Importe une généalogie depuis un fichier.

        Args:
            input_path: Chemin du fichier à importer

        Returns:
            Objet Genealogy importé

        Raises:
            ConversionError: En cas d'erreur de conversion
        """
        pass

    @abstractmethod
    def import_from_string(self, data: str) -> Genealogy:
        """
        Importe une généalogie depuis une chaîne de caractères.

        Args:
            data: Chaîne de caractères contenant les données à importer

        Returns:
            Objet Genealogy importé

        Raises:
            ConversionError: En cas d'erreur de conversion
        """
        pass

    def _validate_file_path(self, input_path: str | Path) -> Path:
        """
        Valide qu'un chemin de fichier est valide.

        Args:
            input_path: Chemin à valider

        Returns:
            Objet Path validé

        Raises:
            ConversionError: Si le chemin n'est pas valide
        """
        path = Path(input_path)

        if not path.exists():
            raise ConversionError(f"Le fichier n'existe pas : {path}")

        if not path.is_file():
            raise ConversionError(f"Le chemin n'est pas un fichier : {path}")

        return path
