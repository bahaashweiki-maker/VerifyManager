from __future__ import annotations

import sqlite3
from typing import Optional

from database.database import get_connection


def _row_factory(cursor, row):
    fields = [d[0] for d in cursor.description]
    return dict(zip(fields, row))


def create_merchant_review(
    merchant_id: int,
    reviewer_id: int,
    reviewer_name: str | None,
    review_text: str,
) -> int:
    text = (review_text or "").strip()
    if merchant_id <= 0 or reviewer_id <= 0 or not text:
        return 0
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO merchant_reviews (
                merchant_id,
                reviewer_id,
                reviewer_name,
                review_text
            )
            VALUES (?, ?, ?, ?)
            """,
            (merchant_id, reviewer_id, (reviewer_name or "").strip() or None, text),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_merchant_reviews(merchant_id: int, limit: int = 10) -> list[dict]:
    if merchant_id <= 0:
        return []
    with get_connection() as conn:
        conn.row_factory = _row_factory
        rows = conn.execute(
            """
            SELECT *
            FROM merchant_reviews
            WHERE merchant_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (merchant_id, max(1, int(limit))),
        ).fetchall()
    return rows


def count_merchant_reviews(merchant_id: int) -> int:
    if merchant_id <= 0:
        return 0
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM merchant_reviews WHERE merchant_id = ?",
            (merchant_id,),
        ).fetchone()
    return int(row[0] or 0) if row else 0


def get_latest_merchant_review(merchant_id: int) -> Optional[dict]:
    rows = list_merchant_reviews(merchant_id, limit=1)
    return rows[0] if rows else None