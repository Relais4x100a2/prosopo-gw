"""
Schémas Pydantic pour les personnes dans l'API geneweb-py.
"""

from typing import Any

from pydantic import BaseModel, Field, field_validator

from ...core.models import AccessLevel, Gender


class TitleSchema(BaseModel):
    """Schéma pour un titre d'une personne."""

    name: str = Field(..., description="Nom du titre")
    title_type: str = Field(default="", description="Type de titre")
    place: str = Field(default="", description="Lieu du titre")
    start_date: str | None = Field(
        default=None, description="Date de début (format ISO ou GeneWeb)"
    )
    end_date: str | None = Field(
        default=None, description="Date de fin (format ISO ou GeneWeb)"
    )
    number: int = Field(default=0, description="Numéro du titre")
    is_main: bool = Field(default=False, description="Titre principal")


class PersonLinkModel(BaseModel):
    """Lien vers une personne dans une note wikitext."""

    first_name: str = Field(..., description="Prénom")
    last_name: str = Field(..., description="Nom")
    occurrence: int = Field(default=0, description="Numéro d'occurrence")
    display_text: str = Field(default="", description="Texte d'affichage du lien")


class PageLinkModel(BaseModel):
    """Lien vers une page étendue dans une note wikitext."""

    page_name: str = Field(..., description="Nom de la page")
    display_text: str = Field(default="", description="Texte d'affichage")


class WizardLinkModel(BaseModel):
    """Lien vers un magicien dans une note wikitext."""

    wizard_name: str = Field(..., description="Nom du magicien")
    display_text: str = Field(default="", description="Texte d'affichage")


class FicheTagsModel(BaseModel):
    """Balises de renvoi sur fiche individu."""

    head: str | None = None
    occu: str | None = None
    death: str | None = None
    biblio: str | None = None
    bnote: str | None = None
    note: str | None = None


class NoteModel(BaseModel):
    """Note structurée avec texte brut et métadonnées wikitext extraites."""

    raw: str = Field(..., description="Texte brut original de la note")
    person_links: list[PersonLinkModel] = Field(default_factory=list)
    page_links: list[PageLinkModel] = Field(default_factory=list)
    wizard_links: list[WizardLinkModel] = Field(default_factory=list)
    fiche_tags: FicheTagsModel = Field(default_factory=FicheTagsModel)


class PersonBaseSchema(BaseModel):
    """Schéma de base pour une personne."""

    first_name: str = Field(..., min_length=1, description="Prénom")
    surname: str = Field(..., min_length=1, description="Nom de famille")
    public_name: str | None = Field(default=None, description="Nom public")
    titles: list[TitleSchema] = Field(default_factory=list, description="Titres")
    image: str | None = Field(default=None, description="Image ou photo")
    sex: Gender = Field(..., description="Sexe")
    access_level: AccessLevel = Field(
        default=AccessLevel.DEFAULT, description="Niveau d'accès"
    )

    @field_validator("sex", mode="before")
    @classmethod
    def convert_sex(cls, v):
        """Convertit les valeurs de sexe vers les enums internes."""
        if isinstance(v, str):
            mapping = {
                "male": Gender.MALE,
                "m": Gender.MALE,
                "female": Gender.FEMALE,
                "f": Gender.FEMALE,
                "unknown": Gender.UNKNOWN,
                "?": Gender.UNKNOWN,
            }
            key = v.strip().lower()
            if key not in mapping:
                raise ValueError(
                    "Valeur de sexe invalide ; utiliser male, female, unknown, m, f ou ?."
                )
            return mapping[key]
        return v

    @field_validator("access_level", mode="before")
    @classmethod
    def convert_access_level(cls, v):
        """Convertit les valeurs de niveau d'accès vers les enums internes."""
        if isinstance(v, str):
            mapping = {
                "public": AccessLevel.PUBLIC,
                "private": AccessLevel.PRIVATE,
                "default": AccessLevel.DEFAULT,
            }
            return mapping.get(v.lower(), AccessLevel.DEFAULT)
        return v


class PersonCreateSchema(PersonBaseSchema):
    """Schéma pour la création d'une personne."""

    pass


class PersonUpdateSchema(BaseModel):
    """Schéma pour la mise à jour d'une personne."""

    first_name: str | None = Field(default=None, min_length=1, description="Prénom")
    surname: str | None = Field(
        default=None, min_length=1, description="Nom de famille"
    )
    public_name: str | None = Field(default=None, description="Nom public")
    titles: list[TitleSchema] | None = Field(default=None, description="Titres")
    image: str | None = Field(default=None, description="Image ou photo")
    sex: Gender | None = Field(default=None, description="Sexe")
    access_level: AccessLevel | None = Field(default=None, description="Niveau d'accès")

    @field_validator("sex", mode="before")
    @classmethod
    def convert_sex(cls, v):
        """Convertit les valeurs de sexe vers les enums internes."""
        if isinstance(v, str):
            mapping = {
                "male": Gender.MALE,
                "m": Gender.MALE,
                "female": Gender.FEMALE,
                "f": Gender.FEMALE,
                "unknown": Gender.UNKNOWN,
                "?": Gender.UNKNOWN,
            }
            key = v.strip().lower()
            if key not in mapping:
                raise ValueError(
                    "Valeur de sexe invalide ; utiliser male, female, unknown, m, f ou ?."
                )
            return mapping[key]
        return v

    @field_validator("access_level", mode="before")
    @classmethod
    def convert_access_level(cls, v):
        """Convertit les valeurs de niveau d'accès vers les enums internes."""
        if isinstance(v, str):
            mapping = {
                "public": AccessLevel.PUBLIC,
                "private": AccessLevel.PRIVATE,
                "default": AccessLevel.DEFAULT,
            }
            return mapping.get(v.lower(), AccessLevel.DEFAULT)
        return v


