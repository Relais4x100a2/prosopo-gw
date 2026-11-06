"""
Service principal pour la gestion de la généalogie dans l'API geneweb-py.

Ce service fournit les opérations CRUD et la logique métier pour manipuler
les données généalogiques.
"""

import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from ...core.date import Date
from ...core.models import (
    Event,
    EventType,
    Family,
    FamilyEvent,
    FamilyEventType,
    Genealogy,
    Person,
    PersonalEvent,
)
from ...core.parser import GeneWebParser
from ...core.place import place_city
from ...core.shared_experiences import SharedExperienceIndex, find_shared_experiences
from ..models.event import (
    EventUpdateSchema,
    FamilyEventCreateSchema,
    PersonalEventCreateSchema,
)
from ..models.family import FamilyCreateSchema, FamilySearchSchema, FamilyUpdateSchema
from ..models.person import PersonCreateSchema, PersonSearchSchema, PersonUpdateSchema
from ..serialization import (
    count_by_birth_century,
    count_event_century,
    count_marriage_century,
    event_witnesses_to_api_strings,
    family_events_breakdown,
    parse_api_date_string,
    stable_event_id,
    titles_from_create_schemas,
)
from .export_bundle import build_export_bundle
from .organization_candidates import (
    DEFAULT_IGNORED_WORDS,
    CandidateIndex,
    UnmatchedGroup,
    build_candidate_index,
    build_unmatched,
    normalize_ignored_words,
)
from .organization_tables import build_organization_tables


def _normalize_search_text(text: str) -> str:
    """Normalize for accent/case/hyphen-insensitive comparison.

    Removes accents using NFD normalization and converts hyphens/underscores
    to spaces for flexible place matching.
    """
    nfd = unicodedata.normalize("NFD", text.lower())
    no_accents = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return no_accents.replace("-", " ").replace("_", " ")


def _family_search_text(genealogy: Genealogy, family: Family) -> str:
    """Texte normalisé où chercher une famille : noms des conjoints, lieu du mariage."""
    parts: List[str] = []
    for pid in (family.husband_id, family.wife_id):
        person = genealogy.persons.get(pid) if pid else None
        if person is not None:
            parts += [person.first_name, person.last_name, person.public_name or ""]
    parts.append(family.marriage_place or "")
    return _normalize_search_text(" ".join(parts))


def _api_event_type_value(event: Event) -> str:
    """Valeur de type d'événement telle qu'exposée par l'API (voir ``event_to_schema``)."""
    if isinstance(event, FamilyEvent) and event.family_event_type is not None:
        raw: Any = event.family_event_type
    else:
        raw = event.event_type
    return str(getattr(raw, "value", raw))


@dataclass(frozen=True)
class EventSearchHit:
    """Contexte d'un événement pour recherche et sérialisation API."""

    event: Event
    person_id: Optional[str]
    family_id: Optional[str]
    index: int


