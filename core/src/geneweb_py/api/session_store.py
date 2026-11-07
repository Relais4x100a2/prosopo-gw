"""Store de sessions éphémères en mémoire — privacy by design."""

import secrets
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Optional

from ..core.genealogy import Genealogy
from .limits import SESSION_MAX_SESSIONS, SESSION_TTL_SECONDS

if TYPE_CHECKING:
    from .services.genealogy_service import GenealogyService


class SessionFullError(Exception):
    """Levée quand le cap de sessions simultanées est atteint."""


@dataclass
class SessionEntry:
    genealogy: Genealogy
    expires_at: datetime
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    # Service de la session, créé à la première requête et conservé ensuite :
    # ses caches et réglages (candidates, mots ignorés…) valent pour toute la session.
    service: Optional["GenealogyService"] = None
    # Nom du fichier chargé (assaini), pour nommer l'archive d'export ; il n'est
    # pas recopié dans ``genealogy.metadata.source_file``, qui reste vide.
    source_name: str | None = None


class SessionStore:
    """Store en mémoire de sessions éphémères avec TTL glissant."""

    def __init__(
        self,
        max_sessions: int = SESSION_MAX_SESSIONS,
        ttl_seconds: int = SESSION_TTL_SECONDS,
    ) -> None:
        self._max = max_sessions
        self._ttl = ttl_seconds
        self._store: dict[str, SessionEntry] = {}
        self._lock = threading.Lock()

    def _now(self) -> datetime:
        return datetime.now(UTC)

    def _new_expiry(self) -> datetime:
        return self._now() + timedelta(seconds=self._ttl)

    def create(
        self, genealogy: Genealogy, source_name: str | None = None
    ) -> tuple[str, datetime]:
        """Crée une session, lève SessionFullError si le cap est atteint."""
        with self._lock:
            active = sum(1 for e in self._store.values() if e.expires_at > self._now())
            if active >= self._max:
                raise SessionFullError("Session cap reached")
            token = secrets.token_urlsafe(32)
            expires_at = self._new_expiry()
            entry = SessionEntry(
                genealogy=genealogy, expires_at=expires_at, source_name=source_name
            )
            self._store[token] = entry
            return token, expires_at

    def touch(self, token: str) -> tuple[Genealogy, datetime] | None:
        """Prolonge le TTL d'une session active ; retourne (Genealogy, nouvelle échéance)."""
        with self._lock:
            entry = self._store.get(token)
            if entry is None:
                return None
            if entry.expires_at <= self._now():
                self._store.pop(token, None)
                return None
            entry.expires_at = self._new_expiry()
            return entry.genealogy, entry.expires_at

    def service(self, token: str) -> tuple["GenealogyService", datetime] | None:
        """Comme `touch`, mais retourne le service de la session (créé une seule fois)."""
        from .services.genealogy_service import GenealogyService

        with self._lock:
            entry = self._store.get(token)
            if entry is None:
                return None
            if entry.expires_at <= self._now():
                self._store.pop(token, None)
                return None
            entry.expires_at = self._new_expiry()
            if entry.service is None:
                entry.service = GenealogyService(
                    genealogy=entry.genealogy, source_name=entry.source_name
                )
            return entry.service, entry.expires_at

    def get(self, token: str) -> Genealogy | None:
        """Retourne la Genealogy si active, None sinon. Prolonge le TTL."""
        touched = self.touch(token)
        return touched[0] if touched else None

    def seconds_left(self, expires_at: datetime) -> int:
        """Secondes restantes avant ``expires_at`` (indépendant de l'horloge du client)."""
        return max(0, int((expires_at - self._now()).total_seconds()))

    def delete(self, token: str) -> bool:
        """Supprime une session. Retourne True si trouvée, False sinon."""
        with self._lock:
            if token in self._store:
                del self._store[token]
                return True
        return False

    def cleanup_expired(self) -> int:
        """Supprime les sessions expirées. Retourne le nombre supprimé."""
        now = self._now()
        with self._lock:
            expired = [k for k, e in self._store.items() if e.expires_at <= now]
            for k in expired:
                del self._store[k]
        return len(expired)

    def count_active(self) -> int:
        """Nombre de sessions non expirées."""
        now = self._now()
        with self._lock:
            return sum(1 for e in self._store.values() if e.expires_at > now)

    def is_full(self) -> bool:
        """Vrai si le cap de sessions est atteint."""
        return self.count_active() >= self._max
