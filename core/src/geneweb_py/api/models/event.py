"""
Schémas Pydantic pour les événements dans l'API geneweb-py.
"""

from pydantic import BaseModel, Field, field_validator

from ...core.models import EventType, FamilyEventType


class EventBaseSchema(BaseModel):
    """Schéma de base pour un événement."""

    event_type: EventType | FamilyEventType = Field(..., description="Type d'événement")
    date: str | None = Field(default=None, description="Date de l'événement")
    place: str | None = Field(default=None, description="Lieu de l'événement")
    reason: str | None = Field(default=None, description="Raison ou cause")
    note: str | None = Field(default=None, description="Note sur l'événement")
    witnesses: list[str] = Field(default_factory=list, description="Témoins")
    sources: list[str] = Field(default_factory=list, description="Sources")

    @field_validator("event_type", mode="before")
    @classmethod
    def convert_event_type(cls, v):
        """Convertit les types d'événements lisibles vers les enums internes."""
        if isinstance(v, str):
            # Mapping pour les événements personnels
            personal_mapping = {
                "birth": EventType.BIRTH,
                "baptism": EventType.BAPTISM,
                "death": EventType.DEATH,
                "burial": EventType.BURIAL,
                "cremation": EventType.CREMATION,
                "confirmation": EventType.CONFIRMATION,
                "first_communion": EventType.FIRST_COMMUNION,
                "ordination": EventType.ORDINATION,
                "excommunication": EventType.EXCOMMUNICATION,
                "naturalization": EventType.NATURALIZATION,
                "occupation": EventType.OCCUPATION,
                "residence": EventType.RESIDENCE,
                "education": EventType.EDUCATION,
                "graduation": EventType.GRADUATION,
                "military_service": EventType.MILITARY_SERVICE,
                "marriage": EventType.MARRIAGE,
                "divorce": EventType.DIVORCE,
                "separation": EventType.SEPARATION,
                "engagement": EventType.ENGAGEMENT,
                "pacs": EventType.PACS,
            }

            # Mapping pour les événements familiaux
            family_mapping = {
                "marriage": FamilyEventType.MARRIAGE,
                "divorce": FamilyEventType.DIVORCE,
                "separation": FamilyEventType.SEPARATION,
                "engagement": FamilyEventType.ENGAGEMENT,
                "pacs": FamilyEventType.PACS,
            }

            # Essayer d'abord les événements personnels
            if v in personal_mapping:
                return personal_mapping[v]
            # Puis les événements familiaux
            elif v in family_mapping:
                return family_mapping[v]
            # Sinon, essayer de trouver par valeur enum
            else:
                for event_type in EventType:
                    if event_type.value == v:
                        return event_type
                for event_type in FamilyEventType:
                    if event_type.value == v:
                        return event_type

        return v


class PersonalEventCreateSchema(EventBaseSchema):
    """Schéma pour la création d'un événement personnel."""

    person_id: str = Field(..., description="Identifiant de la personne")
    event_type: EventType = Field(..., description="Type d'événement personnel")


class FamilyEventCreateSchema(EventBaseSchema):
    """Schéma pour la création d'un événement familial."""

    family_id: str = Field(..., description="Identifiant de la famille")
    event_type: FamilyEventType = Field(..., description="Type d'événement familial")


class EventUpdateSchema(BaseModel):
    """Schéma pour la mise à jour d'un événement."""

    event_type: EventType | FamilyEventType | None = Field(
        default=None, description="Type d'événement"
    )
    date: str | None = Field(default=None, description="Date de l'événement")
    place: str | None = Field(default=None, description="Lieu de l'événement")
    reason: str | None = Field(default=None, description="Raison ou cause")
    note: str | None = Field(default=None, description="Note sur l'événement")
    witnesses: list[str] | None = Field(default=None, description="Témoins")
    sources: list[str] | None = Field(default=None, description="Sources")


class EventSchema(EventBaseSchema):
    """Schéma complet pour un événement."""

    id: str = Field(..., description="Identifiant unique de l'événement")
    person_id: str | None = Field(
        default=None,
        description="Identifiant de la personne (pour événements personnels)",
    )
    family_id: str | None = Field(
        default=None,
        description="Identifiant de la famille (pour événements familiaux)",
    )
    person_name: str | None = Field(
        default=None, description="Nom résolu de la personne"
    )
    family_label: str | None = Field(
        default=None, description="Libellé résolu de la famille"
    )
    witness_names: list[str] = Field(
        default_factory=list, description="Noms des témoins résolus"
    )
    date_sort_year: int | None = Field(
        default=None, description="Année de tri numérique"
    )
    custom_type: str | None = Field(
        default=None,
        description="Nom personnalisé d'un événement « Autre » (tag GeneWeb libre)",
    )

    class Config:
        """Configuration Pydantic."""

        from_attributes = True


class EventListSchema(BaseModel):
    """Schéma pour la liste des événements."""

    id: str = Field(..., description="Identifiant unique")
    event_type: EventType | FamilyEventType = Field(..., description="Type d'événement")
    date: str | None = Field(default=None, description="Date de l'événement")
    place: str | None = Field(default=None, description="Lieu de l'événement")
    person_id: str | None = Field(
        default=None, description="Identifiant de la personne"
    )
    family_id: str | None = Field(default=None, description="Identifiant de la famille")


class EventSearchSchema(BaseModel):
    """Schéma pour la recherche d'événements."""

    query: str | None = Field(default=None, description="Recherche textuelle")
    event_type: EventType | FamilyEventType | None = Field(
        default=None, description="Filtrer par type d'événement"
    )
    person_id: str | None = Field(default=None, description="Filtrer par personne")
    family_id: str | None = Field(default=None, description="Filtrer par famille")
    year_from: int | None = Field(
        default=None, ge=1000, le=3000, description="Année minimum"
    )
    year_to: int | None = Field(
        default=None, ge=1000, le=3000, description="Année maximum"
    )
    place: str | None = Field(default=None, description="Filtrer par lieu")
    has_witnesses: bool | None = Field(
        default=None, description="Filtrer par présence de témoins"
    )
    has_sources: bool | None = Field(
        default=None, description="Filtrer par présence de sources"
    )
    page: int = Field(default=1, ge=1, description="Numéro de page")
    size: int = Field(default=20, ge=1, le=100, description="Taille de la page")


class EventStatsSchema(BaseModel):
    """Schéma pour les statistiques des événements."""

    total: int = Field(..., ge=0, description="Nombre total d'événements")
    by_type: dict[str, int] = Field(..., description="Répartition par type d'événement")
    by_century: dict[str, int] = Field(..., description="Répartition par siècle")
    with_date: int = Field(..., ge=0, description="Nombre avec date")
    with_place: int = Field(..., ge=0, description="Nombre avec lieu")
    with_witnesses: int = Field(..., ge=0, description="Nombre avec témoins")
    with_sources: int = Field(..., ge=0, description="Nombre avec sources")
    personal_events: int = Field(
        ..., ge=0, description="Nombre d'événements personnels"
    )
    family_events: int = Field(..., ge=0, description="Nombre d'événements familiaux")
