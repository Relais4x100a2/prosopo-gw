"""Schémas Pydantic des organisations candidates."""

from typing import List, Optional

from pydantic import BaseModel, Field


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
