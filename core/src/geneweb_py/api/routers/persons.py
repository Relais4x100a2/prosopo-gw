"""
Router FastAPI pour la gestion des personnes dans l'API geneweb-py.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from ..dependencies import get_session_service, require_write_mode
from ..family_payload import family_to_family_schema
from ..models.person import (
    PersonCreateSchema,
    PersonSearchSchema,
    PersonStatsSchema,
    PersonUpdateSchema,
)
from ..models.responses import (
    PaginatedResponse,
    PaginationInfo,
    SuccessResponse,
)
from ..person_payload import person_to_list_schema, person_to_person_schema
from ..router_helpers import raise_internal_server_error
from ..serialization import event_to_schema, stable_event_id
from ..services.genealogy_service import GenealogyService

router = APIRouter()

# Plafond de /names : couvre une page de 50 familles (100 conjoints) avec marge.
MAX_NAME_IDS = 200


@router.post(
    "/",
    response_model=SuccessResponse,
    status_code=201,
    dependencies=[Depends(require_write_mode)],
)
async def create_person(
    person_data: PersonCreateSchema,
    service: GenealogyService = Depends(get_session_service),
) -> SuccessResponse:
    """
    Crée une nouvelle personne.

    Args:
        person_data: Données de la personne à créer
        service: Service de généalogie

    Returns:
        SuccessResponse: Réponse de succès avec les données de la personne
    """
    try:
        person = service.create_person(person_data)

        person_schema = person_to_person_schema(person)

        return SuccessResponse(
            message="Personne créée avec succès", data=person_schema.model_dump()
        )

    except Exception as exc:
        raise_internal_server_error(
            "Erreur lors de la création d'une personne dans l'API", exc
        )


@router.get("/", response_model=PaginatedResponse)
async def list_persons(
    page: int = Query(1, ge=1, description="Numéro de page"),
    size: int = Query(20, ge=1, le=100, description="Taille de la page"),
    query: Optional[str] = Query(None, description="Recherche textuelle"),
    first_name: Optional[str] = Query(None, description="Filtrer par prénom"),
    surname: Optional[str] = Query(None, description="Filtrer par nom de famille"),
    sex: Optional[str] = Query(None, description="Filtrer par sexe"),
    access_level: Optional[str] = Query(None, description="Filtrer par niveau d'accès"),
    birth_year_from: Optional[int] = Query(
        None, ge=1000, le=3000, description="Année de naissance minimum"
    ),
    birth_year_to: Optional[int] = Query(
        None, ge=1000, le=3000, description="Année de naissance maximum"
    ),
    death_year_from: Optional[int] = Query(
        None, ge=1000, le=3000, description="Année de décès minimum"
    ),
    death_year_to: Optional[int] = Query(
        None, ge=1000, le=3000, description="Année de décès maximum"
    ),
    place: Optional[str] = Query(
        None,
        description=(
            "Filtrer par lieu (naissance, décès, baptême, sépulture) ; "
            "sous-chaîne après NFKC et sans tenir compte de la casse"
        ),
    ),
    service: GenealogyService = Depends(get_session_service),
) -> PaginatedResponse:
    """
    Liste les personnes avec pagination et filtres.

    Args:
        page: Numéro de page
        size: Taille de la page
        query: Recherche textuelle
        first_name: Filtre par prénom
        surname: Filtre par nom de famille
        sex: Filtre par sexe
        access_level: Filtre par niveau d'accès
        birth_year_from: Borne inférieure année de naissance (filtre par overlap)
        birth_year_to: Borne supérieure année de naissance
        death_year_from: Borne inférieure année de décès
        death_year_to: Borne supérieure année de décès
        place: Sous-chaîne de lieu (NFKC + insensible à la casse)
        service: Service de généalogie

    Returns:
        PaginatedResponse: Réponse paginée avec les personnes
    """
    # Construction des paramètres de recherche (query → schéma Pydantic)
    raw_params: Dict[str, Any] = {
        "page": page,
        "size": size,
        "query": query,
        "first_name": first_name,
        "surname": surname,
        "sex": sex,
        "access_level": access_level,
        "birth_year_from": birth_year_from,
        "birth_year_to": birth_year_to,
        "death_year_from": death_year_from,
        "death_year_to": death_year_to,
        "place": place,
    }
    try:
        search_params = PersonSearchSchema.model_validate(raw_params)
    except ValidationError as exc:
        raise RequestValidationError(list(exc.errors())) from exc

    persons, total = service.search_persons(search_params)

    # Conversion vers les schémas de liste
    person_list = []
    for person in persons:
        person_list.append(person_to_list_schema(person).model_dump())

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

    return PaginatedResponse(items=person_list, pagination=pagination)


@router.get("/{person_id:path}/families", response_model=SuccessResponse)
async def get_person_families(
    person_id: str, service: GenealogyService = Depends(get_session_service)
) -> SuccessResponse:
    """
    Récupère les familles d'une personne.

    Args:
        person_id: Identifiant de la personne
        service: Service de généalogie

    Returns:
        SuccessResponse: Réponse avec les familles de la personne
    """
    person = service.get_person(person_id)

    if person is None:
        raise HTTPException(
            status_code=404, detail=f"Personne avec l'ID '{person_id}' non trouvée"
        )

    genealogy = service.genealogy
    families_out = []
    for fid in person.get_families():
        fam = genealogy.families.get(fid)
        if fam is not None:
            families_out.append(family_to_family_schema(fam).model_dump())

    return SuccessResponse(message="Familles récupérées avec succès", data=families_out)


@router.get("/{person_id:path}/events", response_model=SuccessResponse)
async def get_person_events(
    person_id: str, service: GenealogyService = Depends(get_session_service)
) -> SuccessResponse:
    """
    Récupère les événements d'une personne.

    Args:
        person_id: Identifiant de la personne
        service: Service de généalogie

    Returns:
        SuccessResponse: Réponse avec les événements de la personne
    """
    person = service.get_person(person_id)

    if person is None:
        raise HTTPException(
            status_code=404, detail=f"Personne avec l'ID '{person_id}' non trouvée"
        )

    events_out = []
    for idx, ev in enumerate(person.events):
        uid = getattr(ev, "unique_id", None)
        eid = (
            str(uid)
            if uid is not None
            else stable_event_id(
                ev, scope="person", scope_key=person.unique_id, index=idx
            )
        )
        events_out.append(
            event_to_schema(
                ev,
                event_id=eid,
                person_id=person.unique_id,
                family_id=None,
                genealogy=service.genealogy,
            ).model_dump()
        )

    return SuccessResponse(message="Événements récupérés avec succès", data=events_out)


@router.get("/{person_id:path}/related", response_model=SuccessResponse)
async def get_related_persons(
    person_id: str,
    degree: int = Query(1, ge=1, le=3, description="Degré de lien (1, 2 ou 3)"),
    service: GenealogyService = Depends(get_session_service),
) -> SuccessResponse:
    """
    Retourne les person_ids et family_ids liés à person_id jusqu'au degré donné.

    Args:
        person_id: Identifiant de la personne
        degree: Degré de lien (1, 2 ou 3)
        service: Service de généalogie

    Returns:
        SuccessResponse: Réponse avec les personnes et familles liées
    """
    try:
        result = service.get_related_person_ids(person_id, degree)
        return SuccessResponse(
            message="Personnes liées récupérées avec succès",
            data=result,
        )
    except Exception as exc:
        raise_internal_server_error(
            "Erreur lors de la récupération des personnes liées", exc
        )


@router.get("/names", response_model=SuccessResponse)
async def get_person_names(
    ids: List[str] = Query(
        default_factory=list,
        description="Identifiants (paramètre répété : ?ids=a&ids=b)",
    ),
    service: GenealogyService = Depends(get_session_service),
) -> SuccessResponse:
    """
    Résout en une requête les noms de plusieurs personnes.

    Évite le N+1 côté client (une requête par conjoint, parent ou enfant).
    Les identifiants inconnus sont simplement absents du résultat.

    Returns:
        SuccessResponse: ``data`` = ``{id: {first_name, surname, birth_date,
        death_date}}``
    """
    if len(ids) > MAX_NAME_IDS:
        raise RequestValidationError(
            [
                {
                    "type": "too_long",
                    "loc": ("query", "ids"),
                    "msg": f"Au plus {MAX_NAME_IDS} identifiants par requête",
                    "input": len(ids),
                }
            ]
        )
    names: Dict[str, Dict[str, Any]] = {}
    for person_id in dict.fromkeys(ids):
        person = service.get_person(person_id)
        if person is None:
            continue
        item = person_to_list_schema(person)
        names[person_id] = {
            "first_name": item.first_name,
            "surname": item.surname,
            "birth_date": item.birth_date,
            "death_date": item.death_date,
        }
    return SuccessResponse(message=f"{len(names)} nom(s) résolu(s)", data=names)


@router.get("/stats/overview", response_model=SuccessResponse)
async def get_person_stats(
    service: GenealogyService = Depends(get_session_service),
) -> SuccessResponse:
    """
    Récupère les statistiques des personnes.

    Args:
        service: Service de généalogie

    Returns:
        SuccessResponse: Réponse avec les statistiques
    """
    stats = service.get_stats()

    person_stats = PersonStatsSchema(
        total=stats["total_persons"],
        by_sex=stats["persons_by_sex"],
        by_access_level=stats["persons_by_access_level"],
        by_century=stats.get("persons_by_birth_century", {}),
        with_birth_date=stats["persons_with_birth_date"],
        with_death_date=stats["persons_with_death_date"],
    )

    return SuccessResponse(
        message="Statistiques récupérées avec succès", data=person_stats.model_dump()
    )


# Routes à segment libre en dernier : un id peut contenir « / » (%2F décodé).
@router.get("/{person_id:path}", response_model=SuccessResponse)
async def get_person(
    person_id: str, service: GenealogyService = Depends(get_session_service)
) -> SuccessResponse:
    """
    Récupère une personne par son ID.

    Args:
        person_id: Identifiant de la personne
        service: Service de généalogie

    Returns:
        SuccessResponse: Réponse de succès avec les données de la personne
    """
    person = service.get_person(person_id)

    if person is None:
        raise HTTPException(
            status_code=404, detail=f"Personne avec l'ID '{person_id}' non trouvée"
        )

    person_schema = person_to_person_schema(person)

    return SuccessResponse(
        message="Personne récupérée avec succès", data=person_schema.model_dump()
    )


@router.put(
    "/{person_id:path}",
    response_model=SuccessResponse,
    dependencies=[Depends(require_write_mode)],
)
async def update_person(
    person_id: str,
    person_data: PersonUpdateSchema,
    service: GenealogyService = Depends(get_session_service),
) -> SuccessResponse:
    """
    Met à jour une personne.

    Args:
        person_id: Identifiant de la personne
        person_data: Nouvelles données de la personne
        service: Service de généalogie

    Returns:
        SuccessResponse: Réponse de succès avec les données mises à jour
    """
    person = service.update_person(person_id, person_data)

    if person is None:
        raise HTTPException(
            status_code=404, detail=f"Personne avec l'ID '{person_id}' non trouvée"
        )

    person_schema = person_to_person_schema(person)

    return SuccessResponse(
        message="Personne mise à jour avec succès", data=person_schema.model_dump()
    )


@router.delete(
    "/{person_id:path}",
    response_model=SuccessResponse,
    dependencies=[Depends(require_write_mode)],
)
async def delete_person(
    person_id: str, service: GenealogyService = Depends(get_session_service)
) -> SuccessResponse:
    """
    Supprime une personne.

    Args:
        person_id: Identifiant de la personne
        service: Service de généalogie

    Returns:
        SuccessResponse: Réponse de succès
    """
    success = service.delete_person(person_id)

    if not success:
        raise HTTPException(
            status_code=404, detail=f"Personne avec l'ID '{person_id}' non trouvée"
        )

    return SuccessResponse(message="Personne supprimée avec succès")
