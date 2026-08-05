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
"""


def init_merchant_publication_db() -> bool:
    try:
        with get_connection() as conn:
            conn.executescript(_SCHEMA_SQL)
        logger.info("merchant_publication_db initialized")
        return True
    except sqlite3.Error as exc:
        logger.critical("init_merchant_publication_db failed: %s", exc, exc_info=True)
        return False
