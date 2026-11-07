"""
Middleware de logging pour l'API geneweb-py.

Ce module journalise les requêtes et réponses pour le monitoring, sans jamais
écrire de donnée issue du fichier téléversé (privacy by design) : ni l'URL réelle
(les identifiants de personnes contiennent noms et prénoms), ni la chaîne de
requête, ni le message des exceptions, ni l'adresse IP du client. Seuls la méthode,
le gabarit de la route (ex. ``/api/v1/persons/{person_id}``), le statut et la durée
sont écrits.
"""

import logging
import time
from collections.abc import Callable

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

UNROUTED = "<non-routé>"


def route_template(request: Request) -> str:
    """Gabarit de la route appelée, jamais l'URL réelle.

    Renvoie ``UNROUTED`` quand aucune route ne correspond (404, fichier statique).
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) and path else UNROUTED


class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware de logging des requêtes HTTP."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Traite la requête avec logging.

        Args:
            request: Requête HTTP
            call_next: Fonction suivante dans la chaîne

        Returns:
            Response: Réponse HTTP
        """
        start_time = time.time()

        # Ni l'URL réelle, ni la chaîne de requête, ni X-Session-Token, ni l'adresse
        # IP, ni le User-Agent ne sont journalisés (privacy by design).
        try:
            response = await call_next(request)
        except Exception as exc:
            # Seul le type de l'exception est écrit : son message peut citer des
            # données du fichier téléversé.
            logger.error(
                "Erreur lors du traitement: %s %s après %.3fs - %s",
                request.method,
                route_template(request),
                time.time() - start_time,
                type(exc).__name__,
            )
            # Re-lance l'exception pour qu'elle soit traitée par les gestionnaires d'erreurs  # noqa: E501
            raise

        process_time = time.time() - start_time
        logger.info(
            "Réponse: %s %s -> %s en %.3fs",
            request.method,
            route_template(request),
            response.status_code,
            process_time,
        )
        response.headers["X-Process-Time"] = str(process_time)
        return response


def setup_logging_middleware(app: FastAPI) -> None:
    """
    Configure le middleware de logging pour l'application FastAPI.

    Args:
        app: Application FastAPI
    """
    # Ajout du middleware de logging
    app.add_middleware(LoggingMiddleware)

    # Configuration du logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Configuration spécifique pour uvicorn
    # Le journal d'accès d'uvicorn écrit l'URL réelle et la requête : désactivé
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    logger.info("Middleware de logging configuré pour l'API GeneWeb-py")
