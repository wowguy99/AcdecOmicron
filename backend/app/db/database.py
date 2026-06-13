"""SQLite connection helpers and schema initialization."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from ..config import DB_PATH, ensure_dirs
from .models import SCHEMA_SQL


def _connect() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(nodes)").fetchall()}
    if "validated_at" not in cols:
        conn.execute("ALTER TABLE nodes ADD COLUMN validated_at TEXT")
    if "subheader_kind" not in cols:
        conn.execute(
            "ALTER TABLE nodes ADD COLUMN subheader_kind TEXT NOT NULL DEFAULT ''"
        )
    subj_cols = {row[1] for row in conn.execute("PRAGMA table_info(subjects)").fetchall()}
    if "is_iad" not in subj_cols:
        conn.execute(
            "ALTER TABLE subjects ADD COLUMN is_iad INTEGER NOT NULL DEFAULT 0"
        )
    card_cols = {row[1] for row in conn.execute("PRAGMA table_info(cards)").fetchall()}
    if "card_index" not in card_cols:
        conn.execute(
            "ALTER TABLE cards ADD COLUMN card_index INTEGER NOT NULL DEFAULT 0"
        )
        _backfill_card_index(conn)
        _reorder_chunk_cards_from_source(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS validation_progress (
            validation_node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
            card_id            INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
            track              TEXT NOT NULL,
            reviewed_at        TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (validation_node_id, card_id, track)
        )
        """
    )


def _reorder_chunk_cards_from_source(conn: sqlite3.Connection) -> None:
    from ..generation.compile import reorder_node_cards_in_db

    pairs = conn.execute(
        """
        SELECT DISTINCT c.node_id, c.track
        FROM cards c
        JOIN nodes n ON n.id = c.node_id
        WHERE c.deleted = 0 AND c.source = 'ai'
        """
    ).fetchall()
    for row in pairs:
        reorder_node_cards_in_db(conn, row["node_id"], row["track"])


def _backfill_card_index(conn: sqlite3.Connection) -> None:
    """Assign card_index from legacy insert order (id) per node/chunk group."""
    rows = conn.execute(
        "SELECT id, node_id, chunk_id FROM cards ORDER BY node_id, chunk_id, id"
    ).fetchall()
    idx = 0
    last_key: tuple[int, int | None] | None = None
    for row in rows:
        key = (row["node_id"], row["chunk_id"])
        if key != last_key:
            idx = 0
            last_key = key
        conn.execute(
            "UPDATE cards SET card_index = ? WHERE id = ?", (idx, row["id"])
        )
        idx += 1


def _purge_test_seed_subjects(conn: sqlite3.Connection) -> None:
    """Remove subjects left by pytest using placeholder pdf_path ``'x'``."""
    conn.execute("DELETE FROM subjects WHERE pdf_path = 'x'")


def purge_accidental_test_subjects() -> None:
    with get_conn() as conn:
        _purge_test_seed_subjects(conn)


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA_SQL)
        _migrate(conn)


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
