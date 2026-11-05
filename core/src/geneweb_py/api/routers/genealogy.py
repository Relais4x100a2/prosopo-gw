"""
Router FastAPI pour la gestion de la généalogie dans l'API geneweb-py.
"""

import os
import tempfile
from typing import Any, Dict, List

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
)
from fastapi.responses import FileResponse, JSONResponse, Response

from ...formats import GEDCOMExporter, JSONExporter, XMLExporter
from ..dependencies import get_session_service
from ..models.responses import StatsResponse, SuccessResponse
from ..rate_limit import limiter
from ..router_helpers import raise_internal_server_error
from ..services.genealogy_service import GenealogyService
from ..services.organization_exports import (
    candidates_csv,
    candidates_sidecar,
    links_csv,
)

router = APIRouter()

_READ_CHUNK_SIZE = 1024 * 1024


def _unlink_temp(path: str) -> None:
    """Supprime un fichier temporaire en ignorant les erreurs."""
    try:
        os.unlink(path)
    except OSError:
        pass


def _export_with_cleanup(
    genealogy: Any,
    exporter_class: type,
    suffix: str,
    download_filename: str,
    media_type: str,
    background_tasks: BackgroundTasks,
) -> FileResponse:
    """Écrit l'export dans un fichier temporaire et planifie sa suppression."""
    temp_fd, temp_path = tempfile.mkstemp(suffix=suffix)
    os.close(temp_fd)
    try:
        exporter = exporter_class()
        exporter.export(genealogy, temp_path)
    except Exception:
        _unlink_temp(temp_path)
        raise

    background_tasks.add_task(_unlink_temp, temp_path)
    return FileResponse(
        path=temp_path,
        filename=download_filename,
        media_type=media_type,
    )


def _download_headers(filename: str) -> Dict[str, str]:
    return {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
    }


@router.get("/export/org-json")
@limiter.limit("40/minute")
async def export_org_json(
    request: Request,
    service: GenealogyService = Depends(get_session_service),
) -> JSONResponse:
    """Fichier compagnon ``.org.json`` limité aux organisations candidates."""
    payload = candidates_sidecar(service.genealogy, service.get_candidate_index())
    return JSONResponse(payload, headers=_download_headers("genealogie.org.json"))


@router.get("/export/organizations-csv")
@limiter.limit("40/minute")
async def export_organizations_csv(
    request: Request,
    service: GenealogyService = Depends(get_session_service),
) -> Response:
    """CSV des organisations candidates (une ligne par candidat)."""
    return Response(
        candidates_csv(service.get_candidate_index()).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers=_download_headers("organisations.csv"),
    )


@router.get("/export/organization-links-csv")
@limiter.limit("40/minute")
async def export_organization_links_csv(
    request: Request,
    service: GenealogyService = Depends(get_session_service),
) -> Response:
    """CSV des liens personne - organisation des candidats."""
    return Response(
        links_csv(service.get_candidate_index()).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers=_download_headers("liens_organisations.csv"),
    )


