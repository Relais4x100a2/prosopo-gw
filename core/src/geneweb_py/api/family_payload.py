"""
Construction des charges utiles Family pour les réponses API.
"""

from ..core.family import Family
from .models.family import FamilyListSchema, FamilySchema
from .serialization import child_to_schema, date_to_api_string, stable_event_id


def _divorce_place_from_family(family: Family) -> str | None:
    """Lieu de divorce si stocké en métadonnées du parseur."""
    if not family.metadata:
        return None
    raw = family.metadata.get("divorce_place")
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def family_to_family_schema(family: Family) -> FamilySchema:
    """Convertit une famille domaine en schéma API complet."""
    src_list: list[str] = []
    if family.family_source and str(family.family_source).strip():
        src_list.append(str(family.family_source).strip())

    event_ids: list[str] = []
    for idx, ev in enumerate(family.events):
        uid = getattr(ev, "unique_id", None)
        if uid is not None:
            event_ids.append(str(uid))
        else:
            event_ids.append(
                stable_event_id(
                    ev, scope="family", scope_key=family.family_id, index=idx
                )
            )

    return FamilySchema(
        id=family.family_id,
        husband_id=family.husband_id,
        wife_id=family.wife_id,
        children=[child_to_schema(c) for c in family.children],
        marriage_status=family.marriage_status,
        notes=family.comments,
        sources=src_list,
        marriage_date=date_to_api_string(family.marriage_date),
        marriage_place=family.marriage_place,
        divorce_date=date_to_api_string(family.divorce_date),
        divorce_place=_divorce_place_from_family(family),
        events=event_ids,
    )


def family_to_list_schema(family: Family) -> FamilyListSchema:
    """Schéma liste famille avec date de mariage."""
    return FamilyListSchema(
        id=family.family_id,
        husband_id=family.husband_id,
        wife_id=family.wife_id,
        children_count=len(family.children),
        marriage_date=date_to_api_string(family.marriage_date),
        marriage_status=family.marriage_status,
    )
