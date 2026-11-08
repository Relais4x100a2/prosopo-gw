-- Personal place registry (design § 6.3), schema version 2.
-- Applied by PlaceRegistry on a database whose user_version is 0.

CREATE TABLE IF NOT EXISTS places (
    place_id   TEXT PRIMARY KEY,          -- UUID4, stable
    created_at TEXT NOT NULL              -- UTC ISO 8601
);

-- Level chain of a place: rank 0 is the most precise level. Validated and
-- proposed levels share the rank sequence (see places/levels.py).
CREATE TABLE IF NOT EXISTS place_levels (
    place_id   TEXT NOT NULL REFERENCES places (place_id),
    rank       INTEGER NOT NULL CHECK (rank >= 0),
    name       TEXT NOT NULL,
    written    TEXT,
    type       TEXT,
    identifier TEXT,
    source     TEXT,
    start      TEXT,
    "end"      TEXT,
    latitude   REAL,
    longitude  REAL,
    nature     TEXT CHECK (nature IN ('fusion', 'associee', 'deleguee')),
    origin     TEXT NOT NULL CHECK (origin IN ('written', 'rule', 'manual', 'insee',
                   'paris', 'dicotopo', 'geonames', 'llm')),
    status     TEXT NOT NULL CHECK (status IN ('validated', 'proposed')),
    PRIMARY KEY (place_id, rank)
);

-- Attributes of a place that are not levels (the postal code).
CREATE TABLE IF NOT EXISTS place_attributes (
    place_id TEXT NOT NULL REFERENCES places (place_id),
    name     TEXT NOT NULL CHECK (name IN ('postal_code')),
    value    TEXT NOT NULL,
    origin   TEXT NOT NULL CHECK (origin IN ('written', 'rule', 'manual', 'insee')),
    PRIMARY KEY (place_id, name)
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
                 'detach', 'undo', 'import', 'migrate')),
    payload  TEXT NOT NULL,                -- JSON, see registry.py
    undone   INTEGER NOT NULL DEFAULT 0 CHECK (undone IN (0, 1))
);

PRAGMA user_version = 2;
