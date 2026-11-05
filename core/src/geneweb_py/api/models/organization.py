"""Schémas Pydantic des organisations candidates."""

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from ..services.organization_candidates import (
    IGNORED_WORDS_MAX,
    normalize_ignored_words,
)


class OrganizationMemberSchema(BaseModel):
    """Personne liée à un candidat, avec son événement d'origine."""

    person_id: str
    person_name: str
    role: Optional[str] = None
    date: Optional[str] = Field(default=None, description="Date affichable")
    place: Optional[str] = None
    source_event_type: str = Field(
        ...,
        description='Type API de l\'événement : "oth", "occu", "educ", "occu_attr"…',
    )
    event_type_raw: Optional[str] = None
    event_label: str = ""
    witness_count: int = 0
    year: Optional[int] = None
    witness: bool = Field(
        False, description="Témoin de l'événement (et non son porteur)"
    )
    source_event_id: Optional[str] = Field(
        default=None,
        description="Événement d'origine, commun au porteur et à ses témoins",
    )


class OrganizationCandidateSchema(BaseModel):
    """Organisation candidate (liste)."""

    id: str
    name: str
    type: str
    place: Optional[str] = None
    named_from: Optional[str] = None
    sources: List[str] = Field(default_factory=list)
    trigger: Optional[str] = None
    confidence: Optional[float] = None
    needs_review: bool = False
    to_determine: bool = False
    relation: bool = False
    collective: bool = False
    person_count: int
    event_count: int
    first_year: Optional[int] = None
    last_year: Optional[int] = None
    places: List[str] = Field(default_factory=list)
    roles: List[str] = Field(default_factory=list)


class OrganizationCandidateDetailSchema(OrganizationCandidateSchema):
    """Candidat avec la liste de ses membres."""

    members: List[OrganizationMemberSchema] = Field(default_factory=list)


class UnmatchedEventSchema(BaseModel):
    """Événement « Autre » sans candidat."""

    person_id: str
    person_name: str
    event_type_raw: str
    label: str
    date: Optional[str] = None
    place: Optional[str] = None


class UnmatchedGroupSchema(BaseModel):
    """Groupe d'événements non classés partageant un mot."""

    word: str
    count: int
    events: List[UnmatchedEventSchema] = Field(default_factory=list)


class UnmatchedResponseSchema(BaseModel):
    """Reste à classer."""

    total: int
    groups: List[UnmatchedGroupSchema] = Field(default_factory=list)
    ignored_total: int = Field(
        default=0, description="Événements « Autre » écartés par les mots ignorés"
    )
    civil_status_total: int = Field(
        default=0, description="Événements d'état civil écartés (toujours exclus)"
    )


class IgnoredWordsSchema(BaseModel):
    """Mots qui écartent un événement « Autre » des organisations candidates."""

    words: List[str] = Field(
        default_factory=list,
        max_length=IGNORED_WORDS_MAX * 2,
        description="Mots entiers, sans casse ni accents (cercle, club…)",
    )

    @field_validator("words")
    @classmethod
    def _normalize(cls, words: List[str]) -> List[str]:
        return list(normalize_ignored_words(words))


class SharedReasonSchema(BaseModel):
    """Raison du rapprochement : même ville ou mots rares communs."""

    kind: str = Field(..., description='"same_place" ou "rare_word"')
    place: Optional[str] = None
    words: List[str] = Field(default_factory=list)


class SharedExperiencePersonSchema(BaseModel):
    """Événement d'une personne dans une expérience proche."""

    person_id: str
    person_name: str
    event_type_raw: str
    label: str = Field(..., description="Tag lisible (``_`` remplacé par une espace)")
    year_start: int
    year_end: int
    place: Optional[str] = None


class SharedExperienceSchema(BaseModel):
    """Expérience proche : événements rapprochés de plusieurs personnes."""

    id: str
    theme: str
    label: str
    year_min: int
    year_max: int
    places: List[str] = Field(default_factory=list)
    reasons: List[SharedReasonSchema] = Field(default_factory=list)
    person_count: int
    event_count: int
    persons: List[SharedExperiencePersonSchema] = Field(default_factory=list)


class SharedExperiencesResponseSchema(BaseModel):
    """Liste des expériences proches (plafonnée)."""

    items: List[SharedExperienceSchema] = Field(default_factory=list)
    total: int
    civil_status_total: int = 0
    undated_total: int = 0
    truncated: bool = False
