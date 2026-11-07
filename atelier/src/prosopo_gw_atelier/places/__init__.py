"""Places step: collection of place writings and their decomposition."""

from .collect import collect_writings
from .decompose import decompose
from .model import Decomposition, Element, ElementKind, Occurrence, Writing

__all__ = [
    "Decomposition",
    "Element",
    "ElementKind",
    "Occurrence",
    "Writing",
    "collect_writings",
    "decompose",
]
