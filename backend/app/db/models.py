"""SQLite schema.

Designed so generation can resume across sessions: every chunk carries a
status, and the worker rebuilds its queue from the DB on restart.

Node tiers
----------
* ``section``   -> parent_id IS NULL
* ``subheader`` -> parent_id = section node id

Section types classify content for routing:
BODY, GLOSSARY, TIMELINE, INTRODUCTION, CONCLUSION, SECTION_SUMMARY,
NOTES, BIBLIOGRAPHY.
"""
from __future__ import annotations

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS subjects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    filename    TEXT NOT NULL,
    pdf_path    TEXT NOT NULL,
    page_count  INTEGER NOT NULL DEFAULT 0,
    -- uploaded | approved | generating | done | error
    status      TEXT NOT NULL DEFAULT 'uploaded',
    -- 1 when the guide is an IAD-specific packet (author, title field order)
    is_iad      INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tags (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id  INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    definition  TEXT NOT NULL DEFAULT '',
    builtin     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS nodes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id   INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    parent_id    INTEGER REFERENCES nodes(id) ON DELETE CASCADE,
    tier         TEXT NOT NULL,            -- section | subheader
    title        TEXT NOT NULL,
    section_type TEXT NOT NULL DEFAULT 'BODY',
    order_index  INTEGER NOT NULL DEFAULT 0,
    -- offset boundaries (inline subheaders share/split pages)
    start_page   INTEGER,
    start_line   INTEGER,
    start_char   INTEGER,
    end_page     INTEGER,
    end_line     INTEGER,
    end_char     INTEGER,
    body_text    TEXT NOT NULL DEFAULT '',
    caption_text TEXT NOT NULL DEFAULT '',
    -- intro | selected_work for art-guide subheaders; empty otherwise
    subheader_kind TEXT NOT NULL DEFAULT '',
    -- whether this node is excluded from generation (NOTES/BIBLIOGRAPHY/SUMMARY)
    excluded     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id     INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    idx         INTEGER NOT NULL,
    track       TEXT NOT NULL DEFAULT 'A',   -- A (body) | B (captions)
    text        TEXT NOT NULL,
    -- pending | in_progress | done | error
    status      TEXT NOT NULL DEFAULT 'pending',
    error       TEXT NOT NULL DEFAULT '',
    attempts    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cards (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id     INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    chunk_id    INTEGER REFERENCES chunks(id) ON DELETE CASCADE,
    -- Position within node/chunk (source-text order for AI cards).
    card_index  INTEGER NOT NULL DEFAULT 0,
    front       TEXT NOT NULL,
    back        TEXT NOT NULL,
    tag         TEXT NOT NULL DEFAULT 'other',
    track       TEXT NOT NULL DEFAULT 'A',   -- A | B
    card_hash   TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'ai',  -- ai | glossary | timeline
    edited      INTEGER NOT NULL DEFAULT 0,
    deleted     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_cards_node ON cards(node_id);
CREATE INDEX IF NOT EXISTS idx_cards_hash ON cards(card_hash);

CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id  INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    -- idle | running | paused | done | error
    status      TEXT NOT NULL DEFAULT 'idle',
    message     TEXT NOT NULL DEFAULT '',
    total       INTEGER NOT NULL DEFAULT 0,
    completed   INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- local request accounting for free-tier RPD/RPM (providers don't report reliably)
CREATE TABLE IF NOT EXISTS request_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Cards reviewed during an in-progress validation walkthrough (per node + track).
CREATE TABLE IF NOT EXISTS validation_progress (
    validation_node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    card_id            INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    track              TEXT NOT NULL,
    reviewed_at        TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (validation_node_id, card_id, track)
);
"""
