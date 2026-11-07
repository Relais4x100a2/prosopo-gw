"""
Modèle Event pour les événements généalogiques

Ce module définit les événements personnels et familiaux dans le format GeneWeb,
avec support des événements gwplus.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from .date import Date
from .place import ParsedPlace, parse_place

if TYPE_CHECKING:
    pass


class EventType(Enum):
    """Types d'événements personnels"""

    # Événements de base
    BIRTH = "birt"
    BAPTISM = "bapt"
    DEATH = "deat"
    BURIAL = "buri"
    CREMATION = "crem"

    # Événements religieux
    CONFIRMATION = "conf"
    FIRST_COMMUNION = "fcom"
    ORDINATION = "ordn"
    EXCOMMUNICATION = "exco"

    # Événements civils
    NATURALIZATION = "natu"
    OCCUPATION = "occu"
    RESIDENCE = "resi"
    EDUCATION = "educ"
    GRADUATION = "grad"
    MILITARY_SERVICE = "mser"

    # Autre / type inconnu (import inter-formats, extensions)
    OTHER = "oth"

    # Événements personnels gwplus — compléments spec officielle
    ACCOMPLISHMENT = "acco"
    ACQUISITION = "acqu"
    ADHESION = "adhe"
    BAPTISM_LDS = "bapl"
    BAR_MITZVAH = "barm"
    BAT_MITZVAH = "basm"
    BENEDICTION = "bles"
    RECENSEMENT = "cens"
    CHANGE_NAME = "chgn"
    CIRCUMCISION = "circ"
    CONFIRMATION_LDS = "conl"
    DIPLOMA = "degr"
    DECORATION = "awar"
    DEMOBILISATION = "demm"
    DISTINCTION = "dist"
    DOTATION = "endl"
    DOTATION_LDS = "dotl"
    ELECTION = "elec"
    EMIGRATION = "emig"
    FAMILY_LINK_LDS = "flkl"
    FUNERAL = "fune"
    HOSPITALISATION = "hosp"
    ILLNESS = "illn"
    IMMIGRATION = "immi"
    LAST_PASSAGE = "lpas"
    MILITARY_DISCHARGE = "mdis"
    MILITARY_PROMOTION = "mpro"
    MILITARY_MOBILISATION = "mobm"
    PROPERTY = "prop"
    RETIREMENT = "reti"
    SEALING_CHILD = "slgc"
    SEALING_PARENT = "slgp"
    SEALING_SPOUSE = "slgs"
    VOTE = "vteb"
    WILL = "will"
    STRNG = "strng"

    # Événements familiaux
    MARRIAGE = "marr"
    DIVORCE = "div"
    SEPARATION = "sep"
    ENGAGEMENT = "enga"
    PACS = "pacs"


class FamilyEventType(Enum):
    """Types d'événements familiaux (gwplus)"""

    MARRIAGE = "marr"
    NO_MARRIAGE = "nmar"
    NO_MENTION = "nmen"
    ENGAGEMENT = "enga"
    DIVORCE = "div"
    SEPARATION = "sep"
    ANNULMENT = "anul"
    MARRIAGE_BANN = "marb"
    MARRIAGE_CONTRACT = "marc"
    MARRIAGE_LICENSE = "marl"
    PACS = "pacs"
    RESIDENCE = "resi"
    NAME_STRING = "strng"
    OTHER = "other"  # tag libre : voir ``Event.event_type_raw``


class WitnessKind(Enum):
    """Rôle d'un témoin explicitement marqué dans le ``.gw``"""

    GODPARENT = "godp"  # ``wit m: #godp Personne`` : parrain ou marraine
    OFFICER = "offi"  # ``#offi`` : documenté par GeneWeb, pas encore implémenté


