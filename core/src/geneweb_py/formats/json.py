"""
Convertisseur JSON pour geneweb-py.

Ce module fournit les fonctionnalités d'export et d'import vers/depuis
le format JSON pour faciliter l'intégration avec d'autres systèmes
et l'échange de données généalogiques.
"""

import json
from pathlib import Path
from typing import Any, TypeVar

from ..core.date import CalendarType, Date, DeathType
from ..core.event import Event, FamilyEvent, PersonalEvent
from ..core.family import Family
from ..core.genealogy import Genealogy
from ..core.person import Person
from .base import BaseExporter, BaseImporter, ConversionError

_E = TypeVar("_E", bound=Event)


class JSONExporter(BaseExporter):
    """Exporteur vers le format JSON."""

    def __init__(
        self, encoding: str = "utf-8", indent: int = 2, ensure_ascii: bool = False
    ):
        """
        Initialise l'exporteur JSON.

        Args:
            encoding: Encodage à utiliser (défaut: utf-8)
            indent: Indentation JSON (défaut: 2)
            ensure_ascii: Forcer l'ASCII (défaut: False pour UTF-8)
        """
        super().__init__(encoding)
        self.indent = indent
        self.ensure_ascii = ensure_ascii

    def export(self, genealogy: Genealogy, output_path: str | Path) -> None:
        """
        Exporte une généalogie vers un fichier JSON.

        Args:
            genealogy: Objet Genealogy à exporter
            output_path: Chemin du fichier de sortie

        Raises:
            ConversionError: En cas d'erreur de conversion
        """
        self._validate_genealogy(genealogy)

        try:
            json_content = self.export_to_string(genealogy)

            with open(output_path, "w", encoding=self.encoding) as f:
                f.write(json_content)

        except Exception as e:
            raise ConversionError(f"Erreur lors de l'export JSON : {e}") from e

    def export_to_string(self, genealogy: Genealogy) -> str:
        """
        Exporte une généalogie vers une chaîne JSON.

        Args:
            genealogy: Objet Genealogy à exporter

        Returns:
            Chaîne JSON formatée

        Raises:
            ConversionError: En cas d'erreur de conversion
        """
        self._validate_genealogy(genealogy)

        try:
            data = self._serialize_genealogy(genealogy)
            return json.dumps(
                data, indent=self.indent, ensure_ascii=self.ensure_ascii, default=str
            )
        except Exception as e:
            raise ConversionError(f"Erreur lors de la sérialisation JSON : {e}") from e

    def _serialize_genealogy(self, genealogy: Genealogy) -> dict[str, Any]:
        """Sérialise une généalogie en dictionnaire JSON."""
        return {
            "metadata": {
                "version": "1.0.0",
                "format": "geneweb-py-json",
                "created_at": (
                    genealogy.metadata.created_date.isoformat()
                    if genealogy.metadata.created_date
                    else None
                ),
                "statistics": {
                    "persons_count": len(genealogy.persons),
                    "families_count": len(genealogy.families),
                    "events_count": sum(
                        len(p.events) for p in genealogy.persons.values()
                    )
                    + sum(len(f.events) for f in genealogy.families.values()),
                },
            },
            "persons": [
                self._serialize_person(person) for person in genealogy.persons.values()
            ],
            "families": [
                self._serialize_family(family) for family in genealogy.families.values()
            ],
        }

    def _serialize_person(self, person: Person) -> dict[str, Any]:
        """Sérialise une personne en dictionnaire JSON."""
        return {
            "id": id(person),  # ID unique temporaire
            "last_name": person.last_name,
            "first_name": person.first_name,
            "public_name": person.public_name,
            "first_name_alias": person.first_name_alias,
            "surname_alias": person.surname_alias,
            "general_alias": person.general_alias,
            "nickname": person.nickname,
            "gender": person.gender.value if person.gender else None,
            "birth_date": self._serialize_date(person.birth_date),
            "birth_place": person.birth_place,
            "death_date": self._serialize_date(person.death_date),
            "death_place": person.death_place,
            "baptism_date": self._serialize_date(person.baptism_date),
            "baptism_place": person.baptism_place,
            "titles": [
                {
                    "name": title.name,
                    "title_type": title.title_type,
                    "place": title.place,
                }
                for title in person.titles
            ],
            "occupation": person.occupation,
            "events": [self._serialize_event(event) for event in person.events],
        }

    def _serialize_family(self, family: Family) -> dict[str, Any]:
        """Sérialise une famille en dictionnaire JSON."""
        return {
            "id": id(family),  # ID unique temporaire
            "family_id": family.family_id,
            "husband_id": family.husband_id,
            "wife_id": family.wife_id,
            "children": [
                {"person_id": child.person_id, "sex": child.sex.value}
                for child in family.children
            ],
            "marriage_date": self._serialize_date(family.marriage_date),
            "marriage_place": family.marriage_place,
            "divorce_date": self._serialize_date(family.divorce_date),
            "events": [self._serialize_event(event) for event in family.events],
            "witnesses": family.witnesses,
            "family_source": family.family_source,
            "comments": family.comments,
        }

    def _serialize_event(self, event: Event) -> dict[str, Any]:
        """Sérialise un événement en dictionnaire JSON."""
        return {
            "event_type": event.event_type.value if event.event_type else None,
            "date": self._serialize_date(event.date),
            "place": event.place,
            "source": event.source,
            "witnesses": event.witnesses,
            "notes": event.notes,
            "metadata": event.metadata,
        }

    def _serialize_date(self, date: Date | None) -> dict[str, Any] | None:
        """Sérialise une date en dictionnaire JSON."""
        if not date:
            return None

        from ..core.date import DatePrefix

        return {
            "year": date.year,
            "month": date.month,
            "day": date.day,
            "calendar": date.calendar.value if date.calendar else None,
            "prefix": date.prefix.value if date.prefix else None,
            "text": date.text_date,
            "is_approximate": date.prefix == DatePrefix.ABOUT,
            "is_before": date.prefix == DatePrefix.BEFORE,
            "is_after": date.prefix == DatePrefix.AFTER,
            "is_uncertain": date.prefix == DatePrefix.MAYBE,
            "death_type": date.death_type.value if date.death_type else None,
        }


