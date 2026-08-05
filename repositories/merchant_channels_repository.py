"""
repositories/merchant_channels_repository.py
-------------------------------------------
Repository for globally managed merchant publication channels.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Optional

from database.database import get_connection
from repositories.merchant_publication_repository import normalize_channel_key

logger = logging.getLogger(__name__)


def _row_factory(cursor, row):
    fields = [d[0] for d in cursor.description]
    return dict(zip(fields, row))


def create_channel(channel_ref: str, display_name: str | None = None) -> int:
    normalized_ref = (channel_ref or "").strip()
    channel_key = normalize_channel_key(normalized_ref)
    if not channel_key:
        return 0

    channel_name = (display_name or normalized_ref).strip() or channel_key

    try:
        with get_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO merchant_publication_channels (
                    display_name,
                    channel_key,
                    channel_ref,
                    is_active
                )
                VALUES (?, ?, ?, 1)
                ON CONFLICT(channel_key) DO UPDATE
                    SET display_name = excluded.display_name,
                        channel_ref = excluded.channel_ref,
                        is_active = 1
                """,
                (channel_name, channel_key, normalized_ref),
            )
            conn.commit()
            if cur.lastrowid:
                return int(cur.lastrowid)

            row = conn.execute(
                "SELECT id FROM merchant_publication_channels WHERE channel_key = ? LIMIT 1",
                (channel_key,),
            ).fetchone()
            return int(row[0]) if row else 0
    except sqlite3.Error as exc:
        logger.error("create_channel(%s) failed: %s", channel_ref, exc)
        return 0


def list_channels(active_only: bool = True) -> list[dict]:
    where_sql = "WHERE is_active = 1" if active_only else ""
    try:
        with get_connection() as conn:
            conn.row_factory = _row_factory
            rows = conn.execute(
                f"""
                SELECT *
                FROM merchant_publication_channels
                {where_sql}
                ORDER BY display_name COLLATE NOCASE ASC, id ASC
                """
            ).fetchall()
        return rows
    except sqlite3.Error as exc:
        logger.error("list_channels failed: %s", exc)
        return []


def get_channel_by_id(channel_id: int) -> Optional[dict]:
    try:
        with get_connection() as conn:
            conn.row_factory = _row_factory
            row = conn.execute(
                "SELECT * FROM merchant_publication_channels WHERE id = ? LIMIT 1",
                (channel_id,),
            ).fetchone()
        return row
    except sqlite3.Error as exc:
        logger.error("get_channel_by_id(%s) failed: %s", channel_id, exc)
        return None


def deactivate_channel(channel_id: int) -> bool:
    try:
        with get_connection() as conn:
            cur = conn.execute(
                """
                UPDATE merchant_publication_channels
                SET is_active = 0
                WHERE id = ?
                """,
                (channel_id,),
            )
            conn.commit()
        return cur.rowcount > 0
    except sqlite3.Error as exc:
        logger.error("deactivate_channel(%s) failed: %s", channel_id, exc)
        return False
