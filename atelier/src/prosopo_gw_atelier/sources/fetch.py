"""Safe HTTP helpers for sources: streamed download and JSON fetch."""

from __future__ import annotations

import http.client
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from importlib import metadata
from pathlib import Path
from typing import IO, BinaryIO

from prosopo_gw_atelier.sources.base import PermanentSourceError, SourceError

Opener = Callable[[urllib.request.Request, float], BinaryIO]

REPOSITORY_URL = "https://github.com/Relais4x100a2/prosopo-gw"
_CHUNK = 64 * 1024
JSON_MAX_BYTES = 5 * 1024 * 1024


def _version() -> str:
    try:
        return metadata.version("prosopo-gw-atelier")
    except metadata.PackageNotFoundError:
        return "0+unknown"


USER_AGENT = f"prosopo-gw-atelier/{_version()} (+{REPOSITORY_URL})"


class _HttpOnlyRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects to http and https only (not ftp, file…)."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        if urllib.parse.urlparse(newurl).scheme.lower() not in ("http", "https"):
            raise urllib.error.HTTPError(
                req.full_url,
                code,
                "redirection vers un schéma non pris en charge",
                headers,
                fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _director() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_HttpOnlyRedirect)


def default_opener(request: urllib.request.Request, timeout: float) -> BinaryIO:
    # Looked up at call time so tests can patch OpenerDirector.open.
    return _director().open(request, timeout=timeout)  # type: ignore[no-any-return]


def _describe(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 429:
            return "le service limite le nombre de requêtes, réessayez plus tard"
        if exc.code >= 500:
            return f"service indisponible (HTTP {exc.code})"
        return f"réponse inattendue du service (HTTP {exc.code})"
    if isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError)):
        return "erreur réseau ou délai dépassé"
    if isinstance(exc, http.client.HTTPException):
        return "erreur réseau ou réponse incomplète"
    if isinstance(exc, OSError):
        return f"erreur d'entrée/sortie ({exc})"
    return "erreur inattendue"


def _is_permanent(exc: BaseException) -> bool:
    """HTTP 4xx other than 408 and 429: asking again will not help."""
    return (
        isinstance(exc, urllib.error.HTTPError)
        and 400 <= exc.code < 500
        and exc.code not in (408, 429)
    )


def _check_scheme(url: str, prefix: str) -> None:
    if urllib.parse.urlparse(url).scheme.lower() not in ("http", "https"):
        raise SourceError(
            f"{prefix} : schéma d'URL non pris en charge (http ou https attendu)"
        )


def _declared_too_large(response: object, max_bytes: int | None) -> bool:
    if max_bytes is None:
        return False
    headers = getattr(response, "headers", None)
    value = headers.get("Content-Length") if headers is not None else None
    try:
        return value is not None and int(value) > max_bytes
    except ValueError:
        return False


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT})


def download(
    url: str,
    target: Path,
    *,
    opener: Opener | None = None,
    timeout: float = 60.0,
    max_bytes: int | None = None,
) -> int:
    """Stream ``url`` to ``target`` through a ``.part`` file; return the size."""
    _check_scheme(url, "Téléchargement impossible")
    open_url = opener or default_opener
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    try:
        total = 0
        with open_url(_request(url), timeout) as response, part.open("wb") as out:
            if _declared_too_large(response, max_bytes):
                raise SourceError(
                    f"fichier trop volumineux (plus de {max_bytes} octets)"
                )
            while chunk := response.read(_CHUNK):
                total += len(chunk)
                if max_bytes is not None and total > max_bytes:
                    raise SourceError(
                        f"fichier trop volumineux (plus de {max_bytes} octets)"
                    )
                out.write(chunk)
        os.replace(part, target)
        return total
    except Exception as exc:
        part.unlink(missing_ok=True)
        permanent = isinstance(exc, PermanentSourceError) or _is_permanent(exc)
        if isinstance(exc, urllib.error.HTTPError):
            exc.close()
        message = str(exc) if isinstance(exc, SourceError) else _describe(exc)
        error = PermanentSourceError if permanent else SourceError
        raise error(f"Téléchargement impossible : {message}") from exc


def get_json(
    url: str, *, opener: Opener | None = None, timeout: float = 30.0
) -> object:
    """Fetch ``url`` and decode it as JSON."""
    _check_scheme(url, "Requête impossible")
    open_url = opener or default_opener
    try:
        with open_url(_request(url), timeout) as response:
            data = response.read(JSON_MAX_BYTES + 1)
            if len(data) > JSON_MAX_BYTES:
                raise SourceError("réponse trop volumineuse")
            return json.loads(data)
    except Exception as exc:
        if isinstance(exc, urllib.error.HTTPError):
            exc.close()
        if isinstance(exc, SourceError):
            raise SourceError(f"Requête impossible : {exc}") from exc
        if isinstance(exc, ValueError):
            message = "réponse non valide (JSON attendu)"
        else:
            message = _describe(exc)
        raise SourceError(f"Requête impossible : {message}") from exc
