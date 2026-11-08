-- Personal place registry (design § 6.3), schema version 5.
-- Applied by PlaceRegistry on a database whose user_version is 0, and replayed
-- on a database of an older version 2 or more (only CREATE ... IF NOT EXISTS).

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

-- Arrondissement precision decisions of the user, per occurrence key: the writing
-- (complement removed), the complement ('' when none) and the period of the date
-- ('' when undated). Both ids NULL = the user decided no arrondissement applies.
CREATE TABLE IF NOT EXISTS precisions (
    writing           TEXT NOT NULL,
    complement        TEXT NOT NULL,
    period            TEXT NOT NULL,
    arrondissement_id TEXT,
    quartier_id       TEXT,
    project           TEXT,
    decided_at        TEXT NOT NULL,
    PRIMARY KEY (writing, complement, period)
);

-- Source proposals the user refused, per subject (``place:<id>`` or
-- ``writing:<text>``), source and proposed article identifier.
CREATE TABLE IF NOT EXISTS refused_proposals (
    subject    TEXT NOT NULL,
    source     TEXT NOT NULL,
    identifier TEXT NOT NULL,
    project    TEXT,
    decided_at TEXT NOT NULL,
    PRIMARY KEY (subject, source, identifier)
);

-- GeoNames mode chosen per country (ISO alpha-2, uppercase); absence = 'written'.
CREATE TABLE IF NOT EXISTS country_settings (
    country    TEXT PRIMARY KEY,
    mode       TEXT NOT NULL CHECK (mode IN ('written', 'geonames')),
    project    TEXT,
    decided_at TEXT
);

-- Per-writing correction of the country mode (the writing, the source).
CREATE TABLE IF NOT EXISTS source_overrides (
    writing    TEXT NOT NULL,
    source     TEXT NOT NULL,
    mode       TEXT NOT NULL CHECK (mode IN ('written', 'geonames')),
    project    TEXT,
    decided_at TEXT,
    PRIMARY KEY (writing, source)
);

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

PRAGMA user_version = 5;
