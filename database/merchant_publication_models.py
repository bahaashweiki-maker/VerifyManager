"""
database/merchant_publication_models.py
--------------------------------------
Schema for merchant publication administration.

This module creates only isolated tables for merchant publication channels.
Merchant-to-channel permissions are still stored in the existing user_permissions table.
"""

from __future__ import annotations

import logging
import sqlite3

from database.database import get_connection

logger = logging.getLogger(__name__)


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS merchant_publication_channels (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name  TEXT NOT NULL,
    channel_key   TEXT NOT NULL UNIQUE,
    channel_ref   TEXT NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_merchant_pub_channels_active
    ON merchant_publication_channels (is_active, display_name);

CREATE TABLE IF NOT EXISTS merchant_reviews (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id     INTEGER NOT NULL,
    reviewer_id     INTEGER NOT NULL,
    reviewer_name   TEXT,
    review_text     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    response_text   TEXT,
    merchant_reply_text TEXT,
    merchant_reply_status TEXT,
    merchant_reply_updated_at TEXT,
    merchant_reply_admin_note TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_merchant_reviews_merchant
    ON merchant_reviews (merchant_id, created_at DESC);
"""


def init_merchant_publication_db() -> bool:
    try:
        with get_connection() as conn:
            conn.executescript(_SCHEMA_SQL)
            _ensure_review_columns(conn)
        logger.info("merchant_publication_db initialized")
        return True
    except sqlite3.Error as exc:
        logger.critical("init_merchant_publication_db failed: %s", exc, exc_info=True)
        return False


def _ensure_review_columns(conn: sqlite3.Connection) -> None:
    rows = conn.execute("PRAGMA table_info(merchant_reviews)").fetchall()
    existing = {str(row[1]) for row in rows}
    if "status" not in existing:
        conn.execute("ALTER TABLE merchant_reviews ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'")
    if "response_text" not in existing:
        conn.execute("ALTER TABLE merchant_reviews ADD COLUMN response_text TEXT")
    if "merchant_reply_text" not in existing:
        conn.execute("ALTER TABLE merchant_reviews ADD COLUMN merchant_reply_text TEXT")
    if "merchant_reply_status" not in existing:
        conn.execute("ALTER TABLE merchant_reviews ADD COLUMN merchant_reply_status TEXT")
    if "merchant_reply_updated_at" not in existing:
        conn.execute("ALTER TABLE merchant_reviews ADD COLUMN merchant_reply_updated_at TEXT")
    if "merchant_reply_admin_note" not in existing:
        conn.execute("ALTER TABLE merchant_reviews ADD COLUMN merchant_reply_admin_note TEXT")
