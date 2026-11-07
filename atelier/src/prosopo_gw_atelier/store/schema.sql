-- Personal place registry (design § 6.3), schema version 1.
-- Applied by PlaceRegistry on a database whose user_version is 0.

CREATE TABLE IF NOT EXISTS places (
    place_id   TEXT PRIMARY KEY,          -- UUID4, stable
    created_at TEXT NOT NULL              -- UTC ISO 8601
);

-- One row per decomposed element of a place, with its origin.
CREATE TABLE IF NOT EXISTS place_fields (
    place_id TEXT NOT NULL REFERENCES places (place_id),
    kind     TEXT NOT NULL CHECK (kind IN ('commune', 'postal_code', 'insee_code',
                 'department', 'region', 'country', 'former_name')),
    value    TEXT NOT NULL,
    origin   TEXT NOT NULL CHECK (origin IN ('rule', 'manual', 'reference', 'llm')),
    PRIMARY KEY (place_id, kind)
);

-- One row per decided writing (exact text, complement removed).
CREATE TABLE IF NOT EXISTS writings (
    writing    TEXT PRIMARY KEY,
    place_id   TEXT REFERENCES places (place_id),
    status     TEXT NOT NULL CHECK (status IN ('validated', 'rejected')),
    project    TEXT,                       -- project of the latest decision
    decided_at TEXT NOT NULL,
    CHECK ((status = 'validated') = (place_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS writings_place ON writings (place_id);

-- Append-only: rows are never deleted, only flagged undone.
CREATE TABLE IF NOT EXISTS journal (
    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    at       TEXT NOT NULL,
    project  TEXT,
    action   TEXT NOT NULL CHECK (action IN ('validate', 'reject', 'correct',
                 'detach', 'undo', 'import')),
    payload  TEXT NOT NULL,                -- JSON, see registry.py
    undone   INTEGER NOT NULL DEFAULT 0 CHECK (undone IN (0, 1))
);

PRAGMA user_version = 1;
