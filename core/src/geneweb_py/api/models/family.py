"""
Schémas Pydantic pour les familles dans l'API geneweb-py.
"""

from pydantic import BaseModel, Field, field_validator

from ...core.models import ChildSex, MarriageStatus


class ChildSchema(BaseModel):
    """Schéma pour un enfant dans une famille."""

    person_id: str = Field(..., description="Identifiant de la personne")
    sex: ChildSex = Field(default=ChildSex.UNKNOWN, description="Sexe de l'enfant")
    last_name: str | None = Field(
        default=None, description="Nom de famille si différent du père"
    )

    @field_validator("sex", mode="before")
    @classmethod
    def convert_sex(cls, v):
        """Convertit les valeurs de sexe vers les enums internes."""
        if isinstance(v, str):
            mapping = {
                "male": ChildSex.MALE,
                "female": ChildSex.FEMALE,
                "unknown": ChildSex.UNKNOWN,
            }
            return mapping.get(v.lower(), ChildSex.UNKNOWN)
        return v


class FamilyBaseSchema(BaseModel):
    """Schéma de base pour une famille."""

    husband_id: str | None = Field(default=None, description="Identifiant du mari")
    wife_id: str | None = Field(default=None, description="Identifiant de l'épouse")
    children: list[ChildSchema] = Field(default_factory=list, description="Enfants")
    marriage_status: MarriageStatus = Field(
        default=MarriageStatus.MARRIED, description="Statut du mariage"
    )
    notes: list[str] = Field(default_factory=list, description="Notes familiales")
    sources: list[str] = Field(default_factory=list, description="Sources")

    @field_validator("marriage_status", mode="before")
    @classmethod
    def convert_marriage_status(cls, v):
        """Convertit les valeurs de statut de mariage vers les enums internes."""
        if isinstance(v, str):
            mapping = {
                "married": MarriageStatus.MARRIED,
                "divorced": MarriageStatus.DIVORCED,
                "separated": MarriageStatus.SEPARATED,
                "widowed": MarriageStatus.WIDOWED,
                "unknown": MarriageStatus.UNKNOWN,
            }
            return mapping.get(v.lower(), MarriageStatus.MARRIED)
        return v


class FamilyCreateSchema(FamilyBaseSchema):
    """Schéma pour la création d'une famille."""

    pass


class FamilyUpdateSchema(BaseModel):
    """Schéma pour la mise à jour d'une famille."""

    husband_id: str | None = Field(default=None, description="Identifiant du mari")
    wife_id: str | None = Field(default=None, description="Identifiant de l'épouse")
    children: list[ChildSchema] | None = Field(default=None, description="Enfants")
    marriage_status: MarriageStatus | None = Field(
        default=None, description="Statut du mariage"
    )
    notes: list[str] | None = Field(default=None, description="Notes familiales")
    sources: list[str] | None = Field(default=None, description="Sources")

    @field_validator("marriage_status", mode="before")
    @classmethod
    def convert_marriage_status(cls, v):
        """Convertit les valeurs de statut de mariage vers les enums internes."""
        if isinstance(v, str):
            mapping = {
                "married": MarriageStatus.MARRIED,
                "divorced": MarriageStatus.DIVORCED,
                "separated": MarriageStatus.SEPARATED,
                "widowed": MarriageStatus.WIDOWED,
                "unknown": MarriageStatus.UNKNOWN,
            }
            return mapping.get(v.lower(), MarriageStatus.MARRIED)
        return v


class FamilySchema(FamilyBaseSchema):
    """Schéma complet pour une famille."""

    id: str = Field(..., description="Identifiant unique de la famille")
    marriage_date: str | None = Field(default=None, description="Date de mariage")
    marriage_place: str | None = Field(default=None, description="Lieu de mariage")
    divorce_date: str | None = Field(default=None, description="Date de divorce")
    divorce_place: str | None = Field(default=None, description="Lieu de divorce")
    events: list[str] = Field(
        default_factory=list, description="IDs des événements familiaux"
    )

    class Config:
        """Configuration Pydantic."""

        from_attributes = True


class FamilyListSchema(BaseModel):
    """Schéma pour la liste des familles."""

    id: str = Field(..., description="Identifiant unique")
    husband_id: str | None = Field(default=None, description="Identifiant du mari")
    wife_id: str | None = Field(default=None, description="Identifiant de l'épouse")
    children_count: int = Field(..., ge=0, description="Nombre d'enfants")
    marriage_date: str | None = Field(default=None, description="Date de mariage")
    marriage_status: MarriageStatus = Field(..., description="Statut du mariage")


class FamilySearchSchema(BaseModel):
    """Schéma pour la recherche de familles."""

    query: str | None = Field(default=None, description="Recherche textuelle")
    husband_id: str | None = Field(default=None, description="Filtrer par mari")
    wife_id: str | None = Field(default=None, description="Filtrer par épouse")
    marriage_status: MarriageStatus | None = Field(
        default=None, description="Filtrer par statut de mariage"
    )
    marriage_year_from: int | None = Field(
        default=None, ge=1000, le=3000, description="Année de mariage minimum"
    )
    marriage_year_to: int | None = Field(
        default=None, ge=1000, le=3000, description="Année de mariage maximum"
    )
    divorce_year_from: int | None = Field(
        default=None, ge=1000, le=3000, description="Année de divorce minimum"
    )
    divorce_year_to: int | None = Field(
        default=None, ge=1000, le=3000, description="Année de divorce maximum"
    )
    place: str | None = Field(default=None, description="Filtrer par lieu")
    has_children: bool | None = Field(
        default=None, description="Filtrer par présence d'enfants"
    )
    min_children: int | None = Field(
        default=None, ge=0, description="Nombre minimum d'enfants"
    )
    max_children: int | None = Field(
        default=None, ge=0, description="Nombre maximum d'enfants"
    )
    page: int = Field(default=1, ge=1, description="Numéro de page")
    size: int = Field(default=20, ge=1, le=100, description="Taille de la page")


class FamilyStatsSchema(BaseModel):
    """Schéma pour les statistiques des familles."""

    total: int = Field(..., ge=0, description="Nombre total de familles")
    by_status: dict[str, int] = Field(
        ..., description="Répartition par statut de mariage"
    )
    by_century: dict[str, int] = Field(
        ..., description="Répartition par siècle de mariage"
    )
    with_marriage_date: int = Field(
        ..., ge=0, description="Nombre avec date de mariage"
    )
    with_divorce_date: int = Field(..., ge=0, description="Nombre avec date de divorce")
    average_children: float = Field(
        ..., ge=0, description="Nombre moyen d'enfants par famille"
    )
    families_with_children: int = Field(
        ..., ge=0, description="Nombre de familles avec enfants"
    )
