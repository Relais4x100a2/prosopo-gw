"""
Router FastAPI pour la gestion des familles dans l'API geneweb-py.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ...core.family import MarriageStatus
from ...core.person import Person
from ..dependencies import get_session_service, require_write_mode
from ..family_payload import family_to_family_schema, family_to_list_schema
from ..models.family import (
    FamilyCreateSchema,
    FamilySearchSchema,
    FamilyStatsSchema,
    FamilyUpdateSchema,
)
from ..models.responses import (
    PaginatedResponse,
    PaginationInfo,
    SuccessResponse,
)
from ..person_payload import person_to_list_schema
from ..router_helpers import raise_internal_server_error
from ..serialization import event_to_schema, stable_event_id
from ..services.genealogy_service import GenealogyService

router = APIRouter()


@router.post(
    "/",
    response_model=SuccessResponse,
    status_code=201,
    dependencies=[Depends(require_write_mode)],
)
async def create_family(
    family_data: FamilyCreateSchema,
    service: GenealogyService = Depends(get_session_service),
) -> SuccessResponse:
    """
    Crée une nouvelle famille.

    Args:
        family_data: Données de la famille à créer
        service: Service de généalogie

    Returns:
        SuccessResponse: Réponse de succès avec les données de la famille
    """
    try:
        family = service.create_family(family_data)

        family_schema = family_to_family_schema(family)

        return SuccessResponse(
            message="Famille créée avec succès", data=family_schema.model_dump()
        )

    except Exception as exc:
        raise_internal_server_error(
            "Erreur lors de la création d'une famille dans l'API", exc
        )


@router.get("/{family_id}", response_model=SuccessResponse)
async def get_family(
    family_id: str, service: GenealogyService = Depends(get_session_service)
) -> SuccessResponse:
    """
    Récupère une famille par son ID.

    Args:
        family_id: Identifiant de la famille
        service: Service de généalogie

    Returns:
        SuccessResponse: Réponse de succès avec les données de la famille
    """
    family = service.get_family(family_id)

    if family is None:
        raise HTTPException(
            status_code=404, detail=f"Famille avec l'ID '{family_id}' non trouvée"
        )

    family_schema = family_to_family_schema(family)

    return SuccessResponse(
        message="Famille récupérée avec succès", data=family_schema.model_dump()
    )


@router.put(
    "/{family_id}",
    response_model=SuccessResponse,
    dependencies=[Depends(require_write_mode)],
)
async def update_family(
    family_id: str,
    family_data: FamilyUpdateSchema,
    service: GenealogyService = Depends(get_session_service),
) -> SuccessResponse:
    """
    Met à jour une famille.

    Args:
        family_id: Identifiant de la famille
        family_data: Nouvelles données de la famille
        service: Service de généalogie

    Returns:
        SuccessResponse: Réponse de succès avec les données mises à jour
    """
    family = service.update_family(family_id, family_data)

    if family is None:
        raise HTTPException(
            status_code=404, detail=f"Famille avec l'ID '{family_id}' non trouvée"
        )

    family_schema = family_to_family_schema(family)

    return SuccessResponse(
        message="Famille mise à jour avec succès", data=family_schema.model_dump()
    )


@router.delete(
    "/{family_id}",
    response_model=SuccessResponse,
    dependencies=[Depends(require_write_mode)],
)
async def delete_family(
    family_id: str, service: GenealogyService = Depends(get_session_service)
) -> SuccessResponse:
    """
    Supprime une famille.

    Args:
        family_id: Identifiant de la famille
        service: Service de généalogie

    Returns:
        SuccessResponse: Réponse de succès
    """
    success = service.delete_family(family_id)

    if not success:
        raise HTTPException(
            status_code=404, detail=f"Famille avec l'ID '{family_id}' non trouvée"
        )

    return SuccessResponse(message="Famille supprimée avec succès")


@router.get("/", response_model=PaginatedResponse)
async def list_families(
    page: int = Query(1, ge=1, description="Numéro de page"),
    size: int = Query(20, ge=1, le=100, description="Taille de la page"),
    query: str | None = Query(None, description="Recherche textuelle"),
    husband_id: str | None = Query(None, description="Filtrer par mari"),
    wife_id: str | None = Query(None, description="Filtrer par épouse"),
    marriage_status: MarriageStatus | None = Query(
        None, description="Filtrer par statut de mariage"
    ),
    has_children: bool | None = Query(
        None, description="Filtrer par présence d'enfants"
    ),
    min_children: int | None = Query(
        None, ge=0, description="Nombre minimum d'enfants"
    ),
    max_children: int | None = Query(
        None, ge=0, description="Nombre maximum d'enfants"
    ),
    service: GenealogyService = Depends(get_session_service),
) -> PaginatedResponse:
    """
    Liste les familles avec pagination et filtres.

    Args:
        page: Numéro de page
        size: Taille de la page
        query: Recherche textuelle
        husband_id: Filtre par mari
        wife_id: Filtre par épouse
        marriage_status: Filtre par statut de mariage
        has_children: Filtre par présence d'enfants
        min_children: Nombre minimum d'enfants
        max_children: Nombre maximum d'enfants
        service: Service de généalogie

    Returns:
        PaginatedResponse: Réponse paginée avec les familles
    """
    # Construction des paramètres de recherche
    search_params = FamilySearchSchema(
        page=page,
        size=size,
        query=query,
        husband_id=husband_id,
        wife_id=wife_id,
        marriage_status=marriage_status,
        marriage_year_from=None,
        marriage_year_to=None,
        divorce_year_from=None,
        divorce_year_to=None,
        place=None,
        has_children=has_children,
        min_children=min_children,
        max_children=max_children,
    )

    families, total = service.search_families(search_params)

    # Conversion vers les schémas de liste
    family_list = []
    for family in families:
        family_list.append(family_to_list_schema(family).model_dump())

    # Calcul de la pagination
    total_pages = (total + size - 1) // size
    has_next = page < total_pages
    has_prev = page > 1

    pagination = PaginationInfo(
        page=page,
        size=size,
        total=total,
        pages=total_pages,
        has_next=has_next,
        has_prev=has_prev,
    )

    return PaginatedResponse(items=family_list, pagination=pagination)


@router.get("/{family_id}/children", response_model=SuccessResponse)
async def get_family_children(
    family_id: str, service: GenealogyService = Depends(get_session_service)
) -> SuccessResponse:
    """
    Récupère les enfants d'une famille.

    Args:
        family_id: Identifiant de la famille
        service: Service de généalogie

    Returns:
        SuccessResponse: Réponse avec les enfants de la famille
    """
    family = service.get_family(family_id)

    if family is None:
        raise HTTPException(
            status_code=404, detail=f"Famille avec l'ID '{family_id}' non trouvée"
        )

    genealogy = service.genealogy
    children_out: list[dict[str, Any]] = []
    for ch in family.children:
        if isinstance(ch, str):
            pid: str = ch
            sex_val: str | None = None
            last: str | None = None
        else:
            pid = ch.person_id
            sex_val = ch.sex.value if ch.sex else None
            last = ch.last_name

        child_person = genealogy.persons.get(pid)
        if isinstance(child_person, Person):
            children_out.append(
                {
                    "person_id": pid,
                    "sex": sex_val,
                    "last_name": last,
                    "person": person_to_list_schema(child_person).model_dump(),
                }
            )
        else:
            children_out.append(
                {
                    "person_id": pid,
                    "sex": sex_val,
                    "last_name": last,
                    "person": None,
                }
            )

    return SuccessResponse(message="Enfants récupérés avec succès", data=children_out)


@router.get("/{family_id}/events", response_model=SuccessResponse)
async def get_family_events(
    family_id: str, service: GenealogyService = Depends(get_session_service)
) -> SuccessResponse:
    """
    Récupère les événements d'une famille.

    Args:
        family_id: Identifiant de la famille
        service: Service de généalogie

    Returns:
        SuccessResponse: Réponse avec les événements de la famille
    """
    try:
        family = service.get_family(family_id)

        if family is None:
            raise HTTPException(
                status_code=404, detail=f"Famille avec l'ID '{family_id}' non trouvée"
            )

        events = []
        for idx, event in enumerate(family.events):
            uid = getattr(event, "unique_id", None)
            eid = (
                str(uid)
                if uid is not None
                else stable_event_id(
                    event, scope="family", scope_key=family_id, index=idx
                )
            )
            events.append(
                event_to_schema(
                    event,
                    event_id=eid,
                    person_id=None,
                    family_id=family_id,
                    genealogy=service.genealogy,
                ).model_dump()
            )

        return SuccessResponse(message="Événements récupérés avec succès", data=events)

    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(
            "Erreur lors de la récupération des événements d'une famille", exc
        )


@router.get("/stats/overview", response_model=SuccessResponse)
async def get_family_stats(
    service: GenealogyService = Depends(get_session_service),
) -> SuccessResponse:
    """
    Récupère les statistiques des familles.

    Args:
        service: Service de généalogie

    Returns:
        SuccessResponse: Réponse avec les statistiques
    """
    stats = service.get_stats()

    family_stats = FamilyStatsSchema(
        total=stats["total_families"],
        by_status=stats["families_by_status"],
        by_century=stats.get("families_by_marriage_century", {}),
        with_marriage_date=stats.get("families_with_marriage_date", 0),
        with_divorce_date=stats.get("families_with_divorce_date", 0),
        average_children=stats["average_children_per_family"],
        families_with_children=stats["families_with_children"],
    )

    return SuccessResponse(
        message="Statistiques récupérées avec succès", data=family_stats.model_dump()
    )
