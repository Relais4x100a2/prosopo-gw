"""Dépendances FastAPI pour l'API geneweb-py."""

from fastapi import Depends, Header, HTTPException, Request, Response, status

import geneweb_py.api.limits as _limits_mod

from .services.genealogy_service import GenealogyService
from .session_store import SessionStore


def get_store(request: Request) -> SessionStore:
    """Retourne le SessionStore stocké dans app.state."""
    return request.app.state.session_store


# Temps restant (secondes) renvoyé à chaque requête de session : le client recale son
# compte à rebours sans dépendre de son horloge.
SESSION_EXPIRES_IN_HEADER = "X-Session-Expires-In"


def get_session_service(
    response: Response,
    x_session_token: str = Header(..., alias="X-Session-Token"),
    store: SessionStore = Depends(get_store),
) -> GenealogyService:
    """Résout le token de session (et prolonge son TTL) ; retourne son GenealogyService.

    Le service est conservé avec la session : ses caches (index des candidates,
    témoins) et ses réglages (mots ignorés) survivent d'une requête à l'autre.
    """
    touched = store.service(x_session_token)
    if touched is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session inconnue ou expirée",
        )
    service, expires_at = touched
    response.headers[SESSION_EXPIRES_IN_HEADER] = str(store.seconds_left(expires_at))
    return service


def require_write_mode() -> None:
    """Lève 405 si l'API est en mode lecture seule (READ_ONLY=true)."""
    if _limits_mod.READ_ONLY:
        raise HTTPException(
            status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
            detail="API en mode lecture seule",
        )


def get_pagination_params(
    page: int = 1, size: int = 20, max_size: int = 100
) -> tuple[int, int]:
    """Valide et retourne les paramètres de pagination."""
    if page < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le numéro de page doit être supérieur à 0",
        )
    if size < 1 or size > max_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"La taille de la page doit être entre 1 et {max_size}",
        )
    return page, size


def get_search_limit(limit: int = 50, max_limit: int = 100) -> int:
    """Valide et retourne la limite de recherche."""
    if limit < 1 or limit > max_limit:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"La limite doit être entre 1 et {max_limit}",
        )
    return limit
