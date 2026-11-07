"""Reference data: INSEE COG communes, departments, regions, countries, postal codes."""

from .loader import Commune, NameMatch, RefData, load_refdata
from .normalize import normalize

__all__ = ["Commune", "NameMatch", "RefData", "load_refdata", "normalize"]
