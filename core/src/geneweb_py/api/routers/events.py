"""
Router FastAPI pour la gestion des événements dans l'API geneweb-py.
"""

from typing import Any, Dict, Generator, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query

from ...core.event import Event
from ...core.person import Person
from ..dependencies import get_session_service, require_write_mode
from ..models.event import (
    EventUpdateSchema,
    FamilyEventCreateSchema,
    PersonalEventCreateSchema,
)
from ..models.responses import (
    PaginatedResponse,
    PaginationInfo,
    SuccessResponse,
)
from ..router_helpers import raise_internal_server_error
from ..serialization import event_to_schema, stable_event_id
from ..services.genealogy_service import EventSearchHit, GenealogyService

router = APIRouter()


def _person_events_index_for_response(person: object) -> int:
    """Indice pour ``stable_event_id`` (service mock ou réel)."""
    evs = getattr(person, "events", None)
    if isinstance(evs, list) and evs:
        return len(evs) - 1
    return 0


def _family_events_index_for_response(family: object) -> int:
    """Indice pour événement familial (``stable_event_id``)."""
    evs = getattr(family, "events", None)
    if isinstance(evs, list) and evs:
        return len(evs) - 1
    return 0


def _unpack_event_context(
    service: GenealogyService, event: Event
) -> Tuple[Optional[str], Optional[str], int]:
    """Décompacte le contexte d'événement si le service le fournit correctement."""
    ctx = service.get_event_context(event)
    if isinstance(ctx, tuple) and len(ctx) == 3:
        return ctx[0], ctx[1], ctx[2]
    return (
        getattr(event, "person_id", None),
        getattr(event, "family_id", None),
        -1,
    )


def _iterate_search_events(
    service: GenealogyService, hits: object
) -> Generator[Tuple[Event, Optional[str], Optional[str], int], None, None]:
    """Parcourt ``search_events`` : ``EventSearchHit`` ou liste d'``Event``."""
    if not isinstance(hits, list):
        return
    for item in hits:
        if isinstance(item, EventSearchHit):
            yield item.event, item.person_id, item.family_id, item.index
        else:
            ev = item
            pid, fid, ev_idx = _unpack_event_context(service, ev)
            yield ev, pid, fid, ev_idx


@router.post(
    "/personal",
    response_model=SuccessResponse,
    status_code=201,
    dependencies=[Depends(require_write_mode)],
)
async def create_personal_event(
    event_data: PersonalEventCreateSchema,
    service: GenealogyService = Depends(get_session_service),
) -> SuccessResponse:
    """
    Crée un nouvel événement personnel.

    Args:
        event_data: Données de l'événement à créer
        service: Service de généalogie

    Returns:
        SuccessResponse: Réponse de succès avec les données de l'événement
    """
    try:
        event = service.create_personal_event(event_data)
        person = service.get_person(event_data.person_id)
        if person is None:
            raise HTTPException(status_code=400, detail="Personne introuvable")
        idx = _person_events_index_for_response(person)
        person_key = (
            person.unique_id
            if isinstance(person, Person)
            else str(event_data.person_id)
        )
        uid = getattr(event, "unique_id", None)
        eid = (
            str(uid)
            if uid is not None
            else stable_event_id(event, scope="person", scope_key=person_key, index=idx)
        )
        event_schema = event_to_schema(
            event,
            event_id=eid,
            person_id=person_key,
            family_id=None,
            genealogy=service.genealogy,
        )

        return SuccessResponse(
            message="Événement personnel créé avec succès",
            data=event_schema.model_dump(),
        )

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(
            "Erreur lors de la création d'un événement personnel", exc
        )


@router.post(
    "/family",
    response_model=SuccessResponse,
    status_code=201,
    dependencies=[Depends(require_write_mode)],
)
async def create_family_event(
    event_data: FamilyEventCreateSchema,
    service: GenealogyService = Depends(get_session_service),
) -> SuccessResponse:
    """
    Crée un nouvel événement familial.

    Args:
        event_data: Données de l'événement à créer
        service: Service de généalogie

    Returns:
        SuccessResponse: Réponse de succès avec les données de l'événement
    """
    try:
        event = service.create_family_event(event_data)
        family = service.get_family(event_data.family_id)
        if family is None:
            raise HTTPException(status_code=400, detail="Famille introuvable")
        idx = _family_events_index_for_response(family)
        uid = getattr(event, "unique_id", None)
        eid = (
            str(uid)
            if uid is not None
            else stable_event_id(
                event, scope="family", scope_key=event_data.family_id, index=idx
            )
        )
        event_schema = event_to_schema(
            event,
            event_id=eid,
            person_id=None,
            family_id=event_data.family_id,
            genealogy=service.genealogy,
        )

        return SuccessResponse(
            message="Événement familial créé avec succès",
            data=event_schema.model_dump(),
        )

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(
            "Erreur lors de la création d'un événement familial", exc
        )


