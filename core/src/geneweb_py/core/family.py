"""
Modèle Family pour les familles dans le format GeneWeb

Ce module définit la représentation des unités familiales avec époux,
enfants et événements familiaux.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from .date import Date
from .event import EventType, FamilyEvent, FamilyEventType, WitnessKind

if TYPE_CHECKING:
    pass


class MarriageStatus(Enum):
    """Statut du mariage/relation"""

    MARRIED = ""  # Marié par défaut
    NOT_MARRIED = "nm"  # Relation sans mariage
    ENGAGED = "eng"  # Fiancé
    SEPARATED = "sep"  # Séparé
    DIVORCED = "div"  # Divorcé
    WIDOWED = "wid"  # Veuf/Veuve
    UNKNOWN = "?"  # Inconnu


class ChildSex(Enum):
    """Sexe d'un enfant (pour l'identification)"""

    MALE = "h"
    FEMALE = "f"
    UNKNOWN = ""


class FamilyQualifier(str, Enum):
    """Qualificateurs de la ligne fam GeneWeb."""

    NO_SEX_CHECK = "nsck"
    NO_SEX_CHECK_MARRIAGE = "nsckm"
    NO_MENTION = "noment"
    BANNS = "banns"
    CONTRACT = "contract"
    LICENSE = "license"
    PACS = "pacs"
    RESIDENCE = "residence"


@dataclass
class Child:
    """Représentation d'un enfant dans une famille"""

    person_id: str  # Référence vers la personne
    sex: ChildSex = ChildSex.UNKNOWN
    last_name: Optional[str] = None  # Si différent du père

    def __str__(self) -> str:
        """Représentation string de l'enfant"""
        parts = []
        if self.sex != ChildSex.UNKNOWN:
            parts.append(f"-{self.sex.value}")
        else:
            parts.append("-")

        if self.last_name:
            parts.append(self.last_name)

        parts.append(self.person_id)
        return " ".join(parts)