class GenealogyService:
    """Service principal pour la gestion de la généalogie."""

    def __init__(
        self,
        genealogy: Optional[Genealogy] = None,
        source_name: Optional[str] = None,
    ) -> None:
        """Initialise le service ; ``source_name`` nomme l'archive d'export."""
        self._source_name = source_name
        self._genealogy: Optional[Genealogy] = None
        self._parser = GeneWebParser(use_multipass=False)
        self._witness_index: Optional[Dict[str, set]] = None  # lazy cache
        self._candidate_index: Optional[CandidateIndex] = None
        self._shared_experiences: Optional[SharedExperienceIndex] = None
        self._unmatched: Optional[Tuple[int, List[UnmatchedGroup]]] = None
        self._export_summary: Optional[Dict[str, int]] = None
        self._orgs_inferred = False  # organisations produites par l'inférence
        self._ignored_words: Tuple[str, ...] = DEFAULT_IGNORED_WORDS
        if genealogy is not None:
            self._genealogy = genealogy
        else:
            self._initialize_empty_genealogy()

    def _initialize_empty_genealogy(self) -> None:
        """Initialise une généalogie avec des données de test."""
        from pathlib import Path

        # Essayer de charger un fichier de test
        test_file = (
            Path(__file__).parent.parent.parent.parent
            / "tests"
            / "fixtures"
            / "simple_test.gw"
        )

        if test_file.exists():
            try:
                self._genealogy = self._parser.parse_file(str(test_file))
                return
            except Exception:
                # Si le parsing échoue, continuer avec une généalogie vide
                pass

        # Créer une généalogie vide par défaut
        from ...core.genealogy import Genealogy, GenealogyMetadata

        metadata = GenealogyMetadata(
            source_file=None,
            encoding="utf-8",
            is_gwplus=False,
            created_date=datetime.now(),
            modified_date=datetime.now(),
            geneweb_version="1.0",
        )

        self._genealogy = Genealogy(persons={}, families={}, metadata=metadata)

    def load_from_file(self, file_path: str) -> Genealogy:
        """
        Charge une généalogie depuis un fichier .gw.

        Args:
            file_path: Chemin vers le fichier .gw

        Returns:
            Genealogy: Objet généalogie chargé

        Raises:
            GeneWebParseError: Erreur de parsing du fichier
        """
        genealogy = self._parser.parse_file(file_path)
        self._genealogy = genealogy
        return genealogy

    def create_empty(self) -> Genealogy:
        """
        Crée une généalogie vide.

        Returns:
            Genealogy: Nouvelle généalogie vide
        """
        self._initialize_empty_genealogy()
        assert self._genealogy is not None  # posé par _initialize_empty_genealogy
        return self._genealogy

    @property
    def genealogy(self) -> Genealogy:
        """
        Retourne la généalogie actuelle.

        Returns:
            Genealogy: Généalogie actuelle

        Raises:
            ValueError: Si aucune généalogie n'est chargée
        """
        if self._genealogy is None:
            raise ValueError(
                "Aucune généalogie chargée. Utilisez load_from_file() ou create_empty()."  # noqa: E501
            )
        return self._genealogy

    # === GESTION DES PERSONNES ===

    def create_person(self, person_data: PersonCreateSchema) -> Person:
        """
        Crée une nouvelle personne.

        Args:
            person_data: Données de la personne à créer

        Returns:
            Person: Personne créée
        """
        genealogy = self.genealogy

        titles = titles_from_create_schemas(person_data.titles)

        # Création de la personne
        person = Person(
            last_name=person_data.surname,
            first_name=person_data.first_name,
            public_name=person_data.public_name,
            titles=titles,
            image_path=person_data.image,
            gender=person_data.sex,
            access_level=person_data.access_level,
            notes=[],
        )

        # Utilisation de l'ID unique généré automatiquement
        person_id = person.unique_id

        # Vérification que la personne n'existe pas déjà
        if person_id in genealogy.persons:
            # Si elle existe, on incrémente le numéro d'occurrence
            occurrence = 1
            while (
                f"{person_data.surname}_{person_data.first_name}_{occurrence}"
                in genealogy.persons
            ):
                occurrence += 1
            person.occurrence_number = occurrence
            person_id = person.unique_id

        genealogy.persons[person_id] = person
        genealogy.metadata.modified_date = datetime.now()

        return person

    def get_person(self, person_id: str) -> Optional[Person]:
        """
        Récupère une personne par son ID.

        Args:
            person_id: Identifiant de la personne

        Returns:
            Person: Personne trouvée ou None
        """
        genealogy = self.genealogy
        return genealogy.persons.get(person_id)

    def update_person(
        self, person_id: str, person_data: PersonUpdateSchema
    ) -> Optional[Person]:
        """
        Met à jour une personne.

        Args:
            person_id: Identifiant de la personne
            person_data: Nouvelles données

        Returns:
            Person: Personne mise à jour ou None si non trouvée
        """
        genealogy = self.genealogy
        person = self.get_person(person_id)

        if person is None:
            return None

        # Mise à jour des champs fournis
        if person_data.first_name is not None:
            person.first_name = person_data.first_name
        if person_data.surname is not None:
            person.last_name = person_data.surname
        if person_data.public_name is not None:
            person.public_name = person_data.public_name
        if person_data.image is not None:
            person.image_path = person_data.image
        if person_data.sex is not None:
            person.gender = person_data.sex
        if person_data.access_level is not None:
            person.access_level = person_data.access_level
        if person_data.titles is not None:
            person.titles = titles_from_create_schemas(person_data.titles)

        genealogy.metadata.modified_date = datetime.now()
        self._invalidate_caches()
        return person

    def delete_person(self, person_id: str) -> bool:
        """
        Supprime une personne.

        Args:
            person_id: Identifiant de la personne

        Returns:
            bool: True si supprimée, False si non trouvée
        """
        genealogy = self.genealogy
        person = self.get_person(person_id)

        if person is None:
            return False

        # Suppression des références dans les familles
        for family in genealogy.families.values():
            if family.husband_id == person_id:
                family.husband_id = None
            if family.wife_id == person_id:
                family.wife_id = None
            family.children = [
                child for child in family.children if child.person_id != person_id
            ]

        # Les événements personnels sont supprimés automatiquement avec la personne

        # Suppression de la personne
        if person_id in genealogy.persons:
            del genealogy.persons[person_id]
        genealogy.metadata.modified_date = datetime.now()
        self._invalidate_caches()

        return True

    def search_persons(
        self, search_params: PersonSearchSchema
    ) -> Tuple[List[Person], int]:
        """
        Recherche des personnes selon les critères.

        Args:
            search_params: Paramètres de recherche

        Returns:
            Tuple[List[Person], int]: (Personnes trouvées, nombre total)
        """
        genealogy = self.genealogy
        persons = list(genealogy.persons.values())

        # Filtrage par critères
        if search_params.query:
            # Recherche par mots : chacun doit figurer dans « prénoms nom nom public »,
            # quel que soit l'ordre, la casse, les accents ou la ponctuation.
            tokens = _normalize_search_text(
                search_params.query.replace(",", " ")
            ).split()
            persons = [
                p
                for p in persons
                if all(
                    tok in hay
                    for hay in [
                        _normalize_search_text(
                            f"{p.first_name} {p.last_name} {p.public_name or ''}"
                        )
                    ]
                    for tok in tokens
                )
            ]

        if search_params.first_name:
            persons = [
                p
                for p in persons
                if search_params.first_name.lower() in p.first_name.lower()
            ]

        if search_params.surname:
            persons = [
                p
                for p in persons
                if search_params.surname.lower() in p.last_name.lower()
            ]

        if search_params.sex:
            persons = [p for p in persons if p.gender == search_params.sex]

        if search_params.access_level:
            persons = [
                p for p in persons if p.access_level == search_params.access_level
            ]

        if (
            search_params.birth_year_from is not None
            or search_params.birth_year_to is not None
        ):
            persons = [
                p
                for p in persons
                if _person_year_in_range(
                    p.birth_date,
                    search_params.birth_year_from,
                    search_params.birth_year_to,
                )
            ]

        if (
            search_params.death_year_from is not None
            or search_params.death_year_to is not None
        ):
            persons = [
                p
                for p in persons
                if _person_year_in_range(
                    p.death_date,
                    search_params.death_year_from,
                    search_params.death_year_to,
                )
            ]

        if search_params.place:
            needle = _normalize_place_fragment(search_params.place)
            persons = [p for p in persons if _person_matches_place(p, needle)]

        total = len(persons)

        # Pagination
        start = (search_params.page - 1) * search_params.size
        end = start + search_params.size
        persons = persons[start:end]

        return persons, total

    # === GESTION DES FAMILLES ===

    def create_family(self, family_data: FamilyCreateSchema) -> Family:
        """
        Crée une nouvelle famille.

        Args:
            family_data: Données de la famille à créer

        Returns:
            Family: Famille créée
        """
        genealogy = self.genealogy

        # Génération d'un ID unique
        family_id = f"f{len(genealogy.families) + 1}"

        # Conversion des enfants
        children = []
        for child_data in family_data.children:
            from ...core.family import Child

            child = Child(
                person_id=child_data.person_id,
                sex=child_data.sex,
                last_name=child_data.last_name,
            )
            children.append(child)

        # Création de la famille
        family = Family(
            family_id=family_id,
            husband_id=family_data.husband_id,
            wife_id=family_data.wife_id,
            children=children,
            marriage_status=family_data.marriage_status,
            comments=family_data.notes,
            family_source=family_data.sources[0] if family_data.sources else None,
        )

        genealogy.families[family_id] = family
        genealogy.metadata.modified_date = datetime.now()

        return family

    def get_family(self, family_id: str) -> Optional[Family]:
        """
        Récupère une famille par son ID.

        Args:
            family_id: Identifiant de la famille

        Returns:
            Family: Famille trouvée ou None
        """
        genealogy = self.genealogy
        return genealogy.families.get(family_id)

    def update_family(
        self, family_id: str, family_data: FamilyUpdateSchema
    ) -> Optional[Family]:
        """
        Met à jour une famille.

        Args:
            family_id: Identifiant de la famille
            family_data: Nouvelles données

        Returns:
            Family: Famille mise à jour ou None si non trouvée
        """
        genealogy = self.genealogy
        family = self.get_family(family_id)

        if family is None:
            return None

        # Mise à jour des champs fournis
        if family_data.husband_id is not None:
            family.husband_id = family_data.husband_id
        if family_data.wife_id is not None:
            family.wife_id = family_data.wife_id
        if family_data.marriage_status is not None:
            family.marriage_status = family_data.marriage_status
        if family_data.notes is not None:
            family.comments = family_data.notes
        if family_data.sources is not None:
            src_first: Optional[str] = None
            for s in family_data.sources:
                if s and str(s).strip():
                    src_first = str(s).strip()
                    break
            family.family_source = src_first
        if family_data.children is not None:
            # Conversion des enfants
            children = []
            for child_data in family_data.children:
                from ...core.family import Child

                child = Child(
                    person_id=child_data.person_id,
                    sex=child_data.sex,
                    last_name=child_data.last_name,
                )
                children.append(child)
            family.children = children

        genealogy.metadata.modified_date = datetime.now()
        return family

    def delete_family(self, family_id: str) -> bool:
        """
        Supprime une famille.

        Args:
            family_id: Identifiant de la famille

        Returns:
            bool: True si supprimée, False si non trouvée
        """
        genealogy = self.genealogy
        family = self.get_family(family_id)

        if family is None:
            return False

        # Les événements familiaux sont supprimés automatiquement avec la famille

        # Suppression de la famille
        if family_id in genealogy.families:
            del genealogy.families[family_id]
        genealogy.metadata.modified_date = datetime.now()

        return True

    def search_families(
        self, search_params: FamilySearchSchema
    ) -> Tuple[List[Family], int]:
        """
        Recherche des familles selon les critères.

        Args:
            search_params: Paramètres de recherche

        Returns:
            Tuple[List[Family], int]: (Familles trouvées, nombre total)
        """
        genealogy = self.genealogy
        families = list(genealogy.families.values())

        # Filtrage par critères
        if search_params.query:
            # Recherche par mots, comme pour les personnes : chacun doit figurer
            # dans les noms des deux conjoints ou le lieu du mariage, dans n'importe quel ordre.
            tokens = _normalize_search_text(
                search_params.query.replace(",", " ")
            ).split()
            families = [
                f
                for f in families
                if all(tok in _family_search_text(genealogy, f) for tok in tokens)
            ]

        if search_params.husband_id:
            families = [f for f in families if f.husband_id == search_params.husband_id]

        if search_params.wife_id:
            families = [f for f in families if f.wife_id == search_params.wife_id]

        if search_params.marriage_status:
            families = [
                f
                for f in families
                if f.marriage_status == search_params.marriage_status
            ]

        if search_params.has_children is not None:
            if search_params.has_children:
                families = [f for f in families if len(f.children) > 0]
            else:
                families = [f for f in families if len(f.children) == 0]

        if search_params.min_children is not None:
            families = [
                f for f in families if len(f.children) >= search_params.min_children
            ]

        if search_params.max_children is not None:
            families = [
                f for f in families if len(f.children) <= search_params.max_children
            ]

        total = len(families)

        # Pagination
        start = (search_params.page - 1) * search_params.size
        end = start + search_params.size
        families = families[start:end]

        return families, total

    # === GESTION DES ÉVÉNEMENTS ===

    def create_personal_event(
        self, event_data: PersonalEventCreateSchema
    ) -> PersonalEvent:
        """
        Crée un nouvel événement personnel.

        Args:
            event_data: Données de l'événement à créer

        Returns:
            PersonalEvent: Événement créé
        """
        genealogy = self.genealogy

        # Vérifier que la personne existe
        person = self.get_person(event_data.person_id)
        if person is None:
            raise ValueError(f"Personne avec l'ID {event_data.person_id} non trouvée")

        witness_dicts: List[Dict[str, Any]] = []
        for w in event_data.witnesses or []:
            witness_dicts.append({"person_id": str(w)})

        # Création de l'événement
        event = PersonalEvent(
            event_type=event_data.event_type,
            date=parse_api_date_string(event_data.date),
            place=event_data.place,
            notes=[event_data.note] if event_data.note else [],
            witnesses=witness_dicts,
        )

        # Ajout à la personne
        person.events.append(event)
        genealogy.metadata.modified_date = datetime.now()
        self._invalidate_caches()

        return event

    def create_family_event(self, event_data: FamilyEventCreateSchema) -> FamilyEvent:
        """
        Crée un nouvel événement familial.

        Args:
            event_data: Données de l'événement à créer

        Returns:
            FamilyEvent: Événement créé
        """
        genealogy = self.genealogy

        # Vérifier que la famille existe
        family = self.get_family(event_data.family_id)
        if family is None:
            raise ValueError(f"Famille avec l'ID {event_data.family_id} non trouvée")

        witness_dicts: List[Dict[str, Any]] = []
        for w in event_data.witnesses or []:
            witness_dicts.append({"person_id": str(w)})
        source_val: Optional[str] = None
        if event_data.sources:
            for s in event_data.sources:
                if s and str(s).strip():
                    source_val = str(s).strip()
                    break

        # Création de l'événement
        event = FamilyEvent(
            event_type=EventType.MARRIAGE,
            family_event_type=event_data.event_type,
            date=parse_api_date_string(event_data.date),
            place=event_data.place,
            reason=event_data.reason,
            notes=[event_data.note] if event_data.note else [],
            witnesses=witness_dicts,
            source=source_val,
        )

        # Ajout à la famille
        family.events.append(event)
        genealogy.metadata.modified_date = datetime.now()
        self._invalidate_caches()

        return event

    def get_event(self, event_id: str) -> Optional[Event]:
        """
        Récupère un événement par son ID.

        Args:
            event_id: Identifiant de l'événement

        Returns:
            Event: Événement trouvé ou None
        """
        genealogy = self.genealogy

        # Recherche dans les événements personnels
        for person in genealogy.persons.values():
            for idx, pev in enumerate(person.events):
                uid = getattr(pev, "unique_id", None)
                if uid is not None and uid == event_id:
                    return pev
                if (
                    stable_event_id(
                        pev, scope="person", scope_key=person.unique_id, index=idx
                    )
                    == event_id
                ):
                    return pev

        # Recherche dans les événements familiaux
        for family in genealogy.families.values():
            for idx, fev in enumerate(family.events):
                uid = getattr(fev, "unique_id", None)
                if uid is not None and uid == event_id:
                    return fev
                if (
                    stable_event_id(
                        fev, scope="family", scope_key=family.family_id, index=idx
                    )
                    == event_id
                ):
                    return fev

        return None

    def get_event_context(
        self, event: Event
    ) -> Tuple[Optional[str], Optional[str], int]:
        """Identifie la personne ou la famille et l'indice d'un événement en mémoire."""
        genealogy = self.genealogy
        for person in genealogy.persons.values():
            for idx, ev in enumerate(person.events):
                if ev is event:
                    return person.unique_id, None, idx
        for family in genealogy.families.values():
            for idx, fev in enumerate(family.events):
                if fev is event:
                    return None, family.family_id, idx
        return None, None, -1

    def update_event(
        self, event_id: str, event_data: EventUpdateSchema
    ) -> Optional[Event]:
        """
        Met à jour un événement.

        Args:
            event_id: Identifiant de l'événement
            event_data: Nouvelles données

        Returns:
            Event: Événement mis à jour ou None si non trouvé
        """
        genealogy = self.genealogy
        event = self.get_event(event_id)

        if event is None:
            return None

        if event_data.event_type is not None:
            et = event_data.event_type
            if isinstance(event, FamilyEvent):
                if isinstance(et, FamilyEventType):
                    event.family_event_type = et
                    mapping = {
                        FamilyEventType.MARRIAGE: EventType.MARRIAGE,
                        FamilyEventType.DIVORCE: EventType.DIVORCE,
                        FamilyEventType.SEPARATION: EventType.SEPARATION,
                        FamilyEventType.ENGAGEMENT: EventType.ENGAGEMENT,
                        FamilyEventType.PACS: EventType.PACS,
                    }
                    event.event_type = mapping.get(et, event.event_type)
                elif isinstance(et, EventType):
                    event.event_type = et
            elif isinstance(et, EventType):
                event.event_type = et
        if event_data.date is not None:
            event.date = parse_api_date_string(event_data.date)
        if event_data.place is not None:
            event.place = event_data.place
        if event_data.reason is not None:
            event.reason = event_data.reason
        if event_data.note is not None:
            event.notes = [event_data.note] if event_data.note else []
        if event_data.witnesses is not None:
            event.witnesses = [{"person_id": str(w)} for w in event_data.witnesses]
        if event_data.sources is not None:
            first_src: Optional[str] = None
            for s in event_data.sources:
                if s and str(s).strip():
                    first_src = str(s).strip()
                    break
            event.source = first_src

        genealogy.metadata.modified_date = datetime.now()
        self._invalidate_caches()
        return event

    def delete_event(self, event_id: str) -> bool:
        """
        Supprime un événement.

        Args:
            event_id: Identifiant de l'événement

        Returns:
            bool: True si supprimé, False si non trouvé
        """
        genealogy = self.genealogy

        # Recherche et suppression dans les événements personnels
        for person in genealogy.persons.values():
            for i, pev in enumerate(person.events):
                uid = getattr(pev, "unique_id", None)
                if uid is not None and uid == event_id:
                    del person.events[i]
                    self._invalidate_caches()
                    genealogy.metadata.modified_date = datetime.now()
                    return True
                if (
                    stable_event_id(
                        pev, scope="person", scope_key=person.unique_id, index=i
                    )
                    == event_id
                ):
                    del person.events[i]
                    self._invalidate_caches()
                    genealogy.metadata.modified_date = datetime.now()
                    return True

        # Recherche et suppression dans les événements familiaux
        for family in genealogy.families.values():
            for i, fev in enumerate(family.events):
                uid = getattr(fev, "unique_id", None)
                if uid is not None and uid == event_id:
                    del family.events[i]
                    self._invalidate_caches()
                    genealogy.metadata.modified_date = datetime.now()
                    return True
                if (
                    stable_event_id(
                        fev, scope="family", scope_key=family.family_id, index=i
                    )
                    == event_id
                ):
                    del family.events[i]
                    self._invalidate_caches()
                    genealogy.metadata.modified_date = datetime.now()
                    return True

        return False

    def _hit_label(self, hit: "EventSearchHit") -> str:
        """Nom(s) affichés pour un résultat : personne, ou époux d'une famille."""
        genealogy = self.genealogy
        ids: List[Optional[str]] = []
        if hit.person_id is not None:
            ids = [hit.person_id]
        elif hit.family_id is not None:
            fam = genealogy.families.get(hit.family_id)
            if fam is not None:
                ids = [fam.husband_id, fam.wife_id]
        names: List[str] = []
        for pid in ids:
            person = genealogy.persons.get(pid) if pid else None
            if person is not None:
                names.append(f"{person.first_name} {person.last_name}")
        return " ".join(names)

    def search_events(
        self, search_params: Dict[str, Any]
    ) -> Tuple[List[EventSearchHit], int]:
        """
        Recherche des événements selon les critères.

        Args:
            search_params: Paramètres de recherche

        Returns:
            Tuple[List[EventSearchHit], int]: (résultats avec contexte, nombre total)
        """
        genealogy = self.genealogy
        hits: List[EventSearchHit] = []

        for person in genealogy.persons.values():
            for idx, pev in enumerate(person.events):
                hits.append(
                    EventSearchHit(
                        event=pev,
                        person_id=person.unique_id,
                        family_id=None,
                        index=idx,
                    )
                )

        for family in genealogy.families.values():
            for idx, fev in enumerate(family.events):
                hits.append(
                    EventSearchHit(
                        event=fev,
                        person_id=None,
                        family_id=family.family_id,
                        index=idx,
                    )
                )

        # Filtrage par critères
        if search_params.get("query"):
            query_lower = search_params["query"].lower()

            def _match_notes(notes: List[str]) -> bool:
                return any(query_lower in (n or "").lower() for n in notes)

            hits = [
                h
                for h in hits
                if (
                    query_lower in (h.event.place or "").lower()
                    or query_lower in (h.event.reason or "").lower()
                    or _match_notes(h.event.notes)
                )
            ]

        wanted_types = {
            str(getattr(t, "value", t))
            for t in (
                [search_params["event_type"]] if search_params.get("event_type") else []
            )
            + list(search_params.get("event_types") or [])
        }
        if wanted_types:
            hits = [h for h in hits if _api_event_type_value(h.event) in wanted_types]

        if search_params.get("person_id"):
            pid = search_params["person_id"]
            hits = [h for h in hits if h.person_id == pid]

        if search_params.get("family_id"):
            fid = search_params["family_id"]
            hits = [h for h in hits if h.family_id == fid]

        if search_params.get("place"):
            needle = _normalize_search_text(search_params["place"])
            hits = [
                h for h in hits if needle in _normalize_search_text(h.event.place or "")
            ]

        if search_params.get("related_to"):
            related = self.get_related_person_ids(
                search_params["related_to"], int(search_params.get("degree", 1))
            )
            related_pids = set(related["person_ids"])
            related_fids = set(related["family_ids"])
            witness_pid = related["witness_person_id"]
            hits = [
                h
                for h in hits
                if h.person_id in related_pids
                or h.family_id in related_fids
                or witness_pid in event_witnesses_to_api_strings(h.event.witnesses)
            ]

        if search_params.get("family_name"):
            name_needle = _normalize_search_text(search_params["family_name"])
            hits = [
                h
                for h in hits
                if name_needle in _normalize_search_text(self._hit_label(h))
            ]

        if search_params.get("has_witnesses") is not None:
            if search_params["has_witnesses"]:
                hits = [h for h in hits if len(h.event.witnesses) > 0]
            else:
                hits = [h for h in hits if len(h.event.witnesses) == 0]

        if search_params.get("has_sources") is not None:
            if search_params["has_sources"]:
                hits = [
                    h
                    for h in hits
                    if h.event.source is not None and str(h.event.source).strip()
                ]
            else:
                hits = [
                    h
                    for h in hits
                    if not (h.event.source and str(h.event.source).strip())
                ]

        total = len(hits)

        # Pagination
        page = search_params.get("page", 1)
        size = search_params.get("size", 20)
        start = (page - 1) * size
        end = start + size
        hits = hits[start:end]

        return hits, total

    # === VALIDATION ===

    def validate_genealogy(self, strict: bool = False) -> Dict[str, Any]:
        """
        Valide la cohérence des références personnes/familles.

        Args:
            strict: Si True, met à jour ``is_valid`` et ``validation_errors`` sur
                l'objet ``Genealogy`` lorsque des erreurs sont trouvées (liste
                remplacée à chaque passe en mode strict).

        Returns:
            Dictionnaire sérialisable pour l'API (erreurs, indicateur de validité).

        Note:
            En mode non strict (défaut pour l'endpoint HTTP), les erreurs sont
            uniquement retournées sans modifier l'état de validation stocké.
        """
        genealogy = self.genealogy
        errors_list = genealogy.validate_consistency(strict=strict)
        error_payloads = [err.to_dict() for err in errors_list]
        suggestions: List[str] = []
        if error_payloads:
            suggestions.append(
                "Vérifiez que chaque identifiant cité dans une famille existe "
                "parmi les personnes chargées."
            )
        return {
            "is_valid": len(error_payloads) == 0,
            "warnings": [],
            "errors": error_payloads,
            "suggestions": suggestions,
        }

    # === GRAPHE DE PARENTÉ ===

    def _get_witness_index(self) -> Dict[str, set]:
        """Returns {witness_id: set_of_person_ids_whose_events_they_witnessed}.

        Lazy-computed and cached on first call.
        """
        if self._witness_index is not None:
            return self._witness_index
        index: Dict[str, set] = {}
        genealogy = self.genealogy
        for person in genealogy.persons.values():
            for event in person.events:
                for wid in event_witnesses_to_api_strings(event.witnesses):
                    index.setdefault(wid, set()).add(person.unique_id)
        for family in genealogy.families.values():
            for family_event in family.events:
                for wid in event_witnesses_to_api_strings(family_event.witnesses):
                    for pid in [family.husband_id, family.wife_id]:
                        if pid:
                            index.setdefault(wid, set()).add(pid)
        self._witness_index = index
        return self._witness_index

    def _invalidate_caches(self) -> None:
        """Invalide les caches dérivés après une écriture.

        Les organisations inférées sont retirées : leurs liens désignent les
        événements par position et seraient faux après une modification.
        Elles sont recalculées au prochain accès à l'index des candidats.
        """
        self._witness_index = None
        self._candidate_index = None
        self._shared_experiences = None
        self._unmatched = None
        self._export_summary = None
        if self._orgs_inferred:
            self.genealogy.organizations.clear()
            self.genealogy.organization_links.clear()
            self._orgs_inferred = False

    def get_candidate_index(self) -> CandidateIndex:
        """Index des organisations candidates (calculé une fois, invalidé à l'écriture)."""
        if self._candidate_index is None:
            if not self.genealogy.organizations:
                self._orgs_inferred = True  # build_candidate_index va inférer
            self._candidate_index = build_candidate_index(
                self.genealogy, self._ignored_words
            )
        return self._candidate_index

    def get_shared_experiences(self) -> SharedExperienceIndex:
        """Expériences proches (calculées une fois, invalidées comme l'index des candidats)."""
        if self._shared_experiences is None:
            index = self.get_candidate_index()
            self._shared_experiences = find_shared_experiences(
                self.genealogy, index.matched, set(self._ignored_words)
            )
        return self._shared_experiences

    def get_unmatched(self) -> Tuple[int, List[UnmatchedGroup]]:
        """Reste à classer ``(total, groupes)`` : sans organisations ni expériences proches."""
        if self._unmatched is None:
            index = self.get_candidate_index()
            experiences = self.get_shared_experiences()
            exclude = set(index.matched)
            for exp in experiences.items:
                exclude.update((ev.person_id, ev.event_index) for ev in exp.events)
            self._unmatched = build_unmatched(
                self.genealogy, exclude, self._ignored_words
            )
        return self._unmatched

    def export_bundle(self, now: datetime) -> Tuple[str, bytes]:
        """Archive d'export de la session : ``(nom, octets)``."""
        return build_export_bundle(
            self.genealogy,
            self.get_candidate_index(),
            self.get_shared_experiences(),
            self._ignored_words,
            self._source_name,
            now,
        )

    def export_summary(self) -> Dict[str, int]:
        """Comptes de la ligne de résumé, tirés des mêmes tables que l'archive.

        Mis en cache comme l'index des candidats : invalidé à l'écriture et au
        changement des mots ignorés.
        """
        if self._export_summary is not None:
            return dict(self._export_summary)
        tables = {
            t.spec.name: len(t.rows)
            for t in build_organization_tables(
                self.genealogy,
                self.get_candidate_index(),
                self.get_shared_experiences(),
                self._ignored_words,
            )
        }
        self._export_summary = {
            "personnes": len(self.genealogy.persons),
            "organisations": tables["organisations"],
            "a_classer": tables["reste_a_classer"],
            "pistes": tables["pistes"],
        }
        return dict(self._export_summary)

    @property
    def ignored_words(self) -> Tuple[str, ...]:
        """Mots qui écartent un événement « Autre » des organisations candidates."""
        return self._ignored_words

    def set_ignored_words(self, words: Iterable[str]) -> Tuple[str, ...]:
        """Remplace les mots ignorés (normalisés) et invalide l'index des candidats."""
        normalized = normalize_ignored_words(words)
        if normalized != self._ignored_words:
            self._ignored_words = normalized
            self._candidate_index = None
            self._shared_experiences = None
            self._unmatched = None
            self._export_summary = None
        return self._ignored_words

    def get_related_person_ids(self, person_id: str, degree: int) -> Dict[str, Any]:
        """Returns person_ids and family_ids related to person_id up to the given degree.

        Degree 1: self + spouses + families_as_spouse
        Degree 2: + parents, children, siblings
        Degree 3: + persons whose events person_id witnessed
        """
        genealogy = self.genealogy
        person = genealogy.persons.get(person_id)
        if person is None:
            return {
                "person_ids": [],
                "family_ids": [],
                "witness_person_id": person_id,
            }

        person_ids: set = {person_id}
        family_ids: set = set(person.families_as_spouse)

        # Degree 1: include spouses
        for fam_id in person.families_as_spouse:
            fam = genealogy.families.get(fam_id)
            if fam is not None:
                if fam.husband_id:
                    person_ids.add(fam.husband_id)
                if fam.wife_id:
                    person_ids.add(fam.wife_id)

        if degree >= 2:
            # Parents and siblings (via families_as_child)
            for fam_id in person.families_as_child:
                fam = genealogy.families.get(fam_id)
                if fam is not None:
                    if fam.husband_id:
                        person_ids.add(fam.husband_id)
                    if fam.wife_id:
                        person_ids.add(fam.wife_id)
                    for child in fam.children:
                        person_ids.add(child.person_id)
            # Children (via families_as_spouse)
            for fam_id in person.families_as_spouse:
                fam = genealogy.families.get(fam_id)
                if fam is not None:
                    for child in fam.children:
                        person_ids.add(child.person_id)

        if degree >= 3:
            witness_index = self._get_witness_index()
            person_ids.update(witness_index.get(person_id, set()))

        return {
            "person_ids": list(person_ids),
            "family_ids": list(family_ids),
            "witness_person_id": person_id,
        }

    # === STATISTIQUES ===

    def get_stats(self) -> Dict[str, Any]:
        """
        Récupère les statistiques de la généalogie.

        Returns:
            Dict[str, Any]: Statistiques détaillées
        """
        genealogy = self.genealogy

        # Statistiques des personnes
        persons_by_sex: Dict[str, int] = {}
        persons_by_access: Dict[str, int] = {}
        persons_with_birth_date = 0
        persons_with_death_date = 0

        for person in genealogy.persons.values():
            # Par sexe
            sex_key = person.gender.value if person.gender else "unknown"
            persons_by_sex[sex_key] = persons_by_sex.get(sex_key, 0) + 1

            # Par niveau d'accès
            access_key = person.access_level.value if person.access_level else "default"
            persons_by_access[access_key] = persons_by_access.get(access_key, 0) + 1

            # Dates
            if person.birth_date:
                persons_with_birth_date += 1
            if person.death_date:
                persons_with_death_date += 1

        # Statistiques des familles
        families_by_status: Dict[str, int] = {}
        families_with_children = 0
        total_children = 0

        for family in genealogy.families.values():
            # Par statut
            status_key = (
                family.marriage_status.value if family.marriage_status else "married"
            )
            families_by_status[status_key] = families_by_status.get(status_key, 0) + 1

            # Enfants
            if len(family.children) > 0:
                families_with_children += 1
            total_children += len(family.children)

        # Statistiques des événements (collectés depuis les personnes et familles)
        events_by_type: Dict[str, int] = {}
        personal_events = 0
        family_events = 0

        # Compter les événements personnels
        for person in genealogy.persons.values():
            for event in person.events:
                type_key = event.event_type.value if event.event_type else "unknown"
                events_by_type[type_key] = events_by_type.get(type_key, 0) + 1
                personal_events += 1

        # Compter les événements familiaux
        for family in genealogy.families.values():
            for family_event in family.events:
                # Même clé que l'onglet Événements (type familial : nmen, marc…).
                type_key = _api_event_type_value(family_event)
                events_by_type[type_key] = events_by_type.get(type_key, 0) + 1
                family_events += 1

        base_stats = {
            "total_persons": len(genealogy.persons),
            "total_families": len(genealogy.families),
            "total_events": personal_events + family_events,
            "persons_by_sex": persons_by_sex,
            "persons_by_access_level": persons_by_access,
            "persons_with_birth_date": persons_with_birth_date,
            "persons_with_death_date": persons_with_death_date,
            "families_by_status": families_by_status,
            "families_with_children": families_with_children,
            "average_children_per_family": (
                total_children / len(genealogy.families) if genealogy.families else 0
            ),
            "events_by_type": events_by_type,
            "personal_events": personal_events,
            "family_events": family_events,
            "metadata": {
                "source_file": genealogy.metadata.source_file,
                "created": (
                    genealogy.metadata.created_date.isoformat()
                    if genealogy.metadata.created_date
                    else None
                ),
                "updated": (
                    genealogy.metadata.modified_date.isoformat()
                    if genealogy.metadata.modified_date
                    else None
                ),
                "version": genealogy.metadata.geneweb_version,
                "encoding": genealogy.metadata.encoding,
            },
        }
        base_stats["advanced"] = _build_advanced_genealogy_stats(genealogy)
        base_stats["persons_by_birth_century"] = count_by_birth_century(genealogy)
        base_stats["families_by_marriage_century"] = count_marriage_century(genealogy)
        base_stats["events_by_century"] = count_event_century(genealogy)
        fb_dates = family_events_breakdown(genealogy)
        base_stats["families_with_marriage_date"] = fb_dates["with_marriage_date"]
        base_stats["families_with_divorce_date"] = fb_dates["with_divorce_date"]
        return base_stats


