"""
Utilitaires communs aux routers HTTP (messages d'erreur sécurisés).
"""

import logging
import traceback
from typing import NoReturn

from fastapi import HTTPException

logger = logging.getLogger(__name__)


def raise_internal_server_error(log_message: str, exc: Exception) -> NoReturn:
    """
    Journalise le type et la pile d'appels (sans le message) et renvoie une erreur HTTP 500 générique.

    Args:
        log_message: Contexte pour les journaux serveur.
        exc: Exception ayant provoqué l'échec.
    """
    # Pas de exc_info : le message de l'exception peut citer des données du fichier
    logger.error(
        "%s - %s\n%s",
        log_message,
        type(exc).__name__,
        "".join(traceback.format_tb(exc.__traceback__)),
    )
    raise HTTPException(
        status_code=500,
        detail="Une erreur interne s'est produite. Réessayez plus tard.",
    ) from exc