@dataclass
class Family:
    """Représentation d'une famille dans la généalogie

    Une famille est composée d'un époux, d'une épouse et d'enfants,
    avec des événements familiaux (mariage, divorce, etc.).
    """

    # Identifiant unique de la famille
    family_id: str

    @property
    def id(self) -> str:
        """Alias pour family_id pour compatibilité API"""
        return self.family_id

    # Époux et épouse (références vers les Person)
    husband_id: Optional[str] = None
    wife_id: Optional[str] = None

    # Informations sur le mariage/relation
    marriage_date: Optional[Date] = None
    marriage_place: Optional[str] = None
    marriage_source: Optional[str] = None
    marriage_status: MarriageStatus = MarriageStatus.MARRIED

    # Qualificateurs de relation/mariage
    family_qualifiers: List["FamilyQualifier"] = field(default_factory=list)

    # Divorce/séparation
    divorce_date: Optional[Date] = None
    is_separated: bool = False

    # Enfants
    children: List[Child] = field(default_factory=list)

    # Témoins du mariage
    witnesses: List[Dict[str, Any]] = field(default_factory=list)

    # Informations sur les enfants
    common_birth_place: Optional[str] = None  # #cbp
    common_children_source: Optional[str] = None  # #csrc

    # Événements familiaux (gwplus)
    events: List[FamilyEvent] = field(default_factory=list)

    # Sources et commentaires
    family_source: Optional[str] = None
    comments: List[str] = field(default_factory=list)

    # Métadonnées
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Provenance : lignes du fichier .gw source (1-indexées, bornes incluses)
    start_line: Optional[int] = None
    end_line: Optional[int] = None

    # Ligne ``fam ? ? + ? ?`` : conjoints inconnus déclarés, pas une omission
    spouses_unknown: bool = False

    # Validation gracieuse
    is_valid: bool = field(default=True)
    validation_errors: List[Any] = field(
        default_factory=list
    )  # List[GeneWebError] mais évite import circulaire

    def __post_init__(self):
        """Validation après initialisation"""
        # Vérifier qu'au moins un époux est défini (validation gracieuse)
        if not self.husband_id and not self.wife_id and not self.spouses_unknown:
            from .exceptions import GeneWebValidationError

            error = GeneWebValidationError(
                "Une famille doit avoir au moins un époux ou une épouse",
                field="husband_id/wife_id",
                entity_type="Family",
                entity_id=self.family_id,
            )
            self.add_validation_error(error)

        # Validation gracieuse des dates
        if self.marriage_date and self.divorce_date:
            if self.marriage_date.year and self.divorce_date.year:
                if self.marriage_date.year > self.divorce_date.year:
                    from .exceptions import GeneWebValidationError

                    error = GeneWebValidationError(
                        f"Date de mariage ({self.marriage_date}) postérieure à la date de divorce ({self.divorce_date})",  # noqa: E501
                        field="marriage_date",
                        entity_type="Family",
                        entity_id=self.family_id,
                    )
                    self.add_validation_error(error)

    @property
    def spouse_ids(self) -> List[str]:
        """Retourne la liste des IDs des époux"""
        spouses = []
        if self.husband_id:
            spouses.append(self.husband_id)
        if self.wife_id:
            spouses.append(self.wife_id)
        return spouses

    @property
    def child_ids(self) -> List[str]:
        """Retourne la liste des IDs des enfants"""
        return [child.person_id for child in self.children]

    @property
    def all_member_ids(self) -> List[str]:
        """Retourne tous les membres de la famille"""
        return self.spouse_ids + self.child_ids

    @property
    def is_married(self) -> bool:
        """Vérifie si c'est un mariage officiel"""
        return self.marriage_status == MarriageStatus.MARRIED

    @property
    def is_divorced(self) -> bool:
        """Vérifie si la famille est divorcée"""
        return self.divorce_date is not None

    @property
    def is_separated_status(self) -> bool:
        """Vérifie si la famille est séparée"""
        return self.is_separated or self.marriage_status == MarriageStatus.SEPARATED

    def add_child(
        self,
        person_id: str,
        sex: ChildSex = ChildSex.UNKNOWN,
        last_name: Optional[str] = None,
    ) -> None:
        """Ajoute un enfant à la famille

        Args:
            person_id: ID de la personne enfant
            sex: Sexe de l'enfant
            last_name: Nom de famille si différent du père
        """
        child = Child(person_id=person_id, sex=sex, last_name=last_name)
        self.children.append(child)

    def remove_child(self, person_id: str) -> bool:
        """Retire un enfant de la famille

        Args:
            person_id: ID de la personne à retirer

        Returns:
            True si l'enfant a été trouvé et retiré, False sinon
        """
        for i, child in enumerate(self.children):
            if child.person_id == person_id:
                del self.children[i]
                return True
        return False

    def add_witness(
        self,
        person_id: str,
        witness_type: Optional[str] = None,
        witness_kind: Optional[WitnessKind] = None,
    ) -> None:
        """Ajoute un témoin au mariage

        Args:
            person_id: ID de la personne témoin
            witness_type: Type de témoin (m=masculin, f=féminin)
            witness_kind: Rôle explicite (``#godp``, ``#offi``), None si simple
        """
        witness = {
            "person_id": person_id,
            "type": witness_type,
            "witness_kind": witness_kind,
            "note": None,
        }
        self.witnesses.append(witness)

    def add_event(self, event: FamilyEvent) -> None:
        """Ajoute un événement familial"""
        self.events.append(event)

    def add_comment(self, comment: str) -> None:
        """Ajoute un commentaire à la famille"""
        self.comments.append(comment)

    def get_events_by_type(
        self, event_type: Union[EventType, FamilyEventType]
    ) -> List[FamilyEvent]:
        """Retourne tous les événements d'un type donné"""
        if isinstance(event_type, EventType):
            # Convertir EventType vers FamilyEventType si possible
            type_mapping = {
                EventType.MARRIAGE: FamilyEventType.MARRIAGE,
                EventType.DIVORCE: FamilyEventType.DIVORCE,
                EventType.SEPARATION: FamilyEventType.SEPARATION,
                EventType.ENGAGEMENT: FamilyEventType.ENGAGEMENT,
                EventType.PACS: FamilyEventType.PACS,
            }
            family_event_type = type_mapping.get(event_type)
            if family_event_type:
                return [
                    event
                    for event in self.events
                    if event.family_event_type == family_event_type
                ]
        else:
            return [
                event for event in self.events if event.family_event_type == event_type
            ]

        return []

    def spouse(self, person_id: str) -> Optional[str]:
        """Retourne l'ID du conjoint d'une personne donnée

        Args:
            person_id: ID de la personne

        Returns:
            ID du conjoint ou None si pas trouvé
        """
        if person_id == self.husband_id:
            return self.wife_id
        elif person_id == self.wife_id:
            return self.husband_id
        return None

    def is_parent(self, person_id: str) -> bool:
        """Vérifie si une personne est parent dans cette famille

        Args:
            person_id: ID de la personne à vérifier

        Returns:
            True si la personne est époux(se) dans cette famille
        """
        return person_id in self.spouse_ids

    def is_child(self, person_id: str) -> bool:
        """Vérifie si une personne est enfant dans cette famille

        Args:
            person_id: ID de la personne à vérifier

        Returns:
            True si la personne est enfant dans cette famille
        """
        return person_id in self.child_ids

    def is_member(self, person_id: str) -> bool:
        """Vérifie si une personne est membre de cette famille

        Args:
            person_id: ID de la personne à vérifier

        Returns:
            True si la personne est membre (parent ou enfant)
        """
        return self.is_parent(person_id) or self.is_child(person_id)

    def add_validation_error(self, error: Any) -> None:
        """Ajoute une erreur de validation à la famille

        Args:
            error: L'erreur à ajouter
        """
        self.validation_errors.append(error)
        self.is_valid = False

    def clear_validation_errors(self) -> None:
        """Efface toutes les erreurs de validation"""
        self.validation_errors.clear()
        self.is_valid = True

    def to_dict(self) -> Dict[str, Any]:
        """Convertit la famille en dictionnaire pour sérialisation"""
        return {
            "family_id": self.family_id,
            "husband_id": self.husband_id,
            "wife_id": self.wife_id,
            "marriage_date": (
                self.marriage_date.display_text if self.marriage_date else None
            ),
            "marriage_place": self.marriage_place,
            "marriage_status": self.marriage_status.value,
            "divorce_date": (
                self.divorce_date.display_text if self.divorce_date else None
            ),
            "is_separated": self.is_separated_status,
            "children": [
                {
                    "person_id": child.person_id,
                    "sex": child.sex.value,
                    "last_name": child.last_name,
                }
                for child in self.children
            ],
            "witnesses": self.witnesses,
            "events": [event.to_dict() for event in self.events],
            "comments": self.comments,
            "family_source": self.family_source,
            "is_valid": self.is_valid,
            "validation_errors": [str(e) for e in self.validation_errors],
        }

    def __str__(self) -> str:
        """Représentation string de la famille"""
        spouses = []
        if self.husband_id:
            spouses.append(self.husband_id)
        if self.wife_id:
            spouses.append(self.wife_id)

        spouse_str = " + ".join(spouses)
        child_count = len(self.children)

        return f"Family({spouse_str}) - {child_count} enfants"

    def __repr__(self) -> str:
        """Représentation pour debug"""
        return f"Family('{self.family_id}')"
