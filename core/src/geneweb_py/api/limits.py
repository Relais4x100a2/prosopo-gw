"""
Limites et seuils de sécurité pour l'API HTTP.

Les valeurs peuvent être surchargées via les variables d'environnement
pour l'adaptation au déploiement.
"""

import os

# Origines autorisées en développement / test local (frontends sur le port 3000).
DEFAULT_DEV_CORS_ORIGINS: list[str] = [
    "http://127.0.0.1:3000",
    "http://localhost:3000",
]


def _parse_int_env(name: str, default: int) -> int:
    """Lit une variable d'environnement entière avec repli sur défaut."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _split_csv_origins(raw: str) -> list[str]:
    """Découpe une chaîne d'origines séparées par des virgules."""
    return [item.strip() for item in raw.split(",") if item.strip()]


def _get_api_env() -> str:
    """Retourne le mode d'exécution API (dev, test, prod)."""
    raw = os.getenv("GENEWEB_API_ENV", "dev")
    return raw.strip().lower() or "dev"


def get_cors_allow_origins() -> list[str]:
    """
    Retourne la liste des origines CORS autorisées selon l'environnement.

    Priorité des variables d'environnement :
        1. ``ALLOWED_ORIGINS`` (liste séparée par des virgules) ;
        2. ``CORS_ORIGINS`` (rétrocompatibilité) ;
        3. Si aucune n'est définie et que ``GENEWEB_API_ENV=prod`` : liste vide
           (aucune origine cross-origin tant que l'opérateur ne configure pas
           ``ALLOWED_ORIGINS``) ;
        4. Sinon : ``DEFAULT_DEV_CORS_ORIGINS``.

    En production, une origine ``*`` est ignorée (incompatible avec
    ``allow_credentials=True`` et interdit par les critères de sécurité).

    Returns:
        Liste d'URL d'origine sans slash final parasite.
    """
    api_env = _get_api_env()
    origins: list[str]

    if "ALLOWED_ORIGINS" in os.environ:
        raw = os.environ["ALLOWED_ORIGINS"]
        if raw.strip() == "":
            origins = []
        else:
            origins = _split_csv_origins(raw)
    elif "CORS_ORIGINS" in os.environ:
        raw = os.environ["CORS_ORIGINS"]
        if raw.strip() == "":
            origins = []
        else:
            origins = _split_csv_origins(raw)
    elif api_env == "prod":
        origins = []
    else:
        origins = list(DEFAULT_DEV_CORS_ORIGINS)

    if api_env == "prod":
        origins = [o for o in origins if o != "*"]

    return origins


MAX_UPLOAD_BYTES: int = _parse_int_env("GENEWEB_MAX_UPLOAD_BYTES", 50 * 1024 * 1024)

SESSION_MAX_SESSIONS: int = _parse_int_env("SESSION_MAX_SESSIONS", 10)
SESSION_TTL_SECONDS: int = _parse_int_env("SESSION_TTL_SECONDS", 3600)
READ_ONLY: bool = os.getenv("READ_ONLY", "false").strip().lower() == "true"
