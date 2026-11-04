"""
Middleware de gestion d'erreurs pour l'API geneweb-py.

Ce module fournit une gestion centralisée des erreurs avec des réponses
standardisées et un logging approprié.
"""

import logging
import traceback

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ...core.exceptions import GeneWebParseError, GeneWebValidationError
from ..models.responses import ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)


def setup_error_handlers(app: FastAPI) -> None:
    """
    Configure les gestionnaires d'erreurs pour l'application FastAPI.

    Args:
        app: Application FastAPI
    """

    @app.exception_handler(GeneWebParseError)
    async def geneweb_parse_error_handler(
        request: Request, exc: GeneWebParseError
    ) -> JSONResponse:
        """Gestionnaire pour les erreurs de parsing GeneWeb."""
        logger.error("Erreur de parsing GeneWeb: %s", type(exc).__name__)

        # Détails enrichis: inclure le contexte utile (ligne, token, attendu)
        details = [ErrorDetail(message=str(exc), code="PARSE_ERROR")]
        if getattr(exc, "line_number", None) is not None:
            details.append(
                ErrorDetail(field="line_number", message=str(exc.line_number))
            )
        if getattr(exc, "token", None):
            details.append(ErrorDetail(field="token", message=str(exc.token)))
        if getattr(exc, "expected", None):
            details.append(ErrorDetail(field="expected", message=str(exc.expected)))
        if getattr(exc, "context", None):
            details.append(ErrorDetail(field="context", message=str(exc.context)))

        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                error=True,
                message="Erreur de parsing du fichier GeneWeb",
                details=details,
                code="PARSE_ERROR",
            ).model_dump(),
        )

    @app.exception_handler(GeneWebValidationError)
    async def geneweb_validation_error_handler(
        request: Request, exc: GeneWebValidationError
    ) -> JSONResponse:
        """Gestionnaire pour les erreurs de validation GeneWeb."""
        logger.error("Erreur de validation GeneWeb: %s", type(exc).__name__)

        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                error=True,
                message="Erreur de validation des données GeneWeb",
                details=[ErrorDetail(message=str(exc), code="VALIDATION_ERROR")],
                code="VALIDATION_ERROR",
            ).model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Gestionnaire pour les erreurs de validation des requêtes."""
        logger.error("Erreur de validation de requête (%d champ(s))", len(exc.errors()))

        details = []
        for error in exc.errors():
            details.append(
                ErrorDetail(
                    field=".".join(str(x) for x in error["loc"]),
                    message=error["msg"],
                    code=error["type"],
                )
            )

        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                error=True,
                message="Erreur de validation des données de la requête",
                details=details,
                code="REQUEST_VALIDATION_ERROR",
            ).model_dump(),
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        """Gestionnaire pour les erreurs HTTP."""
        logger.error("Erreur HTTP %s", exc.status_code)

        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                error=True, message=exc.detail, code=f"HTTP_{exc.status_code}"
            ).model_dump(),
        )

    @app.exception_handler(StarletteHTTPException)
    async def starlette_http_error_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Gestionnaire pour les erreurs HTTP Starlette."""
        logger.error("Erreur Starlette HTTP %s", exc.status_code)

        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                error=True, message=exc.detail, code=f"STARLETTE_HTTP_{exc.status_code}"
            ).model_dump(),
        )

    @app.exception_handler(Exception)
    async def general_error_handler(request: Request, exc: Exception) -> JSONResponse:
        """Gestionnaire pour toutes les autres erreurs."""
        # Type et pile d'appels seulement : le message peut citer des données du fichier
        logger.error(
            "Erreur inattendue: %s\n%s",
            type(exc).__name__,
            "".join(traceback.format_tb(exc.__traceback__)),
        )

        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error=True,
                message="Une erreur interne du serveur s'est produite",
                details=[
                    ErrorDetail(
                        message="Contactez l'administrateur si le problème persiste",
                        code="INTERNAL_SERVER_ERROR",
                    )
                ],
                code="INTERNAL_SERVER_ERROR",
            ).model_dump(),
        )
