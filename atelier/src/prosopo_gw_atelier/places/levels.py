"""Modèle de niveaux d'un lieu : chaîne ordonnée, du plus précis (rang 0) au plus large.

Module pur, sans dépendance au référentiel. Un niveau porte un nom, un type facultatif
(liste ouverte : tout slug conforme à ``TYPE_PATTERN`` passe), une origine et un statut.
Seuls les niveaux validés comptent pour la vue française (``french_view``), l'étiquette
(``chain_label``) et l'export ; les niveaux proposés attendent une décision.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

LevelOrigin = Literal[
    "written", "rule", "manual", "insee", "paris", "dicotopo", "geonames", "llm"
]
LevelStatus = Literal["validated", "proposed"]
HistoricalNature = Literal["fusion", "associee", "deleguee"]
ViewField = Literal[
    "commune",
    "insee_code",
    "postal_code",
    "department",
    "region",
    "country",
    "historical_commune",
    "historical_insee",
]

FRENCH_TYPES: tuple[str, ...] = (
    "lieu_dit",
    "quartier",
    "arrondissement",
    "commune_historique",
    "commune",
    "departement",
    "region",
    "ancienne_region",
    "pays",
)
FOREIGN_TYPES: tuple[str, ...] = (
    "localite",
    "comte",
    "province",
    "etat",
    "nation_constitutive",
    "oblast",
    "canton",
    "district",
)
TYPE_LABELS: dict[str, str] = {
    "lieu_dit": "Lieu-dit",
    "quartier": "Quartier",
    "arrondissement": "Arrondissement",
    "commune_historique": "Commune historique",
    "commune": "Commune",
    "departement": "Département",
    "region": "Région",
    "ancienne_region": "Ancienne région",
    "pays": "Pays",
    "localite": "Localité",
    "comte": "Comté",
    "province": "Province",
    "etat": "État",
    "nation_constitutive": "Nation constitutive",
    "oblast": "Oblast",
    "canton": "Canton",
    "district": "District",
}
TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


@dataclass(frozen=True)
class Level:
    """Un niveau de la chaîne d'un lieu (rang 0 = le plus précis)."""

    rank: int
    name: str
    written: str | None = None
    type: str | None = None
    identifier: str | None = None
    source: str | None = None
    start: str | None = None
    end: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    nature: HistoricalNature | None = None
    origin: LevelOrigin = "rule"
    status: LevelStatus = "validated"


def check_chain(levels: Sequence[Level]) -> None:
    """Lève ``ValueError`` (message en français) si la chaîne est invalide."""
    if not levels:
        raise ValueError("Une chaîne doit contenir au moins un niveau.")
    for index, level in enumerate(levels):
        if not level.name.strip():
            raise ValueError(f"Le nom du niveau {index} est vide.")
        if level.type is not None and not TYPE_PATTERN.match(level.type):
            raise ValueError(
                f"Le type du niveau {index} est invalide : {level.type!r}."
            )
        if level.rank != index:
            raise ValueError(
                f"Rang {level.rank} au niveau {index} : rangs attendus de 0 à n-1."
            )
        if level.latitude is not None and not -90 <= level.latitude <= 90:
            raise ValueError(f"La latitude du niveau {index} est hors de [-90, 90].")
        if level.longitude is not None and not -180 <= level.longitude <= 180:
            raise ValueError(f"La longitude du niveau {index} est hors de [-180, 180].")


def renumber(levels: Sequence[Level]) -> tuple[Level, ...]:
    """Rangs 0..n-1 dans l'ordre donné."""
    return tuple(replace(level, rank=index) for index, level in enumerate(levels))


def validated(levels: Sequence[Level]) -> tuple[Level, ...]:
    """Niveaux validés, renumérotés."""
    return renumber([level for level in levels if level.status == "validated"])


def _first(levels: Sequence[Level], type_: str) -> Level | None:
    return next((level for level in levels if level.type == type_), None)


def _view(levels: Sequence[Level]) -> dict[ViewField, tuple[str, LevelOrigin]]:
    """Valeur et origine de chaque champ de la vue, lues sur les niveaux validés."""
    chain = validated(levels)
    view: dict[ViewField, tuple[str, LevelOrigin]] = {}

    def put(field: ViewField, level: Level | None, value: str | None) -> None:
        if level is not None and value:
            view[field] = (value, level.origin)

    commune = _first(chain, "commune")
    if commune is not None:
        put("commune", commune, commune.name)
        put("insee_code", commune, commune.identifier)
    historical = _first(chain, "commune_historique")
    if historical is not None:
        put("historical_commune", historical, historical.name)
        put("historical_insee", historical, historical.identifier)
    department = _first(chain, "departement")
    if department is not None:
        put("department", department, department.identifier or department.name)
    region = _first(chain, "region") or _first(chain, "ancienne_region")
    if region is not None:
        put("region", region, region.name)
    country = _first(chain, "pays")
    if country is not None:
        put("country", country, country.name)
    return view


def french_view(
    levels: Sequence[Level], postal_code: str | None
) -> dict[ViewField, str]:
    """Vue française à champs fixes (niveaux validés) ; clé sans valeur absente."""
    view: dict[ViewField, str] = {
        field: value for field, (value, _) in _view(levels).items()
    }
    if postal_code:
        view["postal_code"] = postal_code
    return view


def view_origins(levels: Sequence[Level]) -> dict[ViewField, LevelOrigin]:
    """Origine du niveau source de chaque champ de la vue (hors code postal)."""
    return {field: origin for field, (_, origin) in _view(levels).items()}


def chain_label(levels: Sequence[Level]) -> str:
    """Noms des niveaux validés, joints par ``", "``."""
    return ", ".join(level.name for level in validated(levels))