def _person_year_in_range(
    date_val: Optional[Date],
    year_from: Optional[int],
    year_to: Optional[int],
) -> bool:
    """Indique si au moins une année candidate chevauche ``[year_from, year_to]``.

    Pour les dates OR (``|``) ou BETWEEN (``..``), les années du segment principal
    et des ``alternative_dates`` sont prises en compte (chevauchement / overlap).
    """
    if year_from is None and year_to is None:
        return True
    if date_val is None:
        return False
    years = date_val.filter_years_for_range()
    if not years:
        return False
    for year in years:
        if year_from is not None and year < year_from:
            continue
        if year_to is not None and year > year_to:
            continue
        return True
    return False


def _normalize_place_fragment(text: str) -> str:
    """Normalisation NFKC + casefold pour comparaison de lieux."""
    return unicodedata.normalize("NFKC", text).casefold()


def _person_matches_place(person: Person, needle_normalized: str) -> bool:
    """Vérifie si ``needle_normalized`` est une sous-chaîne d'un lieu connu.

    Comparaison naive après NFKC et casefold (pas de collation locale).
    """
    fields = (
        person.birth_place,
        person.death_place,
        person.baptism_place,
        person.burial_place,
    )
    for raw in fields:
        if raw and needle_normalized in _normalize_place_fragment(raw):
            return True
    return False


