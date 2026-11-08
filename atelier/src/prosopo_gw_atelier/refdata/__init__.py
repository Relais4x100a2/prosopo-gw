"""Reference data: INSEE COG communes, departments, regions, countries, postal codes."""

from .loader import Commune, Former, FormerNature, NameMatch, RefData, load_refdata
from .normalize import normalize

__all__ = [
    "Commune",
    "Former",
    "FormerNature",
    "NameMatch",
    "RefData",
    "load_refdata",
    "normalize",
]