@dataclass
class Event:
    """Représentation d'un événement généalogique

    Un événement peut être personnel (pevt) ou familial (fevt) selon le contexte.
    """

    # Type d'événement
    event_type: EventType

    # Date de l'événement
    date: Date | None = None

    # Lieu de l'événement
    place: str | None = None

    # Source de l'événement
    source: str | None = None

    # Raison ou cause de l'événement
    reason: str | None = None

    # ID de la personne associée (pour les événements personnels)
    person_id: str | None = None

    # ID de la famille associée (pour les événements familiaux)
    family_id: str | None = None

    # Témoins (pour les événements familiaux)
    witnesses: list[dict[str, Any]] = field(default_factory=list)

    # Notes sur l'événement
    notes: list[str] = field(default_factory=list)

    # Informations spécifiques selon le type d'événement
    metadata: dict[str, Any] = field(default_factory=dict)

    # Type brut pour les événements non reconnus (event_type == OTHER dans ce cas)
    event_type_raw: str | None = None

    # Provenance : lignes du fichier .gw source (1-indexées, bornes incluses)
    start_line: int | None = None
    end_line: int | None = None

    def add_witness(
        self,
        person_id: str,
        witness_type: str | None = None,
        witness_kind: WitnessKind | None = None,
    ) -> None:
        """Ajoute un témoin à l'événement

        Args:
            person_id: ID de la personne témoin
            witness_type: Type de témoin (m=masculin, f=féminin, etc.)
            witness_kind: Rôle explicite (``#godp``, ``#offi``), None si témoin simple
        """
        witness_info = {
            "person_id": person_id,
            "type": witness_type,
            "witness_kind": witness_kind,
            "note": None,
        }
        self.witnesses.append(witness_info)

    def add_note(self, note: str) -> None:
        """Ajoute une note à l'événement"""
        self.notes.append(note)

    @property
    def place_parts(self) -> ParsedPlace | None:
        """Lieu décomposé (complément / commune) ; ``place`` reste la chaîne brute"""
        return parse_place(self.place)

    def set_metadata(self, key: str, value: Any) -> None:
        """Définit une métadonnée spécifique à l'événement"""
        self.metadata[key] = value

    @property
    def display_name(self) -> str:
        """Retourne le nom d'affichage de l'événement"""
        return self.event_type.value.upper()

    @property
    def is_family_event(self) -> bool:
        """Vérifie si c'est un événement familial"""
        family_events = {
            EventType.MARRIAGE,
            EventType.DIVORCE,
            EventType.SEPARATION,
            EventType.ENGAGEMENT,
            EventType.PACS,
        }
        return self.event_type in family_events

    def to_dict(self) -> dict[str, Any]:
        """Convertit l'événement en dictionnaire pour sérialisation"""
        return {
            "type": self.event_type.value,
            "type_raw": self.event_type_raw,
            "date": self.date.display_text if self.date else None,
            "place": self.place,
            "source": self.source,
            "witnesses": [w["person_id"] for w in self.witnesses],
            "notes": self.notes,
            "metadata": self.metadata,
        }


@dataclass
class FamilyEvent(Event):
    """Événement familial spécifique (format gwplus)"""

    family_event_type: FamilyEventType | None = None

    def __post_init__(self) -> None:
        """Initialisation post-création"""
        if self.family_event_type:
            # Mapper le type familial vers le type générique
            mapping = {
                FamilyEventType.MARRIAGE: EventType.MARRIAGE,
                FamilyEventType.DIVORCE: EventType.DIVORCE,
                FamilyEventType.SEPARATION: EventType.SEPARATION,
                FamilyEventType.ENGAGEMENT: EventType.ENGAGEMENT,
                FamilyEventType.PACS: EventType.PACS,
            }
            if self.family_event_type in mapping:
                self.event_type = mapping[self.family_event_type]

    @property
    def is_family_event(self) -> bool:
        """Les événements familiaux sont toujours des événements familiaux"""
        return True


@dataclass
class PersonalEvent(Event):
    """Événement personnel spécifique (format gwplus)"""

    def __post_init__(self) -> None:
        """Initialisation post-création"""
        # Les événements personnels ne sont jamais familiaux
        pass

    @property
    def is_family_event(self) -> bool:
        """Les événements personnels ne sont jamais familiaux"""
        return False