def _build_advanced_genealogy_stats(genealogy: Genealogy) -> Dict[str, Any]:
    """Construit des statistiques complémentaires.

    Inclut longévité (âge au décès), répartition géographique (lieux fréquents)
    et distribution des tailles de famille (histogramme du nombre d'enfants).
    """
    persons = list(genealogy.persons.values())
    ages_at_death: List[int] = []
    for p in persons:
        if p.age_at_death is not None:
            ages_at_death.append(int(p.age_at_death))

    longevity: Dict[str, Any] = {
        "count_with_age_at_death": len(ages_at_death),
        "average_age_at_death": None,
        "min_age_at_death": None,
        "max_age_at_death": None,
    }
    if ages_at_death:
        longevity["average_age_at_death"] = sum(ages_at_death) / len(ages_at_death)
        longevity["min_age_at_death"] = min(ages_at_death)
        longevity["max_age_at_death"] = max(ages_at_death)

    birth_places = _top_places_from_persons(persons, "birth_place", limit=15)
    death_places = _top_places_from_persons(persons, "death_place", limit=15)

    child_counts = [len(f.children) for f in genealogy.families.values()]
    distribution: Dict[str, int] = {"0": 0, "1": 0, "2": 0, "3": 0, "4+": 0}
    for n in child_counts:
        if n <= 3:
            distribution[str(n)] += 1
        else:
            distribution["4+"] += 1

    family_sizes: Dict[str, Any] = {
        "max_children_per_family": max(child_counts) if child_counts else 0,
        "min_children_per_family": min(child_counts) if child_counts else 0,
        "children_per_family_histogram": distribution,
    }

    return {
        "births_by_decade": _births_by_decade(persons),
        "top_surnames": _top_surnames(persons, limit=15),
        "coverage": _coverage(persons),
        "longevity": longevity,
        "geography": {
            "distinct_birth_places": _distinct_places(persons, "birth_place"),
            "top_birth_places": birth_places,
            "top_death_places": death_places,
        },
        "family_sizes": family_sizes,
    }


