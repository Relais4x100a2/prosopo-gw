"""Tests unitaires pour SessionStore."""

from datetime import UTC, datetime, timedelta

import pytest

from geneweb_py.api.session_store import SessionFullError, SessionStore
from geneweb_py.core.genealogy import Genealogy


def _make_genealogy() -> Genealogy:
    return Genealogy()


class TestSessionStoreCreate:
    def test_create_returns_token_and_expiry(self):
        store = SessionStore(max_sessions=5, ttl_seconds=3600)
        g = _make_genealogy()
        token, expires_at = store.create(g)
        assert len(token) > 20
        assert isinstance(expires_at, datetime)
        assert expires_at > datetime.now(UTC)

    def test_create_stores_genealogy(self):
        store = SessionStore(max_sessions=5, ttl_seconds=3600)
        g = _make_genealogy()
        token, _ = store.create(g)
        assert store.get(token) is g

    def test_create_raises_when_full(self):
        store = SessionStore(max_sessions=2, ttl_seconds=3600)
        store.create(_make_genealogy())
        store.create(_make_genealogy())
        with pytest.raises(SessionFullError):
            store.create(_make_genealogy())

    def test_tokens_are_unique(self):
        store = SessionStore(max_sessions=10, ttl_seconds=3600)
        tokens = {store.create(_make_genealogy())[0] for _ in range(5)}
        assert len(tokens) == 5


class TestSessionStoreGet:
    def test_get_unknown_returns_none(self):
        store = SessionStore()
        assert store.get("nonexistent") is None

    def test_get_extends_ttl(self):
        store = SessionStore(max_sessions=5, ttl_seconds=3600)
        g = _make_genealogy()
        token, _ = store.create(g)
        before = store._store[token].expires_at
        store.get(token)
        after = store._store[token].expires_at
        assert after >= before

    def test_get_expired_returns_none(self):
        store = SessionStore(max_sessions=5, ttl_seconds=3600)
        token, _ = store.create(_make_genealogy())
        store._store[token].expires_at = datetime.now(UTC) - timedelta(seconds=1)
        assert store.get(token) is None

    def test_get_removes_expired_entry(self):
        store = SessionStore(max_sessions=5, ttl_seconds=3600)
        token, _ = store.create(_make_genealogy())
        store._store[token].expires_at = datetime.now(UTC) - timedelta(seconds=1)
        store.get(token)
        assert token not in store._store


class TestSessionStoreDelete:
    def test_delete_existing(self):
        store = SessionStore()
        token, _ = store.create(_make_genealogy())
        assert store.delete(token) is True
        assert store.get(token) is None

    def test_delete_unknown(self):
        store = SessionStore()
        assert store.delete("nonexistent") is False


class TestSessionStoreCleanup:
    def test_cleanup_removes_expired(self):
        store = SessionStore(max_sessions=5, ttl_seconds=3600)
        token, _ = store.create(_make_genealogy())
        store._store[token].expires_at = datetime.now(UTC) - timedelta(seconds=1)
        count = store.cleanup_expired()
        assert count == 1
        assert token not in store._store

    def test_cleanup_preserves_active(self):
        store = SessionStore(max_sessions=5, ttl_seconds=3600)
        token, _ = store.create(_make_genealogy())
        count = store.cleanup_expired()
        assert count == 0
        assert store.get(token) is not None


class TestSessionStoreCountAndFull:
    def test_count_active(self):
        store = SessionStore(max_sessions=5, ttl_seconds=3600)
        assert store.count_active() == 0
        store.create(_make_genealogy())
        assert store.count_active() == 1

    def test_is_full(self):
        store = SessionStore(max_sessions=2, ttl_seconds=3600)
        assert not store.is_full()
        store.create(_make_genealogy())
        store.create(_make_genealogy())
        assert store.is_full()

    def test_expired_not_counted(self):
        store = SessionStore(max_sessions=5, ttl_seconds=3600)
        token, _ = store.create(_make_genealogy())
        store._store[token].expires_at = datetime.now(UTC) - timedelta(seconds=1)
        assert store.count_active() == 0