class PersonSchema(PersonBaseSchema):
    """Schéma complet pour une personne."""

    id: str = Field(..., description="Identifiant unique de la personne")
    birth_date: str | None = Field(default=None, description="Date de naissance")
    birth_place: str | None = Field(default=None, description="Lieu de naissance")
    death_date: str | None = Field(default=None, description="Date de décès")
    death_place: str | None = Field(default=None, description="Lieu de décès")
    death_cause: str | None = Field(default=None, description="Cause du décès")
    burial_date: str | None = Field(default=None, description="Date d'inhumation")
    burial_place: str | None = Field(default=None, description="Lieu d'inhumation")
    baptism_date: str | None = Field(default=None, description="Date de baptême")
    baptism_place: str | None = Field(default=None, description="Lieu de baptême")
    notes: list[str] = Field(default_factory=list, description="Notes personnelles")
    sources: list[str] = Field(default_factory=list, description="Sources")
    families: list[str] = Field(default_factory=list, description="IDs des familles")
    related_families: list[str] = Field(
        default_factory=list,
        description="IDs des familles où la personne est conjoint(e)",
    )
    events: list[str] = Field(
        default_factory=list, description="IDs des événements personnels"
    )

    class Config:
        """Configuration Pydantic."""

        from_attributes = True


class PersonListSchema(BaseModel):
    """Schéma pour la liste des personnes."""

    id: str = Field(..., description="Identifiant unique")
    first_name: str = Field(..., description="Prénom")
    surname: str = Field(..., description="Nom de famille")
    public_name: str | None = Field(default=None, description="Nom public")
    birth_date: str | None = Field(default=None, description="Date de naissance")
    death_date: str | None = Field(default=None, description="Date de décès")
    sex: Gender = Field(..., description="Sexe")
    access_level: AccessLevel = Field(..., description="Niveau d'accès")


class PersonSearchSchema(BaseModel):
    """Schéma pour la recherche de personnes."""

    query: str | None = Field(default=None, description="Recherche textuelle")
    first_name: str | None = Field(default=None, description="Filtrer par prénom")
    surname: str | None = Field(default=None, description="Filtrer par nom de famille")
    sex: Gender | None = Field(default=None, description="Filtrer par sexe")
    birth_year_from: int | None = Field(
        default=None, ge=1000, le=3000, description="Année de naissance minimum"
    )
    birth_year_to: int | None = Field(
        default=None, ge=1000, le=3000, description="Année de naissance maximum"
    )
    death_year_from: int | None = Field(
        default=None, ge=1000, le=3000, description="Année de décès minimum"
    )
    death_year_to: int | None = Field(
        default=None, ge=1000, le=3000, description="Année de décès maximum"
    )
    place: str | None = Field(default=None, description="Filtrer par lieu")
    access_level: AccessLevel | None = Field(
        default=None, description="Filtrer par niveau d'accès"
    )
    page: int = Field(default=1, ge=1, description="Numéro de page")
    size: int = Field(default=20, ge=1, le=100, description="Taille de la page")

    @field_validator("sex", mode="before")
    @classmethod
    def normalize_search_sex(cls, v: Any) -> Gender | None:
        """Normalise le filtre sexe (REST, codes GeneWeb) ou absence de filtre."""
        if v is None:
            return None
        if isinstance(v, Gender):
            return v
        if isinstance(v, str):
            key = v.strip().lower()
            if not key:
                return None
            mapping = {
                "male": Gender.MALE,
                "m": Gender.MALE,
                "female": Gender.FEMALE,
                "f": Gender.FEMALE,
                "unknown": Gender.UNKNOWN,
                "?": Gender.UNKNOWN,
            }
            if key in mapping:
                return mapping[key]
            raise ValueError(
                "Valeur de sexe invalide pour le filtre ; utiliser male, female, "
                "unknown, m, f ou ?."
            )
        raise TypeError("Type invalide pour le filtre sexe.")

    @field_validator("access_level", mode="before")
    @classmethod
    def normalize_search_access_level(cls, v: Any) -> AccessLevel | None:
        """Normalise le filtre niveau d'accès (REST ou codes GeneWeb) ou absence."""
        if v is None:
            return None
        if isinstance(v, AccessLevel):
            return v
        if isinstance(v, str):
            key = v.strip().lower()
            if not key:
                return None
            mapping = {
                "public": AccessLevel.PUBLIC,
                "apubl": AccessLevel.PUBLIC,
                "private": AccessLevel.PRIVATE,
                "apriv": AccessLevel.PRIVATE,
                "default": AccessLevel.DEFAULT,
            }
            if key in mapping:
                return mapping[key]
            raise ValueError(
                "Valeur de niveau d'accès invalide pour le filtre ; utiliser public, "
                "private, default, apubl ou apriv."
            )
        raise TypeError("Type invalide pour le filtre access_level.")


class PersonStatsSchema(BaseModel):
    """Schéma pour les statistiques des personnes."""

    total: int = Field(..., ge=0, description="Nombre total de personnes")
    by_sex: dict[str, int] = Field(..., description="Répartition par sexe")
    by_access_level: dict[str, int] = Field(
        ..., description="Répartition par niveau d'accès"
    )
    by_century: dict[str, int] = Field(
        ..., description="Répartition par siècle de naissance"
    )
    with_birth_date: int = Field(..., ge=0, description="Nombre avec date de naissance")
    with_death_date: int = Field(..., ge=0, description="Nombre avec date de décès")
