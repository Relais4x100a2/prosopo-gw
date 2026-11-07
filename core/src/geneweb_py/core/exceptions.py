"""
Exceptions spécifiques pour la librairie geneweb-py

Ce module définit les exceptions personnalisées utilisées dans toute la librairie
pour une gestion d'erreur claire et spécifique au format GeneWeb.
"""

from enum import Enum
from typing import Any


class ErrorSeverity(Enum):
    """Sévérité d'une erreur ou d'un avertissement"""

    WARNING = "warning"  # Avertissement - le parsing peut continuer
    ERROR = "error"  # Erreur - le parsing peut continuer en mode gracieux
    CRITICAL = "critical"  # Erreur critique - le parsing doit s'arrêter


class GeneWebError(Exception):
    """Exception de base pour toutes les erreurs GeneWeb"""

    def __init__(
        self,
        message: str,
        line_number: int | None = None,
        context: str | None = None,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        **kwargs,
    ) -> None:
        # Attributs communs
        self.message = message
        self.line_number = line_number
        self.context = context
        self.severity = severity

        # Rendez accessibles tous les kwargs supplémentaires afin de
        # permettre aux tests dʼaccéder directement aux attributs ajoutés.
        for key, value in kwargs.items():
            setattr(self, key, value)

        super().__init__(self._format_message())

    def _format_message(self) -> str:
        """Formate le message d'erreur avec le numéro de ligne et le contexte si disponibles"""  # noqa: E501
        parts = []

        # Préfixe de ligne
        if self.line_number is not None:
            parts.append(f"Ligne {self.line_number}")

        # Message principal
        msg = f"{self.message}"
        if parts:
            msg = f"{': '.join(parts)}: {self.message}"

        # Contexte additionnel
        if self.context:
            msg += f"\n  Contexte: {self.context}"

        return msg

    def to_dict(self) -> dict[str, Any]:
        """Convertit l'erreur en dictionnaire pour sérialisation"""
        return {
            "type": self.__class__.__name__,
            "message": self.message,
            "line_number": self.line_number,
            "context": self.context,
            "severity": self.severity.value,
        }


class GeneWebParseError(GeneWebError):
    """Erreur lors du parsing d'un fichier .gw"""

    def __init__(
        self,
        message: str,
        line_number: int | None = None,
        token: str | None = None,
        expected: str | None = None,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        **kwargs,
    ):
        # Attributs spécifiques
        self.token = token
        self.expected = expected

        # Propager vers la classe de base tout en conservant kwargs afin qu'ils
        # restent accessibles en tant qu'attributs.
        super().__init__(
            message,
            line_number=line_number,
            severity=severity,
            token=token,
            expected=expected,
            **kwargs,
        )

    def _format_message(self) -> str:
        """Message enrichi avec token et expected si disponibles"""
        parts = []

        if self.line_number is not None:
            parts.append(f"Ligne {self.line_number}")

        msg = self.message

        if self.token:
            msg += f"\n  Token trouvé: '{self.token}'"

        if self.expected:
            msg += f"\n  Attendu: {self.expected}"

        if parts:
            msg = f"{': '.join(parts)}: {msg}"

        if self.context:
            msg += f"\n  Contexte: {self.context}"

        return msg

    def to_dict(self) -> dict[str, Any]:
        """Convertit l'erreur en dictionnaire pour sérialisation"""
        result = super().to_dict()
        result.update(
            {
                "token": self.token,
                "expected": self.expected,
            }
        )
        return result


class ParseWarning(GeneWebError):
    """Avertissement de parsing - non critique, le parsing peut continuer

    Utilisé pour signaler des problèmes mineurs qui n'empêchent pas le parsing,
    comme des données manquantes non essentielles ou des formats non standard.
    """

    def __init__(
        self,
        message: str,
        line_number: int | None = None,
        context: str | None = None,
        **kwargs,
    ):
        super().__init__(
            message,
            line_number=line_number,
            context=context,
            severity=ErrorSeverity.WARNING,
            **kwargs,
        )