class JSONImporter(BaseImporter):
    """Importeur depuis le format JSON."""

    def __init__(self, encoding: str = "utf-8"):
        """
        Initialise l'importeur JSON.

        Args:
            encoding: Encodage à utiliser (défaut: utf-8)
        """
        super().__init__(encoding)
        self._person_map: dict[int, Person] = {}
        self._family_map: dict[int, Family] = {}

    def import_from_file(self, input_path: str | Path) -> Genealogy:
        """
        Importe une généalogie depuis un fichier JSON.

        Args:
            input_path: Chemin du fichier à importer

        Returns:
            Objet Genealogy importé

        Raises:
            ConversionError: En cas d'erreur de conversion
        """
        path = self._validate_file_path(input_path)

        try:
            with open(path, encoding=self.encoding) as f:
                content = f.read()

            return self.import_from_string(content)

        except Exception as e:
            raise ConversionError(f"Erreur lors de l'import JSON : {e}") from e

    def import_from_string(self, data: str) -> Genealogy:
        """
        Importe une généalogie depuis une chaîne JSON.

        Args:
            data: Chaîne JSON à importer

        Returns:
            Objet Genealogy importé

        Raises:
            ConversionError: En cas d'erreur de conversion
        """
        try:
            # Parser le JSON
            json_data = json.loads(data)

            # Vérifier que le JSON n'est pas vide
            if not json_data or (not isinstance(json_data, dict)):
                raise ConversionError("JSON vide ou invalide")

            # Vérifier qu'il y a au moins des données de généalogie
            if not any(key in json_data for key in ["persons", "families", "metadata"]):
                raise ConversionError(
                    "JSON ne contient pas de données de généalogie valides"
                )

            # Réinitialiser les maps
            self._person_map.clear()
            self._family_map.clear()

            # Créer la généalogie
            genealogy = Genealogy()

            # Importer les personnes
            if "persons" in json_data:
                for person_data in json_data["persons"]:
                    person = self._deserialize_person(person_data)
                    if person:
                        genealogy.add_person(person)

            # Importer les familles
            if "families" in json_data:
                for family_data in json_data["families"]:
                    family = self._deserialize_family(family_data)
                    if family:
                        genealogy.add_family(family)

            return genealogy

        except Exception as e:
            raise ConversionError(f"Erreur lors du parsing JSON : {e}") from e

    def _deserialize_person(self, data: dict[str, Any]) -> Person | None:
        """Désérialise une personne depuis un dictionnaire JSON."""
        try:
            from ..core.person import Gender

            gender = (
                Gender(data.get("gender")) if data.get("gender") else Gender.UNKNOWN
            )

            person = Person(
                last_name=data.get("last_name", ""),
                first_name=data.get("first_name", ""),
                public_name=data.get("public_name"),
                first_name_alias=data.get("first_name_alias"),
                surname_alias=data.get("surname_alias"),
                general_alias=data.get("general_alias"),
                nickname=data.get("nickname"),
                gender=gender,
                birth_date=self._deserialize_date(data.get("birth_date")),
                birth_place=data.get("birth_place"),
                death_date=self._deserialize_date(data.get("death_date")),
                death_place=data.get("death_place"),
                baptism_date=self._deserialize_date(data.get("baptism_date")),
                baptism_place=data.get("baptism_place"),
                occupation=data.get("occupation"),
            )

            # Stocker dans la map pour les références
            if "id" in data:
                self._person_map[data["id"]] = person

            # Ajouter les événements
            if "events" in data:
                for event_data in data["events"]:
                    event = self._deserialize_event(event_data, PersonalEvent)
                    if event:
                        person.add_event(event)

            return person

        except Exception as e:
            raise ConversionError(
                f"Erreur lors de la désérialisation de la personne : {e}"
            ) from e

    def _deserialize_family(self, data: dict[str, Any]) -> Family | None:
        """Désérialise une famille depuis un dictionnaire JSON."""
        try:
            from ..core.family import Child, ChildSex

            family = Family(
                family_id=data.get("family_id", "F001"),
                husband_id=data.get("husband_id"),
                wife_id=data.get("wife_id"),
                marriage_date=self._deserialize_date(data.get("marriage_date")),
                marriage_place=data.get("marriage_place"),
                divorce_date=self._deserialize_date(data.get("divorce_date")),
                witnesses=data.get("witnesses", []),
                family_source=data.get("family_source"),
                comments=data.get("comments", []),
            )

            # Ajouter les enfants
            if "children" in data:
                for child_data in data["children"]:
                    child = Child(
                        person_id=child_data.get("person_id", ""),
                        sex=(
                            ChildSex(child_data.get("sex", ""))
                            if child_data.get("sex")
                            else ChildSex.UNKNOWN
                        ),
                    )
                    family.children.append(child)

            # Stocker dans la map pour les références
            if "id" in data:
                self._family_map[data["id"]] = family

            # Ajouter les événements
            if "events" in data:
                for event_data in data["events"]:
                    event = self._deserialize_event(event_data, FamilyEvent)
                    if event:
                        family.add_event(event)

            return family

        except Exception as e:
            raise ConversionError(
                f"Erreur lors de la désérialisation de la famille : {e}"
            ) from e

    def _deserialize_event(
        self,
        data: dict[str, Any],
        event_cls: type[_E] = Event,  # type: ignore[assignment]
    ) -> _E | None:
        """Désérialise un événement depuis un dictionnaire JSON."""
        try:
            from ..core.event import EventType

            if not data.get("event_type"):
                return None
            event_type = EventType(data["event_type"])

            event = event_cls(
                event_type=event_type,
                date=self._deserialize_date(data.get("date")),
                place=data.get("place"),
                source=data.get("source"),
                witnesses=data.get("witnesses", []),
                notes=data.get("notes", []),
                metadata=data.get("metadata", {}),
            )
            return event
        except Exception as e:
            raise ConversionError(
                f"Erreur lors de la désérialisation de l'événement : {e}"
            ) from e

    def _deserialize_date(self, data: dict[str, Any] | None) -> Date | None:
        """Désérialise une date depuis un dictionnaire JSON."""
        if not data:
            return None

        try:
            return Date(
                year=data.get("year"),
                month=data.get("month"),
                day=data.get("day"),
                calendar=CalendarType(data.get("calendar") or CalendarType.GREGORIAN),
                prefix=data.get("prefix"),
                text_date=data.get("text"),
                # Les attributs is_* sont dérivés du préfixe
                death_type=DeathType(data.get("death_type") or DeathType.NORMAL),
            )
        except Exception as e:
            raise ConversionError(
                f"Erreur lors de la désérialisation de la date : {e}"
            ) from e  # noqa: E501