@router.get("/export/{format}", response_class=FileResponse)
@limiter.limit("40/minute")
async def export_genealogy(
    request: Request,
    format: str,
    background_tasks: BackgroundTasks,
    service: GenealogyService = Depends(get_session_service),
) -> FileResponse:
    """
    Exporte la généalogie dans différents formats.

    Args:
        request: Requête HTTP (limitation de débit).
        format: Format d'export (gw, json, xml, gedcom)
        background_tasks: Tâches après envoi de la réponse (nettoyage disque)
        service: Service de généalogie

    Returns:
        FileResponse: Fichier exporté
    """
    try:
        genealogy = service.genealogy

        if format == "gw":
            raise HTTPException(
                status_code=501,
                detail="Export vers format GeneWeb non encore implémenté",
            )
        if format == "json":
            try:
                return _export_with_cleanup(
                    genealogy,
                    JSONExporter,
                    ".json",
                    "genealogy.json",
                    "application/json",
                    background_tasks,
                )
            except Exception as exc:
                raise_internal_server_error(
                    "Erreur lors de l'export JSON de la généalogie", exc
                )
        if format == "xml":
            try:
                return _export_with_cleanup(
                    genealogy,
                    XMLExporter,
                    ".xml",
                    "genealogy.xml",
                    "application/xml",
                    background_tasks,
                )
            except Exception as exc:
                raise_internal_server_error(
                    "Erreur lors de l'export XML de la généalogie", exc
                )
        if format == "gedcom":
            try:
                return _export_with_cleanup(
                    genealogy,
                    GEDCOMExporter,
                    ".ged",
                    "genealogy.ged",
                    "application/octet-stream",
                    background_tasks,
                )
            except Exception as exc:
                raise_internal_server_error(
                    "Erreur lors de l'export GEDCOM de la généalogie", exc
                )

        raise HTTPException(
            status_code=400,
            detail=(
                f"Format d'export '{format}' non supporté. "
                "Formats disponibles: gw, json, xml, gedcom"
            ),
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error("Erreur lors de l'export de la généalogie", exc)


@router.get("/stats", response_model=SuccessResponse)
async def get_genealogy_stats(
    service: GenealogyService = Depends(get_session_service),
) -> SuccessResponse:
    """
    Récupère les statistiques générales de la généalogie.

    Args:
        service: Service de généalogie

    Returns:
        SuccessResponse: Réponse avec les statistiques complètes
    """
    try:
        stats = service.get_stats()

        stats_response = StatsResponse(
            total_persons=stats["total_persons"],
            total_families=stats["total_families"],
            total_events=stats["total_events"],
            persons_by_sex=stats.get("persons_by_sex", {}),
            persons_by_access_level=stats.get("persons_by_access_level", {}),
            persons_by_birth_century=stats.get("persons_by_birth_century", {}),
            families_by_status=stats.get("families_by_status", {}),
            families_by_marriage_century=stats.get("families_by_marriage_century", {}),
            events_by_type=stats.get("events_by_type", {}),
            events_by_century=stats.get("events_by_century", {}),
            average_children_per_family=stats.get("average_children_per_family", 0.0),
            metadata={
                "source_file": stats["metadata"]["source_file"],
                "created": stats["metadata"]["created"],
                "updated": stats["metadata"]["updated"],
                "version": stats["metadata"]["version"],
                "encoding": stats["metadata"]["encoding"],
            },
            persons_with_birth_date=stats.get("persons_with_birth_date", 0),
            persons_with_death_date=stats.get("persons_with_death_date", 0),
            families_with_children=stats.get("families_with_children", 0),
            personal_events=stats.get("personal_events", 0),
            family_events=stats.get("family_events", 0),
            families_with_marriage_date=stats.get("families_with_marriage_date", 0),
            families_with_divorce_date=stats.get("families_with_divorce_date", 0),
            advanced=stats.get("advanced"),
        )

        return SuccessResponse(
            message="Statistiques récupérées avec succès",
            data=stats_response.model_dump(),
        )

    except Exception as exc:
        raise_internal_server_error(
            "Erreur lors de la récupération des statistiques de la généalogie", exc
        )


@router.get("/search", response_model=SuccessResponse)
@limiter.limit("60/minute")
async def search_genealogy(
    request: Request,
    query: str = Query(..., min_length=1, description="Terme de recherche"),
    search_type: str = Query(
        "all", description="Type de recherche: all, persons, families, events"
    ),
    limit: int = Query(50, ge=1, le=100, description="Nombre maximum de résultats"),
    service: GenealogyService = Depends(get_session_service),
) -> SuccessResponse:
    """
    Effectue une recherche globale dans la généalogie.

    Args:
        request: Requête HTTP (limitation de débit).
        query: Terme de recherche
        search_type: Type de recherche (all, persons, families, events)
        limit: Nombre maximum de résultats
        service: Service de généalogie

    Returns:
        SuccessResponse: Réponse avec les résultats de recherche
    """
    try:
        genealogy = service.genealogy
        query_lower = query.lower()
        results: Dict[str, List[Any]] = {"persons": [], "families": [], "events": []}

        if search_type in ["all", "persons"]:
            for person in genealogy.persons.values():
                if (
                    query_lower in person.first_name.lower()
                    or query_lower in person.last_name.lower()
                    or (
                        person.public_name and query_lower in person.public_name.lower()
                    )
                    or (
                        person.birth_place and query_lower in person.birth_place.lower()
                    )
                    or (
                        person.death_place and query_lower in person.death_place.lower()
                    )
                ):
                    person_data = {
                        "id": person.unique_id,
                        "first_name": person.first_name,
                        "surname": person.last_name,
                        "public_name": person.public_name,
                        "sex": person.gender.value if person.gender else None,
                        "birth_place": person.birth_place,
                        "death_place": person.death_place,
                    }
                    results["persons"].append(person_data)

        if search_type in ["all", "families"]:
            for family in genealogy.families.values():
                husband = (
                    genealogy.persons.get(family.husband_id)
                    if family.husband_id
                    else None
                )
                wife = genealogy.persons.get(family.wife_id) if family.wife_id else None

                family_matches = False
                if husband and (
                    query_lower in husband.first_name.lower()
                    or query_lower in husband.last_name.lower()
                ):
                    family_matches = True
                if wife and (
                    query_lower in wife.first_name.lower()
                    or query_lower in wife.last_name.lower()
                ):
                    family_matches = True

                if family_matches:
                    family_data = {
                        "id": family.id,
                        "husband_id": family.husband_id,
                        "wife_id": family.wife_id,
                        "marriage_status": (
                            family.marriage_status.value
                            if family.marriage_status
                            else None
                        ),
                        "children_count": len(family.children),
                    }
                    results["families"].append(family_data)

        if search_type in ["all", "events"]:

            def _event_notes_match(notes: List[str], q: str) -> bool:
                return any(q in (n or "").lower() for n in notes)

            for person in genealogy.persons.values():
                for event in person.events:
                    if (
                        query_lower in (event.place or "").lower()
                        or query_lower in (event.reason or "").lower()
                        or _event_notes_match(event.notes, query_lower)
                    ):
                        event_data = {
                            "id": getattr(event, "unique_id", "unknown"),
                            "event_type": (
                                event.event_type.value if event.event_type else None
                            ),
                            "place": event.place,
                            "reason": event.reason,
                            "person_id": person.unique_id,
                            "family_id": None,
                        }
                        results["events"].append(event_data)

            for family in genealogy.families.values():
                for family_event in family.events:
                    if (
                        query_lower in (family_event.place or "").lower()
                        or query_lower in (family_event.reason or "").lower()
                        or _event_notes_match(family_event.notes, query_lower)
                    ):
                        event_data = {
                            "id": getattr(family_event, "unique_id", "unknown"),
                            "event_type": (
                                family_event.event_type.value
                                if family_event.event_type
                                else None
                            ),
                            "place": family_event.place,
                            "reason": family_event.reason,
                            "person_id": None,
                            "family_id": family.id,
                        }
                        results["events"].append(event_data)

        total_results = (
            len(results["persons"]) + len(results["families"]) + len(results["events"])
        )
        if limit < total_results:
            results["persons"] = results["persons"][:limit]
            remaining = limit - len(results["persons"])
            if remaining > 0:
                results["families"] = results["families"][:remaining]
                remaining = remaining - len(results["families"])
                if remaining > 0:
                    results["events"] = results["events"][:remaining]

        search_results = {
            "query": query,
            "search_type": search_type,
            "limit": limit,
            "results": results,
            "total_results": total_results,
        }

        return SuccessResponse(
            message=f"Recherche '{query}' effectuée avec succès", data=search_results
        )

    except Exception as exc:
        raise_internal_server_error(
            "Erreur lors de la recherche dans la généalogie", exc
        )


@router.post("/validate", response_model=SuccessResponse)
async def validate_genealogy(
    strict: bool = Query(
        False,
        description=(
            "Si True, met à jour l'état de validation sur l'objet Genealogy "
            "en mémoire : ``validation_errors`` est remplacé par les erreurs "
            "de cette passe (pas de cumul avec les appels précédents)."
        ),
    ),
    service: GenealogyService = Depends(get_session_service),
) -> SuccessResponse:
    """
    Valide la cohérence de la généalogie.

    Args:
        strict: Propagé au validateur côté service.
        service: Service de généalogie

    Returns:
        SuccessResponse: Réponse avec les résultats de validation
    """
    try:
        validation_results = service.validate_genealogy(strict=strict)

        if validation_results.get("is_valid"):
            msg = "Validation terminée : aucune erreur détectée."
        else:
            msg = (
                "Validation terminée : la généalogie présente des erreurs "
                "(voir le champ data)."
            )

        return SuccessResponse(message=msg, data=validation_results)

    except Exception as exc:
        raise_internal_server_error(
            "Erreur lors de la validation de la généalogie", exc
        )


@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """
    Vérification de l'état de santé du service de généalogie.

    Returns:
        Dict[str, Any]: Statut du service
    """
    return {
        "status": "healthy",
        "service": "genealogy",
        "message": "Service de généalogie opérationnel",
        "version": "0.1.0",
    }