class GeneWebValidationError(GeneWebError):
    """Erreur de validation des données généalogiques

    Cette exception est levée quand les données parsées ne respectent pas
    les règles de cohérence généalogique.
    """

    def __init__(
        self,
        message: str,
        line_number: int | None = None,
        field: str | None = None,
        value: Any | None = None,
        context: str | None = None,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        **kwargs,
    ):
        # Garantir l'existence des attributs attendus par _format_message
        self.field = field
        self.value = value
        self.entity_type = kwargs.get("entity_type", None)
        self.entity_id = kwargs.get("entity_id", None)
        self.person_id = kwargs.get("person_id", None)
        self.validation_errors = kwargs.get("validation_errors", []) or []
        self.context = context
        # Filtrer les kwargs déjà consommés pour éviter les doublons
        filtered_kwargs = {
            k: v
            for k, v in kwargs.items()
            if k
            not in {
                "entity_type",
                "entity_id",
                "person_id",
                "validation_errors",
                "field",
                "value",
                "context",
                "severity",
            }
        }
        super().__init__(
            message,
            line_number=line_number,
            context=context,
            severity=severity,
            **filtered_kwargs,
        )

    def _format_message(self) -> str:
        """Message enrichi avec informations de validation"""
        parts = []

        if self.line_number is not None:
            parts.append(f"Ligne {self.line_number}")

        msg = self.message

        if self.entity_type and self.entity_id:
            msg += f"\n  Entité: {self.entity_type} '{self.entity_id}'"

        if self.field:
            msg += f"\n  Champ: {self.field}"

        if self.value is not None:
            msg += f"\n  Valeur: {self.value}"

        if parts:
            msg = f"{': '.join(parts)}: {msg}"

        if self.context:
            msg += f"\n  Contexte: {self.context}"

        return msg

    def to_dict(self) -> dict[str, Any]:
        """Convertit l'erreur en dictionnaire pour sérialisation"""
        result = super().to_dict()
        result.update(
            {
                "field": self.field,
                "value": self.value,
                "entity_type": self.entity_type,
                "entity_id": self.entity_id,
            }
        )
        return result


class UnsupportedCalendarError(GeneWebError):
    """Calendrier non pris en charge pour le calcul de bornes grégoriennes"""


class GeneWebConversionError(GeneWebError):
    """Erreur lors de la conversion vers un autre format"""

    def __init__(
        self,
        message: str,
        source_format: str | None = None,
        target_format: str | None = None,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        **kwargs,
    ):
        self.source_format = source_format
        self.target_format = target_format
        super().__init__(
            message,
            severity=severity,
            source_format=source_format,
            target_format=target_format,
            **kwargs,
        )

    def _format_message(self) -> str:
        """Message enrichi avec informations de conversion"""
        parts = []

        if self.line_number is not None:
            parts.append(f"Ligne {self.line_number}")

        msg = self.message

        if self.source_format:
            msg += f"\n  Format source: {self.source_format}"

        if self.target_format:
            msg += f"\n  Format cible: {self.target_format}"

        if parts:
            msg = f"{': '.join(parts)}: {msg}"

        if self.context:
            msg += f"\n  Contexte: {self.context}"

        return msg

    def to_dict(self) -> dict[str, Any]:
        """Convertit l'erreur en dictionnaire pour sérialisation"""
        result = super().to_dict()
        result.update(
            {
                "source_format": self.source_format,
                "target_format": self.target_format,
            }
        )
        return result


class GeneWebEncodingError(GeneWebError):
    """Erreur d'encodage lors de la lecture d'un fichier .gw"""

    def __init__(
        self,
        message: str,
        encoding: str | None = None,
        detected_encoding: str | None = None,
        attempted_encoding: str | None = None,
        byte_position: int | None = None,
        invalid_byte: bytes | None = None,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        **kwargs,
    ):
        # Initialiser tous les attributs référencés par _format_message
        self.encoding = encoding
        self.detected_encoding = detected_encoding
        self.attempted_encoding = attempted_encoding
        self.byte_position = byte_position
        self.invalid_byte = invalid_byte
        super().__init__(
            message,
            severity=severity,
            encoding=encoding,
            detected_encoding=detected_encoding,
            attempted_encoding=attempted_encoding,
            byte_position=byte_position,
            invalid_byte=invalid_byte,
            **kwargs,
        )

    def _format_message(self) -> str:
        """Message enrichi avec informations d'encodage"""
        parts = []

        if self.line_number is not None:
            parts.append(f"Ligne {self.line_number}")

        msg = self.message

        if self.detected_encoding:
            msg += f"\n  Encodage détecté: {self.detected_encoding}"

        if self.attempted_encoding:
            msg += f"\n  Encodage tenté: {self.attempted_encoding}"

        if self.byte_position is not None:
            msg += f"\n  Position: byte {self.byte_position}"

        if self.invalid_byte:
            msg += f"\n  Byte invalide: {self.invalid_byte!r}"

        if parts:
            msg = f"{': '.join(parts)}: {msg}"

        if self.context:
            msg += f"\n  Contexte: {self.context}"

        return msg

    def to_dict(self) -> dict[str, Any]:
        """Convertit l'erreur en dictionnaire pour sérialisation"""
        result = super().to_dict()
        result.update(
            {
                "encoding": self.encoding,
                "detected_encoding": self.detected_encoding,
                "attempted_encoding": self.attempted_encoding,
                "byte_position": self.byte_position,
                "invalid_byte": str(self.invalid_byte) if self.invalid_byte else None,
            }
        )
        return result


