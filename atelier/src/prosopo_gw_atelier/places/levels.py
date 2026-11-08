"""Modèle de niveaux d'un lieu : chaîne ordonnée, du plus précis (rang 0) au plus large.

Un niveau porte un nom, un type facultatif (liste ouverte : tout slug conforme à
``TYPE_PATTERN`` passe), une origine et un statut. Seuls les niveaux validés comptent
pour la vue française (``french_view``), l'étiquette (``chain_label``) et l'export ;
les niveaux proposés attendent une décision.

``rule_levels`` propose la chaîne d'une écriture décomposée (fonction pure, lecture
seule du référentiel). Commune résolue : ``commune_historique`` (fusion, association,
délégation), ``commune``, ``departement``, ``ancienne_region`` si elle est écrite,
``region`` et ``pays`` « France », d'origine ``insee`` (``pays`` d'origine ``written``
s'il est écrit). Un segment écrit qui ne remplit aucun de ces niveaux (non reconnu, ou
en désaccord avec la commune) devient un niveau sans type, d'origine ``written`` :
avant la commune s'il est écrit avant tout niveau reconnu, sinon juste après le niveau
reconnu qui le précède. Commune non résolue : un niveau par segment, dans l'ordre
écrit ; pays, département et région reconnus prennent leur type et leur nom normalisé
(origine ``rule`` si ce nom diffère de l'écrit, gardé dans ``written``). Les codes
INSEE et postaux ne sont jamais des niveaux ; ``written_postal_code`` rend le code
postal écrit.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

from ..refdata import Former, RefData
from .decompose import HINT_OLD_REGION, is_code
from .model import Decomposition

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
TYPE_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,39}")
FRANCE = "France"


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
        if level.type is not None and not TYPE_PATTERN.fullmatch(level.type):
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


def written_postal_code(decomposition: Decomposition) -> str | None:
    """Premier code postal écrit, s'il y en a un."""
    for segment in decomposition.segments:
        if segment.element is not None and segment.element.kind == "postal_code":
            return segment.element.value
    return None


def rule_levels(decomposition: Decomposition, ref: RefData) -> tuple[Level, ...]:
    """Chaîne de niveaux validés proposée par les règles pour une écriture."""
    if decomposition.insee is not None:
        chain = _resolved_levels(
            decomposition, ref, decomposition.insee, decomposition.historical
        )
        if chain is not None:
            return chain
    return _unresolved_levels(decomposition, ref)


def alternative_levels(
    decomposition: Decomposition, ref: RefData
) -> tuple[Level, ...] | None:
    """Chaîne de la lecture ``alternative`` (ancienne commune), ``None`` sans elle."""
    alternative = decomposition.alternative
    if alternative is None:
        return None
    return _resolved_levels(decomposition, ref, alternative.current, alternative)


def _written(text: str | None, name: str) -> str | None:
    """Écrit gardé quand il diffère du nom retenu."""
    return text if text and text != name else None


def _resolved_levels(
    decomposition: Decomposition, ref: RefData, insee: str, historical: Former | None
) -> tuple[Level, ...] | None:
    """Chaîne française d'une commune résolue (choix 8 du plan pour l'ordre)."""
    commune = ref.commune_by_insee(insee)
    if commune is None:
        return None
    source = f"COG {ref.cog_vintage}"
    region_name = ref.region_name(commune.region)
    slots = ("commune", "departement", "ancienne_region", "region", "pays")
    used: set[str] = set()
    before: list[Level] = []
    after: dict[str, list[Level]] = {slot: [] for slot in slots}
    name_text: str | None = None
    country_text: str | None = None
    old_region: Level | None = None
    last: str | None = None
    for segment in decomposition.segments:
        element = segment.element
        if is_code(segment.text):
            continue
        slot: str | None = None
        if element is None:
            pass
        elif element.kind in ("commune", "former_name"):
            if name_text is None:
                name_text, slot = segment.text, "commune"
        elif element.kind == "department" and element.value == commune.department:
            slot = "departement"
        elif element.kind == "region" and element.hint == HINT_OLD_REGION:
            if old_region is None:
                slot = "ancienne_region"
                old_region = Level(
                    0,
                    element.value,
                    written=_written(segment.text, element.value),
                    type=slot,
                    origin="written",
                )
        elif element.kind == "region" and element.value == region_name:
            slot = "region"
        elif element.kind == "country" and element.value == FRANCE:
            if country_text is None:
                country_text, slot = segment.text, "pays"
        if slot is None or slot in used:
            level = Level(0, segment.text, origin="written")
            (before if last is None else after[last]).append(level)
            continue
        used.add(slot)
        last = slot

    commune_block: list[Level] = []
    if historical is not None:
        commune_block.append(
            Level(
                0,
                historical.name,
                written=_written(name_text, historical.name),
                type="commune_historique",
                identifier=historical.insee,
                source=source,
                end=historical.date or None,
                nature=None if historical.nature == "renommage" else historical.nature,
                origin="insee",
            )
        )
    commune_block.append(
        Level(
            0,
            commune.name,
            written=None if historical else _written(name_text, commune.name),
            type="commune",
            identifier=commune.insee,
            source=source,
            origin="insee",
        )
    )
    department_name = ref.department_name(commune.department) or commune.department
    built: dict[str, list[Level]] = {
        "commune": commune_block,
        "departement": [
            Level(
                0,
                department_name,
                type="departement",
                identifier=commune.department,
                source=source,
                origin="insee",
            )
        ],
        "ancienne_region": [old_region] if old_region is not None else [],
        "region": (
            [Level(0, region_name, type="region", source=source, origin="insee")]
            if region_name
            else []
        ),
        "pays": [
            Level(
                0,
                FRANCE,
                written=_written(country_text, FRANCE),
                type="pays",
                source=None if country_text else source,
                origin="written" if country_text else "insee",
            )
        ],
    }
    chain = [*before]
    for slot in slots:
        chain.extend(built[slot])
        chain.extend(after[slot])
    return renumber(chain)


def _unresolved_levels(decomposition: Decomposition, ref: RefData) -> tuple[Level, ...]:
    """Un niveau par segment écrit non code, dans l'ordre écrit."""
    chain: list[Level] = []
    for segment in decomposition.segments:
        if is_code(segment.text):
            continue
        element = segment.element
        type_: str | None = None
        name = segment.text
        identifier: str | None = None
        if element is not None and element.kind == "country":
            type_, name = "pays", element.value
        elif element is not None and element.kind == "department":
            type_, identifier = "departement", element.value
            name = ref.department_name(element.value) or element.value
        elif element is not None and element.kind == "region":
            old = element.hint == HINT_OLD_REGION
            type_, name = ("ancienne_region" if old else "region"), element.value
        written = _written(segment.text, name)
        chain.append(
            Level(
                0,
                name,
                written=written,
                type=type_,
                identifier=identifier,
                origin="written" if written is None else "rule",
            )
        )
    return renumber(chain)