_SOURCE_ATTRS = (
    "birth_source",
    "death_source",
    "baptism_source",
    "burial_source",
    "person_source",
)


def _births_by_decade(persons: List[Person]) -> Dict[str, int]:
    """Naissances datées par décennie (« 1850 » = 1850-1859), en ordre chronologique."""
    counts: Dict[int, int] = {}
    for person in persons:
        year = person.birth_date.sort_year() if person.birth_date else None
        if year is None or year <= 0:
            continue
        decade = year - year % 10
        counts[decade] = counts.get(decade, 0) + 1
    return {str(decade): counts[decade] for decade in sorted(counts)}


def _top_surnames(persons: List[Person], limit: int) -> List[Dict[str, Any]]:
    """Patronymes les plus portés (comparaison insensible à la casse ; ``?`` exclu)."""
    counts: Dict[str, int] = {}
    label_for_key: Dict[str, str] = {}
    for person in persons:
        surname = (person.last_name or "").strip()
        if not surname or surname == "?":
            continue
        key = surname.casefold()
        counts[key] = counts.get(key, 0) + 1
        label_for_key.setdefault(key, surname)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [
        {"surname": label_for_key[key], "count": count}
        for key, count in ordered[:limit]
    ]


def _coverage(persons: List[Person]) -> Dict[str, int]:
    """Nombre de personnes renseignées pour chaque information clé."""
    return {
        "persons": len(persons),
        "with_birth_date": sum(1 for p in persons if p.birth_date),
        "with_birth_place": sum(1 for p in persons if (p.birth_place or "").strip()),
        "with_death_date": sum(1 for p in persons if p.death_date),
        "with_occupation": sum(1 for p in persons if (p.occupation or "").strip()),
        "with_source": sum(
            1
            for p in persons
            if any((getattr(p, attr) or "").strip() for attr in _SOURCE_ATTRS)
        ),
    }


def _person_cities(persons: Iterable[Any], attr: str) -> Iterator[str]:
    """Villes de l'attribut lieu ``attr`` (complément et précisions après la virgule exclus)."""
    for person in persons:
        raw = getattr(person, attr, None)
        city = place_city(str(raw)) if raw is not None else None
        if city:
            yield city


def _distinct_places(persons: Iterable[Any], attr: str) -> int:
    """Nombre de villes distinctes (sans tenir compte des majuscules)."""
    return len({city.lower() for city in _person_cities(persons, attr)})


def _top_places_from_persons(
    persons: Iterable[Any], attr: str, limit: int
) -> List[Dict[str, Any]]:
    """Villes les plus fréquentes pour l'attribut lieu ``attr`` (« Lille, Nord » compte
    pour « Lille », « [Maternité] - Lille » aussi)."""
    counts: Dict[str, int] = {}
    label_for_key: Dict[str, str] = {}
    for place in _person_cities(persons, attr):
        key = place.lower()
        counts[key] = counts.get(key, 0) + 1
        if key not in label_for_key:
            label_for_key[key] = place
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [
        {"place": label_for_key[key], "count": count} for key, count in ordered[:limit]
    ]
