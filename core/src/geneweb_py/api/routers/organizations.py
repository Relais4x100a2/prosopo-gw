"""Router FastAPI des organisations candidates.

Lecture seule sur la base : seul le réglage des mots ignorés (propre à la
session, sans effet sur le fichier) s'écrit.
"""

import dataclasses
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..dependencies import get_session_service
from ..models.organization import (
    IgnoredWordsSchema,
    OrganizationCandidateDetailSchema,
    OrganizationCandidateSchema,
    SharedExperiencesResponseSchema,
    UnmatchedResponseSchema,
)
from ..models.responses import PaginatedResponse, PaginationInfo
from ..services.genealogy_service import GenealogyService
from ..services.organization_candidates import (
    filter_candidates,
    shared_experience_persons,
    sort_candidates,
)

router = APIRouter()

SHARED_EXPERIENCES_CAP = 500


@router.get("/candidates", response_model=PaginatedResponse)
async def list_candidates(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    sort: Literal["persons", "period", "name"] = Query("persons"),
    type: Optional[str] = Query(None),
    named_from: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    service: GenealogyService = Depends(get_session_service),
) -> PaginatedResponse:
    """Candidats triés et filtrés, paginés."""
    index = service.get_candidate_index()
    found = sort_candidates(
        filter_candidates(
            index.candidates.values(), type_=type, named_from=named_from, q=q
        ),
        sort,
    )
    total = len(found)
    pages = (total + size - 1) // size
    start = (page - 1) * size
    items = [
        OrganizationCandidateSchema.model_validate(
            {k: v for k, v in dataclasses.asdict(c).items() if k != "members"}
        )
        for c in found[start : start + size]
    ]
    return PaginatedResponse(
        items=items,
        pagination=PaginationInfo(
            page=page,
            size=size,
            total=total,
            pages=pages,
            has_next=page < pages,
            has_prev=page > 1,
        ),
    )


@router.get("/candidates/{organization_id}")
async def get_candidate(
    organization_id: str,
    service: GenealogyService = Depends(get_session_service),
) -> OrganizationCandidateDetailSchema:
    """Détail d'un candidat avec ses membres."""
    candidate = service.get_candidate_index().candidates.get(organization_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Organisation inconnue")
    return OrganizationCandidateDetailSchema.model_validate(
        dataclasses.asdict(candidate)
    )


@router.get("/unmatched")
async def get_unmatched(
    service: GenealogyService = Depends(get_session_service),
) -> UnmatchedResponseSchema:
    """Événements « Autre » sans candidat, groupés par mot."""
    index = service.get_candidate_index()
    return UnmatchedResponseSchema.model_validate(
        {
            "total": index.unmatched_total,
            "groups": [dataclasses.asdict(g) for g in index.unmatched_groups],
            "ignored_total": index.ignored_total,
            "civil_status_total": index.civil_status_total,
        }
    )


@router.get("/shared-experiences")
async def get_shared_experiences(
    service: GenealogyService = Depends(get_session_service),
) -> SharedExperiencesResponseSchema:
    """Expériences proches (déportation, voyage…), plafonnées à 500 entrées."""
    index = service.get_shared_experiences()
    items = index.items[:SHARED_EXPERIENCES_CAP]
    return SharedExperiencesResponseSchema.model_validate(
        {
            "items": [
                {
                    "id": e.id,
                    "theme": e.theme,
                    "label": e.label,
                    "year_min": e.year_min,
                    "year_max": e.year_max,
                    "places": e.places,
                    "reasons": [dataclasses.asdict(r) for r in e.reasons],
                    "person_count": e.person_count,
                    "event_count": e.event_count,
                    "persons": shared_experience_persons(service.genealogy, e),
                }
                for e in items
            ],
            "total": len(index.items),
            "civil_status_total": service.get_candidate_index().civil_status_total,
            "undated_total": index.undated_total,
            "truncated": len(index.items) > SHARED_EXPERIENCES_CAP,
        }
    )


@router.get("/ignored-words")
async def get_ignored_words(
    service: GenealogyService = Depends(get_session_service),
) -> IgnoredWordsSchema:
    """Mots qui écartent un événement « Autre » (vide par défaut ; l'état civil est toujours écarté)."""
    return IgnoredWordsSchema(words=list(service.ignored_words))


@router.put("/ignored-words")
async def put_ignored_words(
    body: IgnoredWordsSchema,
    service: GenealogyService = Depends(get_session_service),
) -> IgnoredWordsSchema:
    """Remplace les mots ignorés de la session ; candidats et exports suivent."""
    return IgnoredWordsSchema(words=list(service.set_ignored_words(body.words)))