@router.get("/{event_id}", response_model=SuccessResponse)
async def get_event(
    event_id: str, service: GenealogyService = Depends(get_session_service)
) -> SuccessResponse:
    """
    Récupère un événement par son ID.

    Args:
        event_id: Identifiant de l'événement
        service: Service de généalogie

    Returns:
        SuccessResponse: Réponse avec les données de l'événement
    """
    try:
        event = service.get_event(event_id)

        if event is None:
            raise HTTPException(
                status_code=404, detail=f"Événement avec l'ID {event_id} non trouvé"
            )

        pid, fid, ev_idx = _unpack_event_context(service, event)
        uid = getattr(event, "unique_id", None)
        if uid is not None:
            eid = str(uid)
        elif pid is not None and ev_idx >= 0:
            eid = stable_event_id(event, scope="person", scope_key=pid, index=ev_idx)
        elif fid is not None and ev_idx >= 0:
            eid = stable_event_id(event, scope="family", scope_key=fid, index=ev_idx)
        else:
            eid = event_id
        event_schema = event_to_schema(
            event,
            event_id=eid,
            person_id=pid or getattr(event, "person_id", None),
            family_id=fid or getattr(event, "family_id", None),
            genealogy=service.genealogy,
        )

        return SuccessResponse(
            message="Événement récupéré avec succès", data=event_schema.model_dump()
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(
            "Erreur lors de la récupération d'un événement par identifiant", exc
        )


@router.put(
    "/{event_id}",
    response_model=SuccessResponse,
    dependencies=[Depends(require_write_mode)],
)
async def update_event(
    event_id: str,
    event_data: EventUpdateSchema,
    service: GenealogyService = Depends(get_session_service),
) -> SuccessResponse:
    """
    Met à jour un événement.

    Args:
        event_id: Identifiant de l'événement
        event_data: Nouvelles données de l'événement
        service: Service de généalogie

    Returns:
        SuccessResponse: Réponse de succès avec les données mises à jour
    """
    try:
        event = service.update_event(event_id, event_data)

        if event is None:
            raise HTTPException(
                status_code=404, detail=f"Événement avec l'ID {event_id} non trouvé"
            )

        pid, fid, ev_idx = _unpack_event_context(service, event)
        uid = getattr(event, "unique_id", None)
        if uid is not None:
            eid = str(uid)
        elif pid is not None and ev_idx >= 0:
            eid = stable_event_id(event, scope="person", scope_key=pid, index=ev_idx)
        elif fid is not None and ev_idx >= 0:
            eid = stable_event_id(event, scope="family", scope_key=fid, index=ev_idx)
        else:
            eid = event_id
        event_schema = event_to_schema(
            event,
            event_id=eid,
            person_id=pid or getattr(event, "person_id", None),
            family_id=fid or getattr(event, "family_id", None),
            genealogy=service.genealogy,
        )

        return SuccessResponse(
            message="Événement mis à jour avec succès", data=event_schema.model_dump()
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error("Erreur lors de la mise à jour d'un événement", exc)


@router.delete(
    "/{event_id}",
    response_model=SuccessResponse,
    dependencies=[Depends(require_write_mode)],
)
async def delete_event(
    event_id: str, service: GenealogyService = Depends(get_session_service)
) -> SuccessResponse:
    """
    Supprime un événement.

    Args:
        event_id: Identifiant de l'événement
        service: Service de généalogie

    Returns:
        SuccessResponse: Réponse de succès
    """
    try:
        success = service.delete_event(event_id)

        if not success:
            raise HTTPException(
                status_code=404, detail=f"Événement avec l'ID {event_id} non trouvé"
            )

        return SuccessResponse(
            message="Événement supprimé avec succès", data={"event_id": event_id}
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error("Erreur lors de la suppression d'un événement", exc)


@router.get("/", response_model=PaginatedResponse)
async def list_events(
    page: int = Query(1, ge=1, description="Numéro de page"),
    size: int = Query(20, ge=1, le=100, description="Taille de la page"),
    query: Optional[str] = Query(None, description="Recherche textuelle"),
    event_type: Optional[str] = Query(
        None,
        description="Filtrer par type d'événement (plusieurs types séparés par des virgules)",
    ),
    person_id: Optional[str] = Query(None, description="Filtrer par personne"),
    related_to: Optional[str] = Query(
        None,
        description="Personne de référence : ne garde que les événements de ses liens, jusqu'à `degree`",
    ),
    degree: int = Query(1, ge=1, le=3, description="Degré de lien pour `related_to`"),
    family_name: Optional[str] = Query(
        None, description="Nom de famille (personne ou époux), sans accents ni casse"
    ),
    family_id: Optional[str] = Query(None, description="Filtrer par famille"),
    year_from: Optional[int] = Query(
        None, ge=1000, le=3000, description="Année minimum"
    ),
    year_to: Optional[int] = Query(None, ge=1000, le=3000, description="Année maximum"),
    place: Optional[str] = Query(None, description="Filtrer par lieu"),
    has_witnesses: Optional[bool] = Query(
        None, description="Filtrer par présence de témoins"
    ),
    has_sources: Optional[bool] = Query(
        None, description="Filtrer par présence de sources"
    ),
    service: GenealogyService = Depends(get_session_service),
) -> PaginatedResponse:
    """
    Liste les événements avec pagination et filtres.

    Args:
        page: Numéro de page
        size: Taille de la page
        query: Recherche textuelle
        event_type: Filtre par type d'événement (liste séparée par des virgules)
        person_id: Filtre par personne
        related_to: Personne de référence pour le filtre de liens
        degree: Degré de lien (1 à 3) pour ``related_to``
        family_name: Filtre par nom de famille
        family_id: Filtre par famille
        year_from: Année minimum
        year_to: Année maximum
        place: Filtre par lieu
        has_witnesses: Filtre par présence de témoins
        has_sources: Filtre par présence de sources
        service: Service de généalogie

    Returns:
        PaginatedResponse: Réponse paginée avec les événements
    """
    try:
        # Construction des paramètres de recherche
        search_params: Dict[str, Any] = {
            "page": page,
            "size": size,
            "query": query,
            "event_type": event_type,
            "person_id": person_id,
            "related_to": related_to,
            "family_name": family_name,
            "family_id": family_id,
            "place": place,
            "has_witnesses": has_witnesses,
            "has_sources": has_sources,
        }

        # Suppression des valeurs None
        search_params = {k: v for k, v in search_params.items() if v is not None}

        if related_to:
            search_params["degree"] = degree

        if event_type and "," in event_type:
            search_params.pop("event_type")
            search_params["event_types"] = [
                t.strip() for t in event_type.split(",") if t.strip()
            ]

        events, total = service.search_events(search_params)

        # Conversion vers les schémas de réponse
        event_schemas = []
        for ev, hit_pid, hit_fid, hit_idx in _iterate_search_events(service, events):
            uid = getattr(ev, "unique_id", None)
            if uid is not None:
                eid = str(uid)
            elif hit_pid is not None and hit_idx >= 0:
                eid = stable_event_id(
                    ev,
                    scope="person",
                    scope_key=hit_pid,
                    index=hit_idx,
                )
            elif hit_fid is not None and hit_idx >= 0:
                eid = stable_event_id(
                    ev,
                    scope="family",
                    scope_key=hit_fid,
                    index=hit_idx,
                )
            else:
                eid = "unknown"
            event_schemas.append(
                event_to_schema(
                    ev,
                    event_id=eid,
                    person_id=hit_pid or getattr(ev, "person_id", None),
                    family_id=hit_fid or getattr(ev, "family_id", None),
                    genealogy=service.genealogy,
                ).model_dump()
            )

        # Calcul de la pagination
        total_pages = (total + size - 1) // size
        has_next = page < total_pages
        has_prev = page > 1

        pagination_info = PaginationInfo(
            page=page,
            size=size,
            total=total,
            pages=total_pages,
            has_next=has_next,
            has_prev=has_prev,
        )

        return PaginatedResponse(items=event_schemas, pagination=pagination_info)

    except Exception as exc:
        raise_internal_server_error(
            "Erreur lors de la liste ou recherche d'événements", exc
        )


@router.get("/stats/overview", response_model=SuccessResponse)
async def get_event_stats(
    service: GenealogyService = Depends(get_session_service),
) -> SuccessResponse:
    """
    Récupère les statistiques des événements.

    Args:
        service: Service de généalogie

    Returns:
        SuccessResponse: Réponse avec les statistiques
    """
    try:
        stats = service.get_stats()

        # Extraction des statistiques d'événements
        event_stats = {
            "total_events": stats.get("total_events", 0),
            "personal_events": stats.get("personal_events", 0),
            "family_events": stats.get("family_events", 0),
            "events_by_type": stats.get("events_by_type", {}),
            "events_by_century": stats.get("events_by_century", {}),
        }

        return SuccessResponse(
            message="Statistiques des événements récupérées avec succès",
            data=event_stats,
        )

    except Exception as exc:
        raise_internal_server_error(
            "Erreur lors de la récupération des statistiques d'événements", exc
        )