class GeneWebErrorCollector:
    """Collecteur d'erreurs pour validation gracieuse

    Permet d'accumuler plusieurs erreurs au lieu de lever une exception
    au premier problème rencontré. Supporte le filtrage par type et par sévérité.
    """

    def __init__(self, strict: bool = False) -> None:
        """Initialise le collecteur

        Args:
            strict: Si True, les erreurs ERROR ou CRITICAL lèvent une exception.
        """
        self.errors: list[GeneWebError] = []
        self.strict = strict

    def add_error(self, error: GeneWebError) -> None:
        """Ajoute une erreur au collecteur

        Args:
            error: L'erreur à ajouter

        Raises:
            GeneWebError: Si en mode strict et que l'erreur est ERROR ou CRITICAL
        """
        self.errors.append(error)

        # En mode strict, lever l'exception pour les erreurs non-warning
        if self.strict and error.severity != ErrorSeverity.WARNING:
            raise error

    def add_warning(
        self,
        message: str,
        line_number: int | None = None,
        context: str | None = None,
        **kwargs,
    ) -> None:
        """Ajoute un avertissement (raccourci pratique)"""
        self.add_error(
            ParseWarning(message, line_number=line_number, context=context, **kwargs)
        )

    def has_errors(self, severity: ErrorSeverity | None = None) -> bool:
        """Retourne True si des erreurs ont été collectées

        Args:
            severity: Si spécifié, vérifie uniquement cette sévérité
        """
        if severity is None:
            return len(self.errors) > 0
        return any(e.severity == severity for e in self.errors)

    def has_warnings(self) -> bool:
        """Retourne True si des avertissements ont été collectés"""
        return self.has_errors(ErrorSeverity.WARNING)

    def has_critical_errors(self) -> bool:
        """Retourne True si des erreurs critiques ont été collectées"""
        return self.has_errors(ErrorSeverity.CRITICAL)

    def get_errors(
        self,
        error_type: type | None = None,
        severity: ErrorSeverity | None = None,
    ) -> list[GeneWebError]:
        """Retourne les erreurs, optionnellement filtrées par type et/ou sévérité

        Args:
            error_type: Type d'erreur à filtrer (ex: GeneWebParseError)
            severity: Sévérité à filtrer (ex: ErrorSeverity.WARNING)
        """
        result = self.errors.copy()

        if error_type is not None:
            result = [e for e in result if isinstance(e, error_type)]

        if severity is not None:
            result = [e for e in result if e.severity == severity]

        return result

    def get_warnings(self) -> list[GeneWebError]:
        """Retourne uniquement les avertissements"""
        return self.get_errors(severity=ErrorSeverity.WARNING)

    def get_critical_errors(self) -> list[GeneWebError]:
        """Retourne uniquement les erreurs critiques"""
        return self.get_errors(severity=ErrorSeverity.CRITICAL)

    def clear_errors(self) -> None:
        """Supprime toutes les erreurs"""
        self.errors.clear()

    def error_count(self, severity: ErrorSeverity | None = None) -> int:
        """Retourne le nombre d'erreurs

        Args:
            severity: Si spécifié, compte uniquement cette sévérité
        """
        if severity is None:
            return len(self.errors)
        return len(self.get_errors(severity=severity))

    def get_error_summary(self) -> str:
        """Retourne un résumé des erreurs avec détails par sévérité"""
        if not self.errors:
            return "Aucune erreur"

        # Compter par sévérité
        by_severity = {
            ErrorSeverity.WARNING: 0,
            ErrorSeverity.ERROR: 0,
            ErrorSeverity.CRITICAL: 0,
        }

        for error in self.errors:
            by_severity[error.severity] += 1

        # Construire le résumé
        parts = []
        if by_severity[ErrorSeverity.WARNING] > 0:
            parts.append(f"{by_severity[ErrorSeverity.WARNING]} avertissement(s)")
        if by_severity[ErrorSeverity.ERROR] > 0:
            parts.append(f"{by_severity[ErrorSeverity.ERROR]} erreur(s)")
        if by_severity[ErrorSeverity.CRITICAL] > 0:
            parts.append(f"{by_severity[ErrorSeverity.CRITICAL]} erreur(s) critique(s)")

        return ", ".join(parts)

    def get_detailed_report(self) -> str:
        """Retourne un rapport détaillé de toutes les erreurs"""
        if not self.errors:
            return "Aucune erreur détectée"

        lines = [f"=== Rapport d'erreurs ({len(self.errors)} total) ===\n"]

        # Grouper par sévérité
        for severity in [
            ErrorSeverity.CRITICAL,
            ErrorSeverity.ERROR,
            ErrorSeverity.WARNING,
        ]:
            errors_of_type = self.get_errors(severity=severity)
            if errors_of_type:
                lines.append(f"\n{severity.value.upper()} ({len(errors_of_type)}):")
                for i, error in enumerate(errors_of_type, 1):
                    lines.append(f"  {i}. {error}")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Convertit le collecteur en dictionnaire pour sérialisation"""
        return {
            "error_count": len(self.errors),
            "warning_count": self.error_count(ErrorSeverity.WARNING),
            "error_count_by_severity": self.error_count(ErrorSeverity.ERROR),
            "critical_count": self.error_count(ErrorSeverity.CRITICAL),
            "errors": [e.to_dict() for e in self.errors],
            "summary": self.get_error_summary(),
        }

    def __enter__(self):
        """Support du contexte manager"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Support du contexte manager - lève les erreurs critiques"""
        if self.has_critical_errors():
            critical = self.get_critical_errors()[0]
            raise critical
        return False  # Ne pas supprimer les exceptions externes

    def __len__(self) -> int:
        """Retourne le nombre d'erreurs"""
        return len(self.errors)

    def __str__(self) -> str:
        """Représentation string du collecteur"""
        return f"GeneWebErrorCollector({self.get_error_summary()})"

    def __repr__(self) -> str:
        """Représentation pour debug"""
        return f"GeneWebErrorCollector(errors={len(self.errors)}, strict={self.strict})"


