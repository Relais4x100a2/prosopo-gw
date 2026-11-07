"""Modèle Organisation : entreprises, écoles, associations… rattachées aux personnes.

Une organisation n'est pas une ``Family`` (union/filiation). Elle est reliée aux
personnes par des ``OrganizationLink`` portés par ``Genealogy``. Le format ``.gw``
n'est pas modifié : la persistance passe par un fichier compagnon JSON
(voir ``geneweb_py.formats.org_sidecar``).
"""

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .date import Date
from .place import ParsedPlace, parse_place


class OrganizationType(Enum):
    """Catégorie d'une organisation"""

    COMPANY = "company"
    SCHOOL = "school"
    ASSOCIATION = "association"
    INSTITUTION = "institution"
    RELIGIOUS = "religious"
    MILITARY = "military"
    OTHER = "other"


def _slugify(text: str) -> str:
    """Normalise un texte en slug ASCII minuscule (``École X`` -> ``ecole_x``)."""
    ascii_text = (
        unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    )
    return re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")


def _date_to_json(value: Date | None) -> str | None:
    return value.display_text if value is not None else None


def _date_from_json(value: str | None) -> Date | None:
    return Date.parse_with_fallback(value) if value else None


def _periods_inverted(start: Date | None, end: Date | None) -> bool:
    """Vrai si les deux dates ont une année exploitable et ``start`` > ``end``."""
    if start is None or end is None:
        return False
    start_year, end_year = start.sort_year(), end.sort_year()
    return start_year is not None and end_year is not None and start_year > end_year


@dataclass
class Organization:
    """Organisation (entreprise, école, association…)"""

    # Identifiant unique stable (voir ``create`` pour un slug normalisé)
    id: str
    name: str
    type: OrganizationType = OrganizationType.OTHER
    # Type d'origine quand il n'est pas reconnu (type == OTHER)
    type_raw: str | None = None
    aliases: list[str] = field(default_factory=list)
    founding_date: Date | None = None
    dissolution_date: Date | None = None
    # Lieu brut ``[complément]_-_lieu`` ; voir ``place_parts``
    place: str | None = None
    url: str | None = None
    notes: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    # Hiérarchie (faculté -> université)
    parent_id: str | None = None
    # Confiance 0..1 quand l'organisation est déduite (LLM/règles)
    confidence: float | None = None
    needs_review: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls, name: str, place: str | None = None, **kwargs: Any
    ) -> "Organization":
        """Crée une organisation avec un ``id`` stable dérivé du nom et du lieu."""
        slug = _slugify(name)
        if place:
            slug = f"{slug}_{_slugify(place)}"
        return cls(id=slug, name=name, place=place, **kwargs)

    @property
    def place_parts(self) -> ParsedPlace | None:
        """Lieu décomposé (complément / commune) ; ``place`` reste la chaîne brute"""
        return parse_place(self.place)

    def validate(self) -> list[str]:
        """Retourne la liste des incohérences (vide si l'organisation est valide)."""
        problems: list[str] = []
        if not self.name or not self.name.strip():
            problems.append(f"{self.id}: nom vide")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            problems.append(f"{self.id}: confidence hors de [0, 1] ({self.confidence})")
        if self.parent_id is not None and self.parent_id == self.id:
            problems.append(f"{self.id}: parent_id égal à l'id (auto-parenté)")
        if _periods_inverted(self.founding_date, self.dissolution_date):
            problems.append(f"{self.id}: dates incohérentes (dissolution < fondation)")
        return problems

    def to_dict(self) -> dict[str, Any]:
        """Convertit l'organisation en dictionnaire JSON-compatible"""
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "type_raw": self.type_raw,
            "aliases": list(self.aliases),
            "founding_date": _date_to_json(self.founding_date),
            "dissolution_date": _date_to_json(self.dissolution_date),
            "place": self.place,
            "url": self.url,
            "notes": list(self.notes),
            "sources": list(self.sources),
            "parent_id": self.parent_id,
            "confidence": self.confidence,
            "needs_review": self.needs_review,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Organization":
        """Reconstruit une organisation (type inconnu -> ``OTHER`` + ``type_raw``)"""
        raw_type = data.get("type")
        type_raw = data.get("type_raw")
        try:
            org_type = (
                OrganizationType(raw_type) if raw_type else OrganizationType.OTHER
            )
        except ValueError:
            org_type = OrganizationType.OTHER
            type_raw = type_raw or raw_type
        return cls(
            id=data["id"],
            name=data["name"],
            type=org_type,
            type_raw=type_raw,
            aliases=list(data.get("aliases") or []),
            founding_date=_date_from_json(data.get("founding_date")),
            dissolution_date=_date_from_json(data.get("dissolution_date")),
            place=data.get("place"),
            url=data.get("url"),
            notes=list(data.get("notes") or []),
            sources=list(data.get("sources") or []),
            parent_id=data.get("parent_id"),
            confidence=data.get("confidence"),
            needs_review=bool(data.get("needs_review", False)),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class OrganizationLink:
    """Lien personne ↔ organisation (arête du graphe)"""

    person_id: str
    organization_id: str
    # Rôle/titre/fonction libre : « Membre », « Directeur », « Apprenti »…
    role: str | None = None
    start_date: Date | None = None
    end_date: Date | None = None
    # Événement d'origine : identifiant et/ou tag (ex. ``Cours_peinture``)
    source_event_id: str | None = None
    source_event_type: str | None = None
    notes: list[str] = field(default_factory=list)

    def validate(self) -> list[str]:
        """Retourne la liste des incohérences (vide si le lien est valide)."""
        problems: list[str] = []
        if _periods_inverted(self.start_date, self.end_date):
            problems.append(
                f"{self.person_id}->{self.organization_id}: "
                "période incohérente (fin < début)"
            )
        return problems

    def to_dict(self) -> dict[str, Any]:
        """Convertit le lien en dictionnaire JSON-compatible"""
        return {
            "person_id": self.person_id,
            "organization_id": self.organization_id,
            "role": self.role,
            "start_date": _date_to_json(self.start_date),
            "end_date": _date_to_json(self.end_date),
            "source_event_id": self.source_event_id,
            "source_event_type": self.source_event_type,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OrganizationLink":
        """Reconstruit un lien depuis son dictionnaire"""
        return cls(
            person_id=data["person_id"],
            organization_id=data["organization_id"],
            role=data.get("role"),
            start_date=_date_from_json(data.get("start_date")),
            end_date=_date_from_json(data.get("end_date")),
            source_event_id=data.get("source_event_id"),
            source_event_type=data.get("source_event_type"),
            notes=list(data.get("notes") or []),
        )
