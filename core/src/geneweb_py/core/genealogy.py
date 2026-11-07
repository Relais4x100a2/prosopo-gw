"""
Modèle Genealogy : conteneur principal des données généalogiques

Ce module définit la classe principale qui regroupe toutes les personnes,
familles et métadonnées d'une base généalogique GeneWeb.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .date import Date
from .exceptions import GeneWebError, GeneWebValidationError
from .family import Family
from .organization import Organization, OrganizationLink
from .person import Person

if TYPE_CHECKING:
    from .event_to_organization import EventToOrganizationMapper


@dataclass
class GenealogyMetadata:
    """Métadonnées de la base généalogique"""

    # Informations sur le fichier source
    source_file: str | None = None
    encoding: str = "iso-8859-1"
    is_gwplus: bool = False

    # Informations de création
    created_date: datetime | None = None
    modified_date: datetime | None = None
    geneweb_version: str | None = None

    # Notes de base de données
    database_notes: list[str] = field(default_factory=list)

    # Pages étendues
    extended_pages: dict[str, str] = field(default_factory=dict)

    # Notes de wizard
    wizard_notes: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class Genealogy:
    """Conteneur principal pour toutes les données généalogiques

    Cette classe regroupe les personnes, familles et métadonnées
    d'une base généalogique GeneWeb complète.
    """

    # Collections principales
    persons: dict[str, Person] = field(default_factory=dict)
    families: dict[str, Family] = field(default_factory=dict)

    # Métadonnées
    metadata: GenealogyMetadata = field(default_factory=GenealogyMetadata)

    # Validation gracieuse
    is_valid: bool = field(default=True)
    validation_errors: list[GeneWebError] = field(default_factory=list)

    # Organisations (entreprises, écoles, associations…) et leurs liens aux personnes
    organizations: dict[str, Organization] = field(default_factory=dict)
    organization_links: list[OrganizationLink] = field(default_factory=list)

    # Statistiques (calculées automatiquement)
    _stats_cache: dict[str, Any] = field(default_factory=dict, init=False)

    def __post_init__(self):
        """Validation et initialisation après création"""
        # Mettre à jour les références croisées
        self._update_cross_references()

        # Calculer les statistiques
        self._calculate_stats()

    def add_person(self, person: Person) -> None:
        """Ajoute une personne à la généalogie

        Args:
            person: Personne à ajouter

        Raises:
            GeneWebValidationError: Si la personne existe déjà
        """
        person_id = person.unique_id

        if person_id in self.persons:
            raise GeneWebValidationError(
                f"Personne '{person_id}' déjà présente dans la généalogie"
            )

        self.persons[person_id] = person
        self._invalidate_stats_cache()

    def add_or_update_person(self, person: Person) -> Person:
        """Ajoute une personne ou met à jour si elle existe déjà

        Cette méthode gère intelligemment les cas où une personne apparaît
        plusieurs fois dans le fichier GeneWeb (comme témoin, dans des notes, etc.).
        Si la personne existe déjà, les informations sont fusionnées.

        Args:
            person: Personne à ajouter ou mettre à jour

        Returns:
            La personne ajoutée ou mise à jour (référence existante si doublon)
        """
        person_id = person.unique_id

        if person_id in self.persons:
            # La personne existe déjà, fusionner les informations
            existing = self.persons[person_id]

            # Fusionner le sexe (priorité au sexe connu)
            from .person import Gender

            if person.gender != Gender.UNKNOWN and existing.gender == Gender.UNKNOWN:
                existing.gender = person.gender

            # Fusionner les informations si la nouvelle personne a plus de détails
            if person.birth_date and not existing.birth_date:
                existing.birth_date = person.birth_date
            if person.birth_place and not existing.birth_place:
                existing.birth_place = person.birth_place
            if person.death_date and not existing.death_date:
                existing.death_date = person.death_date
            if person.death_place and not existing.death_place:
                existing.death_place = person.death_place
            if person.baptism_date and not existing.baptism_date:
                existing.baptism_date = person.baptism_date
            if person.baptism_place and not existing.baptism_place:
                existing.baptism_place = person.baptism_place
            if person.occupation and not existing.occupation:
                existing.occupation = person.occupation
            if person.public_name and not existing.public_name:
                existing.public_name = person.public_name
            if person.nickname and not existing.nickname:
                existing.nickname = person.nickname

            if existing.start_line is None and person.start_line is not None:
                existing.start_line = person.start_line
                existing.end_line = person.end_line

            # Fusionner les événements (éviter les doublons)
            for event in person.events:
                if event not in existing.events:
                    existing.events.append(event)

            # Fusionner les notes
            for note in person.notes:
                if note not in existing.notes:
                    existing.notes.append(note)

            # Fusionner les sources spécifiques
            if person.birth_source and not existing.birth_source:
                existing.birth_source = person.birth_source
            if person.death_source and not existing.death_source:
                existing.death_source = person.death_source
            if person.baptism_source and not existing.baptism_source:
                existing.baptism_source = person.baptism_source
            if person.burial_source and not existing.burial_source:
                existing.burial_source = person.burial_source
            if person.person_source and not existing.person_source:
                existing.person_source = person.person_source

            return existing
        else:
            # Nouvelle personne, l'ajouter
            self.persons[person_id] = person
            self._invalidate_stats_cache()
            return person

    def add_family(self, family: Family) -> None:
        """Ajoute une famille à la généalogie

        Args:
            family: Famille à ajouter

        Raises:
            GeneWebValidationError: Si la famille existe déjà
        """
        if family.family_id in self.families:
            raise GeneWebValidationError(
                f"Famille '{family.family_id}' déjà présente dans la généalogie"
            )

        self.families[family.family_id] = family
        self._invalidate_stats_cache()

    def find_person(
        self, last_name: str, first_name: str, occurrence: int = 0
    ) -> Person | None:
        """Recherche une personne par nom

        Args:
            last_name: Nom de famille
            first_name: Prénom
            occurrence: Numéro d'occurrence (0 par défaut)

        Returns:
            Personne trouvée ou None
        """
        person_id = f"{last_name}_{first_name}_{occurrence}"
        return self.persons.get(person_id)

    def find_person_by_id(self, person_id: str) -> Person | None:
        """Recherche une personne par ID unique

        Args:
            person_id: ID unique de la personne

        Returns:
            Personne trouvée ou None
        """
        return self.persons.get(person_id)

    def find_family(self, family_id: str) -> Family | None:
        """Recherche une famille par ID

        Args:
            family_id: ID de la famille

        Returns:
            Famille trouvée ou None
        """
        return self.families.get(family_id)

    def get_families_for_person(self, person_id: str) -> list[Family]:
        """Retourne toutes les familles d'une personne

        Args:
            person_id: ID de la personne

        Returns:
            Liste des familles (comme parent ou enfant)
        """
        families = []

        for family in self.families.values():
            if family.is_member(person_id):
                families.append(family)

        return families

    def get_children(self, person_id: str) -> list[Person]:
        """Retourne tous les enfants d'une personne

        Args:
            person_id: ID de la personne

        Returns:
            Liste des enfants
        """
        children = []

        for family in self.families.values():
            if family.is_parent(person_id):
                for child_id in family.child_ids:
                    child = self.find_person_by_id(child_id)
                    if child:
                        children.append(child)

        return children

    def get_parents(self, person_id: str) -> list[Person]:
        """Retourne les parents d'une personne

        Args:
            person_id: ID de la personne

        Returns:
            Liste des parents (père et/ou mère)
        """
        parents = []

        for family in self.families.values():
            if family.is_child(person_id):
                for parent_id in family.spouse_ids:
                    parent = self.find_person_by_id(parent_id)
                    if parent:
                        parents.append(parent)
                break  # Une personne n'a qu'une seule famille parentale

        return parents

    def get_siblings(self, person_id: str) -> list[Person]:
        """Retourne les frères et sœurs d'une personne

        Args:
            person_id: ID de la personne

        Returns:
            Liste des frères et sœurs
        """
        siblings = []

        for family in self.families.values():
            if family.is_child(person_id):
                for sibling_id in family.child_ids:
                    if sibling_id != person_id:
                        sibling = self.find_person_by_id(sibling_id)
                        if sibling:
                            siblings.append(sibling)
                break

        return siblings

    def get_spouses(self, person_id: str) -> list[Person]:
        """Retourne tous les conjoints d'une personne

        Args:
            person_id: ID de la personne

        Returns:
            Liste des conjoints
        """
        spouses = []

        for family in self.families.values():
            if family.is_parent(person_id):
                spouse_id = family.spouse(person_id)
                if spouse_id:
                    spouse = self.find_person_by_id(spouse_id)
                    if spouse:
                        spouses.append(spouse)

        return spouses

    def validate_consistency(self, strict: bool = True) -> list[GeneWebValidationError]:
        """Valide la cohérence des données généalogiques

        Args:
            strict: Si True, met à jour ``is_valid`` et ``validation_errors`` pour
                refléter exclusivement les erreurs de cette passe (idempotent si
                l'endpoint est rappelé plusieurs fois avec les mêmes données).

        Returns:
            Liste des erreurs de validation trouvées
        """
        errors = []

        # Vérifier les références de personnes dans les familles
        for family in self.families.values():
            # Vérifier les époux
            if family.husband_id and family.husband_id not in self.persons:
                errors.append(
                    GeneWebValidationError(
                        f"Époux '{family.husband_id}' de la famille '{family.family_id}' non trouvé"  # noqa: E501
                    )
                )

            if family.wife_id and family.wife_id not in self.persons:
                errors.append(
                    GeneWebValidationError(
                        f"Épouse '{family.wife_id}' de la famille '{family.family_id}' non trouvée"  # noqa: E501
                    )
                )

            # Vérifier les enfants
            for child_id in family.child_ids:
                if child_id not in self.persons:
                    errors.append(
                        GeneWebValidationError(
                            f"Enfant '{child_id}' de la famille '{family.family_id}' non trouvé"  # noqa: E501
                        )
                    )

        # Vérifier les références de familles dans les personnes
        for person in self.persons.values():
            for family_id in person.get_families():
                if family_id not in self.families:
                    errors.append(
                        GeneWebValidationError(
                            f"Famille '{family_id}' référencée par '{person.unique_id}' non trouvée"  # noqa: E501
                        )
                    )

        # Mettre à jour les attributs de validation (pas de cumul entre appels strict)
        if strict:
            self.validation_errors.clear()
            if errors:
                self.validation_errors.extend(errors)
                self.is_valid = False
            else:
                self.is_valid = True

        return errors

    def add_validation_error(self, error: GeneWebError) -> None:
        """Ajoute une erreur de validation à la généalogie

        Args:
            error: L'erreur à ajouter
        """
        self.validation_errors.append(error)
        self.is_valid = False

    def clear_validation_errors(self) -> None:
        """Efface toutes les erreurs de validation"""
        self.validation_errors.clear()
        self.is_valid = True

    def get_validation_summary(self) -> str:
        """Retourne un résumé des erreurs de validation

        Returns:
            Résumé textuel des erreurs
        """
        if self.is_valid:
            return "Généalogie valide"

        from .exceptions import ErrorSeverity

        # Compter par sévérité
        by_severity = {
            ErrorSeverity.WARNING: 0,
            ErrorSeverity.ERROR: 0,
            ErrorSeverity.CRITICAL: 0,
        }

        for error in self.validation_errors:
            by_severity[error.severity] += 1

        parts = []
        if by_severity[ErrorSeverity.WARNING] > 0:
            parts.append(f"{by_severity[ErrorSeverity.WARNING]} avertissement(s)")
        if by_severity[ErrorSeverity.ERROR] > 0:
            parts.append(f"{by_severity[ErrorSeverity.ERROR]} erreur(s)")
        if by_severity[ErrorSeverity.CRITICAL] > 0:
            parts.append(f"{by_severity[ErrorSeverity.CRITICAL]} erreur(s) critique(s)")

        return f"Généalogie avec erreurs: {', '.join(parts)}"

    def get_statistics(self) -> dict[str, Any]:
        """Retourne les statistiques de la généalogie

        Returns:
            Dictionnaire contenant diverses statistiques
        """
        if not self._stats_cache:
            self._calculate_stats()

        return self._stats_cache.copy()

    def _calculate_stats(self) -> None:
        """Calcule et met en cache les statistiques"""
        stats: dict[str, Any] = {
            "total_persons": len(self.persons),
            "total_families": len(self.families),
            "living_persons": sum(1 for p in self.persons.values() if p.is_alive),
            "deceased_persons": sum(1 for p in self.persons.values() if not p.is_alive),
            "unknown_status_persons": sum(
                1 for p in self.persons.values() if p.is_deceased is None
            ),
            "persons_with_birth_date": sum(
                1 for p in self.persons.values() if p.birth_date
            ),
            "persons_with_death_date": sum(
                1 for p in self.persons.values() if p.death_date
            ),
            "families_with_children": sum(
                1 for f in self.families.values() if f.children
            ),
            "total_children": sum(len(f.children) for f in self.families.values()),
        }

        # Statistiques par sexe
        stats["male_persons"] = sum(
            1 for p in self.persons.values() if p.gender.value == "m"
        )
        stats["female_persons"] = sum(
            1 for p in self.persons.values() if p.gender.value == "f"
        )
        stats["unknown_gender_persons"] = sum(
            1 for p in self.persons.values() if p.gender.value == "?"
        )

        # Âges
        ages = []
        for person in self.persons.values():
            if person.age_at_death is not None:
                ages.append(person.age_at_death)

        if ages:
            stats["average_age_at_death"] = sum(ages) / len(ages)
            stats["oldest_death"] = max(ages)
            stats["youngest_death"] = min(ages)

        self._stats_cache = stats

    def _invalidate_stats_cache(self) -> None:
        """Invalide le cache des statistiques"""
        self._stats_cache = {}

    def _update_cross_references(self) -> None:
        """Met à jour les références croisées entre personnes et familles"""
        # Mettre à jour les références des personnes vers les familles
        for person in self.persons.values():
            person.families_as_child.clear()
            person.families_as_spouse.clear()

        for family in self.families.values():
            # Mettre à jour les références des époux
            if family.husband_id:
                husband = self.find_person_by_id(family.husband_id)
                if husband:
                    husband.families_as_spouse.append(family.family_id)

            if family.wife_id:
                wife = self.find_person_by_id(family.wife_id)
                if wife:
                    wife.families_as_spouse.append(family.family_id)

            # Mettre à jour les références des enfants
            for child_id in family.child_ids:
                child = self.find_person_by_id(child_id)
                if child:
                    child.families_as_child.append(family.family_id)

    # ------------------------------------------------------------------
    # Organisations
    # ------------------------------------------------------------------

    def add_organization(self, organization: Organization) -> None:
        """Ajoute une organisation (identifiant unique obligatoire)"""
        if organization.id in self.organizations:
            raise GeneWebValidationError(
                f"Organisation déjà présente: {organization.id}",
                entity_type="organization",
                entity_id=organization.id,
            )
        self.organizations[organization.id] = organization

    def get_organization(self, organization_id: str) -> Organization | None:
        """Retourne l'organisation d'identifiant donné, ou ``None``"""
        return self.organizations.get(organization_id)

    def link_person_to_organization(
        self,
        person_id: str,
        organization_id: str,
        role: str | None = None,
        start_date: Date | None = None,
        end_date: Date | None = None,
        source_event_id: str | None = None,
        source_event_type: str | None = None,
        notes: list[str] | None = None,
    ) -> OrganizationLink:
        """Relie une personne à une organisation (les deux doivent exister)"""
        if person_id not in self.persons:
            raise GeneWebValidationError(
                f"Personne inconnue: {person_id}",
                entity_type="organization_link",
                entity_id=person_id,
            )
        if organization_id not in self.organizations:
            raise GeneWebValidationError(
                f"Organisation inconnue: {organization_id}",
                entity_type="organization_link",
                entity_id=organization_id,
            )
        link = OrganizationLink(
            person_id=person_id,
            organization_id=organization_id,
            role=role,
            start_date=start_date,
            end_date=end_date,
            source_event_id=source_event_id,
            source_event_type=source_event_type,
            notes=list(notes or []),
        )
        self.organization_links.append(link)
        return link

    def infer_organizations(
        self, mapper: "EventToOrganizationMapper | None" = None
    ) -> tuple[int, int]:
        """Déduit organisations et liens depuis les événements personnalisés.

        Sans ``mapper``, seules les règles déterministes s'appliquent.

        Returns:
            (organisations créées, liens créés)
        """
        from .event_to_organization import EventToOrganizationMapper

        return (mapper or EventToOrganizationMapper()).apply(self)

    def get_organization_links(
        self,
        person_id: str | None = None,
        organization_id: str | None = None,
    ) -> list[OrganizationLink]:
        """Liens filtrés par personne et/ou organisation"""
        return [
            link
            for link in self.organization_links
            if (person_id is None or link.person_id == person_id)
            and (organization_id is None or link.organization_id == organization_id)
        ]

    def get_person_organizations(self, person_id: str) -> list[Organization]:
        """Organisations d'une personne, sans doublon, dans l'ordre des liens"""
        seen: dict[str, Organization] = {}
        for link in self.get_organization_links(person_id=person_id):
            org = self.organizations.get(link.organization_id)
            if org is not None:
                seen.setdefault(org.id, org)
        return list(seen.values())

    def get_organization_members(self, organization_id: str) -> list[Person]:
        """Membres d'une organisation, sans doublon, dans l'ordre des liens"""
        seen: dict[str, Person] = {}
        for link in self.get_organization_links(organization_id=organization_id):
            person = self.persons.get(link.person_id)
            if person is not None:
                seen.setdefault(link.person_id, person)
        return list(seen.values())

    def validate_organizations(self) -> list[str]:
        """Contrôle les organisations : champs, parents existants, cycles, liens"""
        problems: list[str] = []
        for org in self.organizations.values():
            problems.extend(org.validate())
            if org.parent_id and org.parent_id not in self.organizations:
                problems.append(f"{org.id}: parent inconnu ({org.parent_id})")

        reported: set = set()
        for org in self.organizations.values():
            chain: list[str] = []
            current: str | None = org.id
            while current is not None and current in self.organizations:
                if current in chain:
                    cycle = frozenset(chain[chain.index(current) :])
                    if cycle not in reported:
                        reported.add(cycle)
                        problems.append(
                            "cycle de parenté: " + " -> ".join(chain + [current])
                        )
                    break
                chain.append(current)
                current = self.organizations[current].parent_id

        for link in self.organization_links:
            problems.extend(link.validate())
            if link.person_id not in self.persons:
                problems.append(f"lien vers une personne inconnue: {link.person_id}")
            if link.organization_id not in self.organizations:
                problems.append(
                    f"lien vers une organisation inconnue: {link.organization_id}"
                )
        return problems

    def to_dict(self) -> dict[str, Any]:
        """Convertit la généalogie en dictionnaire pour sérialisation"""
        data: dict[str, Any] = {
            "metadata": {
                "source_file": self.metadata.source_file,
                "encoding": self.metadata.encoding,
                "is_gwplus": self.metadata.is_gwplus,
                "database_notes": self.metadata.database_notes,
                "extended_pages": self.metadata.extended_pages,
            },
            "persons": {pid: person.to_dict() for pid, person in self.persons.items()},
            "families": {
                fid: family.to_dict() for fid, family in self.families.items()
            },
            "statistics": self.get_statistics(),
            "validation": {
                "is_valid": self.is_valid,
                "error_count": len(self.validation_errors),
                "errors": [e.to_dict() for e in self.validation_errors],
            },
        }
        if self.organizations or self.organization_links:
            data["organizations"] = [o.to_dict() for o in self.organizations.values()]
            data["organization_links"] = [
                link.to_dict() for link in self.organization_links
            ]
        return data

    def __len__(self) -> int:
        """Retourne le nombre total de personnes"""
        return len(self.persons)

    def __str__(self) -> str:
        """Représentation string de la généalogie"""
        stats = self.get_statistics()
        return f"Genealogy({stats['total_persons']} personnes, {stats['total_families']} familles)"  # noqa: E501

    def __repr__(self) -> str:
        """Représentation pour debug"""
        return f"Genealogy(persons={len(self.persons)}, families={len(self.families)})"
