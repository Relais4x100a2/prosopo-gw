"""
Modèle Person pour les personnes dans le format GeneWeb

Ce module définit la représentation des personnes avec toutes leurs informations
personnelles, événements et relations familiales.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .date import Date
from .event import PersonalEvent


class Gender(Enum):
    """Sexe d'une personne"""

    MALE = "m"
    FEMALE = "f"
    UNKNOWN = "?"


class AccessLevel(Enum):
    """Niveau d'accès aux informations d'une personne"""

    PUBLIC = "apubl"
    PRIVATE = "apriv"
    DEFAULT = ""  # Suit la règle "If Titles"


class RelationType(Enum):
    """Type de relation d'un bloc ``rel``"""

    ADOPTION = "adop"
    RECOGNITION = "reco"
    CANDIDATE = "cand"
    GODPARENT = "godp"
    FOSTER = "fost"


class ParentRole(Enum):
    """Côté du parent concerné par une relation (``fath`` / ``moth``)"""

    FATHER = "fath"
    MOTHER = "moth"


@dataclass(frozen=True)
class Relation:
    """Ligne ``- <type> [fath|moth]: Personne`` d'un bloc ``rel``

    ``target_person_key`` est l'identifiant complet ``Nom_Prenom_occ``.
    """

    relation_type: RelationType
    parent_role: ParentRole | None
    target_person_key: str
    # Provenance : ligne du ``.gw`` (1-indexée). Hors comparaison : deux relations
    # identiques écrites à des endroits différents restent égales.
    start_line: int | None = field(default=None, compare=False)
    end_line: int | None = field(default=None, compare=False)


@dataclass
class Title:
    """Titre d'une personne (noblesse, profession, etc.)"""

    name: str
    title_type: str = ""
    place: str = ""
    start_date: Date | None = None
    end_date: Date | None = None
    number: int = 0
    is_main: bool = False  # Marqué avec * dans le format .gw

    def __str__(self) -> str:
        """Représentation string du titre"""
        parts = [self.name, self.title_type, self.place]

        if self.start_date:
            parts.append(self.start_date.display_text)
        else:
            parts.append("")

        if self.end_date:
            parts.append(self.end_date.display_text)
        else:
            parts.append("")

        if self.number > 0:
            parts.append(str(self.number))

        return ":".join(parts)


