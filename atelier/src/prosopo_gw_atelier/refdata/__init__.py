"""Reference data: INSEE COG communes, departments, regions, countries, postal codes."""

from .arrondissements import (
    CITY_INSEE,
    Arrondissement,
    City,
    by_code,
    city_of,
    current,
    former_paris,
    level_id,
    level_name,
    numbers,
)
from .loader import Commune, Former, FormerNature, NameMatch, RefData, load_refdata
from .normalize import normalize

__all__ = [
    "CITY_INSEE",
    "Arrondissement",
    "City",
    "by_code",
    "city_of",
    "current",
    "former_paris",
    "level_id",
    "level_name",
    "numbers",
    "Commune",
    "Former",
    "FormerNature",
    "NameMatch",
    "RefData",
    "load_refdata",
    "normalize",
]
