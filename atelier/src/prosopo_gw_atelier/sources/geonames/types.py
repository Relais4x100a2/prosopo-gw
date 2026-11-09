"""Level types for GeoNames feature codes, per country.

``PPL*`` (populated places) are ``localite``. The first- and second-level
administrative divisions (``ADM1``, ``ADM2``) get a type that depends on the country:
``ADMIN_TYPES`` maps an ISO 3166 alpha-2 code to the types of ``(ADM1, ADM2)``,
``None`` where the level has no type of the foreign list. A country missing from the
table gets no administrative type: its levels are proposed with an identifier only.
Complete the table to cover more countries; every type must be in ``FOREIGN_TYPES``.
"""

from __future__ import annotations

ADMIN_TYPES: dict[str, tuple[str | None, str | None]] = {
    "CA": ("province", None),
    "US": ("etat", "comte"),
    "GB": ("nation_constitutive", "comte"),
    "IE": ("province", "comte"),
    "RU": ("oblast", "district"),
    "UA": ("oblast", "district"),
    "BY": ("oblast", "district"),
    "KZ": ("oblast", "district"),
    "CH": ("canton", "district"),
    "DE": ("etat", "district"),
    "AT": ("etat", "district"),
    "BE": (None, "province"),
    "NL": ("province", None),
    "IT": (None, "province"),
    "ES": (None, "province"),
}

__all__ = ["ADMIN_TYPES", "level_type"]


def level_type(feature_code: str, country: str) -> str | None:
    """Level type of a GeoNames feature code in ``country`` (ISO2), or ``None``."""
    if feature_code.startswith("PPL"):
        return "localite"
    types = ADMIN_TYPES.get(country.upper())
    if types is None:
        return None
    if feature_code == "ADM1":
        return types[0]
    if feature_code == "ADM2":
        return types[1]
    return None
