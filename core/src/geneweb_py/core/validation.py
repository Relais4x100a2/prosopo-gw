"""
Module de validation gracieuse pour les données généalogiques

Ce module fournit des outils pour valider les données généalogiques de manière
gracieuse, en collectant toutes les erreurs au lieu de s'arrêter à la première.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .exceptions import (
    ErrorSeverity,
    GeneWebErrorCollector,
    GeneWebValidationError,
    ValidationResult,
)

if TYPE_CHECKING:
    from .family import Family
    from .genealogy import Genealogy
    from .person import Person


@dataclass
class ValidationContext:
    """Contexte de validation avec collecteur d'erreurs

    Permet de passer un collecteur d'erreurs à travers les différentes
    étapes de validation pour accumuler les problèmes détectés.
    """

    error_collector: GeneWebErrorCollector = field(
        default_factory=GeneWebErrorCollector
    )
    strict: bool = False

    def add_error(self, error: Exception) -> None:
        """Ajoute une erreur au contexte"""
        from .exceptions import GeneWebError

        if isinstance(error, GeneWebError):
            self.error_collector.add_error(error)
        else:
            # Convertir en GeneWebValidationError
            self.error_collector.add_error(GeneWebValidationError(str(error)))

    def add_warning(self, message: str, **kwargs) -> None:
        """Ajoute un avertissement au contexte"""
        self.error_collector.add_warning(message, **kwargs)

    def has_errors(self) -> bool:
        """Retourne True si des erreurs ont été collectées"""
        return self.error_collector.has_errors()

    def get_errors(self) -> list[Exception]:
        """Retourne la liste des erreurs collectées"""
        return list(self.error_collector.get_errors())

    def get_result(self) -> ValidationResult:
        """Retourne le résultat de validation"""
        result = ValidationResult()
        result.add_errors_from_collector(self.error_collector)
        return result


def validate_person_basic(
    person: "Person", context: ValidationContext | None = None
) -> ValidationResult:
    """Valide les informations de base d'une personne

    Args:
        person: La personne à valider
        context: Contexte de validation (créé si non fourni)

    Returns:
        Résultat de validation avec erreurs éventuelles
    """
    if context is None:
        context = ValidationContext()

    # Nom et prénom obligatoires
    if not person.last_name or not person.last_name.strip():
        context.add_error(
            GeneWebValidationError(
                "Le nom de famille est obligatoire",
                entity_type="Person",
                entity_id=person.unique_id,
                field="last_name",
                value=person.last_name,
            )
        )

    if not person.first_name or not person.first_name.strip():
        context.add_error(
            GeneWebValidationError(
                "Le prénom est obligatoire",
                entity_type="Person",
                entity_id=person.unique_id,
                field="first_name",
                value=person.first_name,
            )
        )

    # Vérifier la cohérence des dates
    if person.birth_date and person.death_date:
        if person.birth_date.is_after(person.death_date):
            context.add_error(
                GeneWebValidationError(
                    "La date de naissance est postérieure à la date de décès",
                    entity_type="Person",
                    entity_id=person.unique_id,
                    field="birth_date",
                    severity=ErrorSeverity.ERROR,
                )
            )

    # Vérifier la cohérence baptême/naissance
    if person.baptism_date and person.birth_date:
        if person.baptism_date.is_before(person.birth_date):
            context.add_error(
                GeneWebValidationError(
                    "La date de baptême est antérieure à la date de naissance",
                    entity_type="Person",
                    entity_id=person.unique_id,
                    field="baptism_date",
                    severity=ErrorSeverity.ERROR,
                )
            )

    # Avertissement si is_deceased est None mais death_date existe
    if person.death_date and person.is_deceased is None:
        context.add_warning(
            f"Date de décès présente mais is_deceased n'est pas défini pour {person.unique_id}",  # noqa: E501
            context=f"Personne: {person.unique_id}",
        )

    # Avertissement si is_deceased=True mais pas de death_date
    if person.is_deceased is True and not person.death_date:
        context.add_warning(
            f"Personne décédée mais pas de date de décès pour {person.unique_id}",
            context=f"Personne: {person.unique_id}",
        )

    return context.get_result()


def validate_person_relationships(
    person: "Person",
    genealogy: "Genealogy",
    context: ValidationContext | None = None,
) -> ValidationResult:
    """Valide les relations familiales d'une personne

    Args:
        person: La personne à valider
        genealogy: La généalogie contenant toutes les données
        context: Contexte de validation (créé si non fourni)

    Returns:
        Résultat de validation avec erreurs éventuelles
    """
    if context is None:
        context = ValidationContext()

    # Vérifier que les familles référencées existent
    for family_id in person.families_as_spouse:
        if family_id not in genealogy.families:
            context.add_error(
                GeneWebValidationError(
                    f"Famille '{family_id}' référencée comme conjoint non trouvée",
                    entity_type="Person",
                    entity_id=person.unique_id,
                    field="families_as_spouse",
                    value=family_id,
                )
            )

    for family_id in person.families_as_child:
        if family_id not in genealogy.families:
            context.add_error(
                GeneWebValidationError(
                    f"Famille '{family_id}' référencée comme enfant non trouvée",
                    entity_type="Person",
                    entity_id=person.unique_id,
                    field="families_as_child",
                    value=family_id,
                )
            )

    return context.get_result()


def validate_family_basic(
    family: "Family", context: ValidationContext | None = None
) -> ValidationResult:
    """Valide les informations de base d'une famille

    Args:
        family: La famille à valider
        context: Contexte de validation (créé si non fourni)

    Returns:
        Résultat de validation avec erreurs éventuelles
    """
    if context is None:
        context = ValidationContext()

    # Une famille doit avoir au moins un parent ou un enfant
    has_parents = family.husband_id or family.wife_id
    has_children = len(family.children) > 0

    if not has_parents and not has_children:
        context.add_error(
            GeneWebValidationError(
                "Une famille doit avoir au moins un parent ou un enfant",
                entity_type="Family",
                entity_id=family.family_id,
            )
        )

    # Vérifier la cohérence des dates de mariage/divorce
    if family.marriage_date and family.divorce_date:
        if family.marriage_date.is_after(family.divorce_date):
            context.add_error(
                GeneWebValidationError(
                    "La date de mariage est postérieure à la date de divorce",
                    entity_type="Family",
                    entity_id=family.family_id,
                    field="marriage_date",
                )
            )

    # Avertissement si divorce_date sans is_separated
    if family.divorce_date and not family.is_separated:
        context.add_warning(
            f"Date de divorce présente mais is_separated=False pour famille {family.family_id}",  # noqa: E501
            context=f"Famille: {family.family_id}",
        )

    return context.get_result()


def validate_family_members(
    family: "Family",
    genealogy: "Genealogy",
    context: ValidationContext | None = None,
) -> ValidationResult:
    """Valide que tous les membres d'une famille existent dans la généalogie

    Args:
        family: La famille à valider
        genealogy: La généalogie contenant toutes les données
        context: Contexte de validation (créé si non fourni)

    Returns:
        Résultat de validation avec erreurs éventuelles
    """
    if context is None:
        context = ValidationContext()

    # Vérifier l'existence des époux
    if family.husband_id and family.husband_id not in genealogy.persons:
        context.add_error(
            GeneWebValidationError(
                f"Époux '{family.husband_id}' non trouvé dans la généalogie",
                entity_type="Family",
                entity_id=family.family_id,
                field="husband_id",
                value=family.husband_id,
            )
        )

    if family.wife_id and family.wife_id not in genealogy.persons:
        context.add_error(
            GeneWebValidationError(
                f"Épouse '{family.wife_id}' non trouvée dans la généalogie",
                entity_type="Family",
                entity_id=family.family_id,
                field="wife_id",
                value=family.wife_id,
            )
        )

    # Vérifier l'existence des enfants
    for child in family.children:
        if child.person_id not in genealogy.persons:
            context.add_error(
                GeneWebValidationError(
                    f"Enfant '{child.person_id}' non trouvé dans la généalogie",
                    entity_type="Family",
                    entity_id=family.family_id,
                    field="children",
                    value=child.person_id,
                )
            )

    return context.get_result()


def validate_genealogy_consistency(
    genealogy: "Genealogy", context: ValidationContext | None = None
) -> ValidationResult:
    """Valide la cohérence globale d'une généalogie

    Cette fonction effectue une validation complète de toutes les personnes,
    familles et leurs relations croisées.

    Args:
        genealogy: La généalogie à valider
        context: Contexte de validation (créé si non fourni)

    Returns:
        Résultat de validation avec toutes les erreurs détectées
    """
    if context is None:
        context = ValidationContext()

    # Valider toutes les personnes
    for person in genealogy.persons.values():
        validate_person_basic(person, context)
        validate_person_relationships(person, genealogy, context)

    # Valider toutes les familles
    for family in genealogy.families.values():
        validate_family_basic(family, context)
        validate_family_members(family, genealogy, context)

    # Vérifications de cohérence bidirectionnelle
    validate_bidirectional_references(genealogy, context)

    return context.get_result()


def validate_bidirectional_references(
    genealogy: "Genealogy", context: ValidationContext | None = None
) -> ValidationResult:
    """Valide que les références entre personnes et familles sont bidirectionnelles

    Args:
        genealogy: La généalogie à valider
        context: Contexte de validation (créé si non fourni)

    Returns:
        Résultat de validation avec erreurs éventuelles
    """
    if context is None:
        context = ValidationContext()

    # Pour chaque famille, vérifier que les parents référencent cette famille
    for family in genealogy.families.values():
        if family.husband_id:
            husband = genealogy.persons.get(family.husband_id)
            if husband and family.family_id not in husband.families_as_spouse:
                context.add_warning(
                    f"L'époux {family.husband_id} ne référence pas la famille {family.family_id}",  # noqa: E501
                    context=f"Famille: {family.family_id}",
                )

        if family.wife_id:
            wife = genealogy.persons.get(family.wife_id)
            if wife and family.family_id not in wife.families_as_spouse:
                context.add_warning(
                    f"L'épouse {family.wife_id} ne référence pas la famille {family.family_id}",  # noqa: E501
                    context=f"Famille: {family.family_id}",
                )

        # Vérifier que les enfants référencent cette famille
        for child in family.children:
            child_person = genealogy.persons.get(child.person_id)
            if child_person and family.family_id not in child_person.families_as_child:
                context.add_warning(
                    f"L'enfant {child.person_id} ne référence pas la famille {family.family_id}",  # noqa: E501
                    context=f"Famille: {family.family_id}",
                )

    return context.get_result()


def create_partial_person(
    last_name: str,
    first_name: str,
    occurrence: int = 0,
    error_message: str | None = None,
) -> "Person":
    """Crée une personne partielle en cas d'erreur de parsing

    Cette fonction permet de créer un objet Person même si toutes les informations
    ne sont pas disponibles, facilitant ainsi le parsing gracieux.

    Args:
        last_name: Nom de famille
        first_name: Prénom
        occurrence: Numéro d'occurrence
        error_message: Message d'erreur décrivant le problème

    Returns:
        Objet Person avec is_valid=False et validation_errors rempli
    """
    from .person import Gender, Person

    person = Person(
        last_name=last_name or "UNKNOWN",
        first_name=first_name or "UNKNOWN",
        occurrence_number=occurrence,
        gender=Gender.UNKNOWN,
    )

    # Marquer comme invalide
    person.is_valid = False

    # Ajouter l'erreur
    if error_message:
        error = GeneWebValidationError(
            error_message,
            entity_type="Person",
            entity_id=person.unique_id,
        )
        person.validation_errors.append(error)

    return person


def create_partial_family(family_id: str, error_message: str | None = None) -> "Family":
    """Crée une famille partielle en cas d'erreur de parsing

    Args:
        family_id: Identifiant de la famille
        error_message: Message d'erreur décrivant le problème

    Returns:
        Objet Family avec is_valid=False et validation_errors rempli
    """
    from .family import Family

    family = Family(family_id=family_id)

    # Marquer comme invalide
    family.is_valid = False

    # Ajouter l'erreur
    if error_message:
        error = GeneWebValidationError(
            error_message,
            entity_type="Family",
            entity_id=family_id,
        )
        family.validation_errors.append(error)

    return family