class ValidationResult:
    """Résultat de validation avec erreurs et avertissements.

    Distingue erreurs (échec) et avertissements (succès avec remarques).
    """

    def __init__(self) -> None:
        self.errors: list[GeneWebError] = []
        self.warnings: list[GeneWebError] = []

    def add_error(self, error: GeneWebError) -> None:
        """Ajoute une erreur ou un avertissement au résultat"""
        if error.severity == ErrorSeverity.WARNING:
            self.warnings.append(error)
        else:
            self.errors.append(error)

    def add_errors_from_collector(self, collector: GeneWebErrorCollector) -> None:
        """Ajoute toutes les erreurs d'un collecteur"""
        for error in collector.get_errors():
            self.add_error(error)

    def is_valid(self) -> bool:
        """Retourne True si la validation est réussie (pas d'erreurs, warnings OK)"""
        return len(self.errors) == 0

    def has_errors(self) -> bool:
        """Retourne True si des erreurs ont été trouvées"""
        return len(self.errors) > 0

    def has_warnings(self) -> bool:
        """Retourne True si des avertissements ont été trouvés"""
        return len(self.warnings) > 0

    def get_all_issues(self) -> list[GeneWebError]:
        """Retourne toutes les erreurs et avertissements"""
        return self.errors + self.warnings

    def get_error_messages(self) -> list[str]:
        """Retourne la liste des messages d'erreur"""
        return [str(error) for error in self.errors]

    def get_warning_messages(self) -> list[str]:
        """Retourne la liste des messages d'avertissement"""
        return [str(warning) for warning in self.warnings]

    def get_all_messages(self) -> list[str]:
        """Retourne tous les messages (erreurs et avertissements)"""
        return self.get_error_messages() + self.get_warning_messages()

    def get_summary(self) -> str:
        """Retourne un résumé de la validation"""
        if self.is_valid():
            if self.has_warnings():
                return f"Validation réussie avec {len(self.warnings)} avertissement(s)"
            return "Validation réussie"
        else:
            parts = [f"{len(self.errors)} erreur(s)"]
            if self.has_warnings():
                parts.append(f"{len(self.warnings)} avertissement(s)")
            return f"Validation échouée: {', '.join(parts)}"

    def to_dict(self) -> dict[str, Any]:
        """Convertit le résultat en dictionnaire pour sérialisation"""
        return {
            "is_valid": self.is_valid(),
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
            "summary": self.get_summary(),
        }

    def __str__(self) -> str:
        """Représentation string du résultat"""
        return self.get_summary()

    def __repr__(self) -> str:
        """Représentation pour debug"""
        return f"ValidationResult(errors={len(self.errors)}, warnings={len(self.warnings)})"  # noqa: E501