@dataclass
class Person:
    """Représentation d'une personne dans la généalogie

    Contient toutes les informations personnelles, dates importantes,
    événements et relations familiales.
    """

    # Informations de base
    last_name: str
    first_name: str
    occurrence_number: int = 0  # Pour distinguer les homonymes

    # Noms alternatifs
    public_name: str | None = None  # (PublicName)
    nickname: str | None = None  # #nick
    first_name_alias: str | None = None  # {FirstNameAlias}
    surname_alias: str | None = None  # #salias
    general_alias: str | None = None  # #alias

    # Titres
    titles: list[Title] = field(default_factory=list)

    # Informations personnelles
    gender: Gender = Gender.UNKNOWN
    occupation: str | None = None
    image_path: str | None = None

    # Dates importantes
    birth_date: Date | None = None
    death_date: Date | None = None
    baptism_date: Date | None = None

    # Lieux
    birth_place: str | None = None
    death_place: str | None = None
    baptism_place: str | None = None
    burial_place: str | None = None

    # Sources
    birth_source: str | None = None
    death_source: str | None = None
    baptism_source: str | None = None
    burial_source: str | None = None
    person_source: str | None = None

    # Événements personnels (gwplus)
    events: list[PersonalEvent] = field(default_factory=list)

    # Informations de décès
    is_deceased: bool | None = None  # ? pour inconnu
    is_obviously_dead: bool = False  # #od tag
    is_young_death: bool = False  # #mj tag
    is_anonymous: bool = False  # conjoint ``? ?`` : personne créée, identité inconnue
    burial_type: str | None = None  # #buri ou #crem

    # Contrôle d'accès
    access_level: AccessLevel = AccessLevel.DEFAULT

    # Relations familiales (références)
    families_as_child: list[str] = field(
        default_factory=list
    )  # IDs des familles où cette personne est enfant
    families_as_spouse: list[str] = field(
        default_factory=list
    )  # IDs des familles où cette personne est époux(se)

    # Notes personnelles
    notes: list[str] = field(default_factory=list)

    # Relations spéciales (adoption, parrainage, etc.)
    relations: dict[str, list[str]] = field(default_factory=dict)
    # Relations typées (bloc rel) ; ``relations`` en garde la vue par type
    relation_links: list[Relation] = field(default_factory=list)

    # Métadonnées personnalisées
    metadata: dict[str, Any] = field(default_factory=dict)

    # Provenance : lignes du fichier .gw source (1-indexées, bornes incluses)
    start_line: int | None = None
    end_line: int | None = None

    # Validation gracieuse
    is_valid: bool = field(default=True)
    validation_errors: list[Any] = field(
        default_factory=list
    )  # List[GeneWebError] mais évite import circulaire

    def __post_init__(self) -> None:
        """Validation après initialisation"""
        # Normaliser les noms (remplacer espaces par underscores)
        self.last_name = self.last_name.replace(" ", "_")
        self.first_name = self.first_name.replace(" ", "_")

        if self.public_name:
            self.public_name = self.public_name.replace(" ", "_")

        # Validation gracieuse des dates
        if self.birth_date and self.death_date:
            if self.birth_date.year and self.death_date.year:
                if self.birth_date.year > self.death_date.year:
                    # Au lieu de lever une exception, ajouter une erreur de validation
                    from .exceptions import GeneWebValidationError

                    error = GeneWebValidationError(
                        f"Date de naissance ({self.birth_date}) postérieure à la date de décès ({self.death_date})",  # noqa: E501
                        field="birth_date",
                        entity_type="Person",
                        entity_id=self.unique_id,
                    )
                    self.add_validation_error(error)

    @property
    def full_name(self) -> str:
        """Retourne le nom complet de la personne"""
        name_parts = [self.last_name, self.first_name]
        if self.occurrence_number > 0:
            name_parts.append(f".{self.occurrence_number}")
        return " ".join(name_parts)

    @property
    def display_name(self) -> str:
        """Retourne le nom d'affichage (avec nom public si disponible)"""
        if self.public_name:
            return f"{self.last_name} {self.public_name}"
        return self.full_name

    @property
    def unique_id(self) -> str:
        """Retourne un identifiant unique pour cette personne"""
        return f"{self.last_name}_{self.first_name}_{self.occurrence_number}"

    @property
    def age_at_death(self) -> int | None:
        """Calcule l'âge au décès si possible"""
        if not self.birth_date or not self.death_date:
            return None

        if not self.birth_date.year or not self.death_date.year:
            return None

        return self.death_date.year - self.birth_date.year

    @property
    def is_alive(self) -> bool:
        """Détermine si la personne est vivante"""
        # Si on a une date de décès, la personne est décédée
        if self.death_date:
            return False

        if self.is_deceased is True:
            return False
        if self.is_deceased is False:
            return True

        # Si inconnu, on peut essayer de déduire
        if self.is_obviously_dead:
            return False

        if self.birth_date and self.birth_date.year:
            # Née il y a plus de 120 ans (avant 1906 en 2026) : considérée décédée
            from datetime import datetime

            current_year = datetime.now().year
            if current_year - self.birth_date.year > 120:
                return False

        return True  # Par défaut, on assume vivant si inconnu

    def add_title(self, title: Title) -> None:
        """Ajoute un titre à la personne"""
        self.titles.append(title)

    def add_event(self, event: PersonalEvent) -> None:
        """Ajoute un événement personnel"""
        self.events.append(event)

    def add_note(self, note: str) -> None:
        """Ajoute une note personnelle"""
        self.notes.append(note)

    def get_notes_structured(self) -> "list[Any]":
        """Retourne les notes parsées (wikitext extrait), calculé on-demand.

        Returns:
            Liste de NoteContent (un par note), dans l'ordre de self.notes
        """
        from .parser.wikitext import WikitextParser

        parser = WikitextParser()
        return [parser.parse(note) for note in self.notes]

    def add_relation_link(self, relation: Relation) -> None:
        """Ajoute une relation typée et met à jour la vue ``relations``"""
        self.relation_links.append(relation)
        self.add_relation(relation.relation_type.value, relation.target_person_key)

    def add_relation(self, relation_type: str, person_id: str) -> None:
        """Ajoute une relation spéciale (adoption, parrainage, etc.)"""
        if relation_type not in self.relations:
            self.relations[relation_type] = []
        self.relations[relation_type].append(person_id)

    def get_events_by_type(self, event_type: str) -> list[PersonalEvent]:
        """Retourne tous les événements d'un type donné"""
        return [event for event in self.events if event.event_type.value == event_type]

    def get_families(self) -> list[str]:
        """Retourne toutes les familles liées à cette personne"""
        return self.families_as_child + self.families_as_spouse

    def add_validation_error(self, error: Any) -> None:
        """Ajoute une erreur de validation à la personne

        Args:
            error: L'erreur à ajouter
        """
        self.validation_errors.append(error)
        self.is_valid = False

    def clear_validation_errors(self) -> None:
        """Efface toutes les erreurs de validation"""
        self.validation_errors.clear()
        self.is_valid = True

    def to_dict(self) -> dict[str, Any]:
        """Convertit la personne en dictionnaire pour sérialisation"""
        return {
            "unique_id": self.unique_id,
            "full_name": self.full_name,
            "display_name": self.display_name,
            "last_name": self.last_name,
            "first_name": self.first_name,
            "occurrence_number": self.occurrence_number,
            "public_name": self.public_name,
            "nickname": self.nickname,
            "gender": self.gender.value,
            "occupation": self.occupation,
            "is_anonymous": self.is_anonymous,
            "birth_date": self.birth_date.display_text if self.birth_date else None,
            "death_date": self.death_date.display_text if self.death_date else None,
            "birth_place": self.birth_place,
            "death_place": self.death_place,
            "is_alive": self.is_alive,
            "age_at_death": self.age_at_death,
            "families_as_child": self.families_as_child,
            "families_as_spouse": self.families_as_spouse,
            "events": [event.to_dict() for event in self.events],
            "relations": self.relations,
            "relation_links": [
                {
                    "type": r.relation_type.value,
                    "parent_role": r.parent_role.value if r.parent_role else None,
                    "target": r.target_person_key,
                }
                for r in self.relation_links
            ],
            "notes": self.notes,
            "is_valid": self.is_valid,
            "validation_errors": [str(e) for e in self.validation_errors],
        }

    def __str__(self) -> str:
        """Représentation string de la personne"""
        return self.display_name

    def __repr__(self) -> str:
        """Représentation pour debug"""
        return f"Person('{self.full_name}')"
