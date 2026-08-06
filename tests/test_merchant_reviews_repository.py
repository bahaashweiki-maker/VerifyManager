import sqlite3
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from repositories import merchant_reviews_repository as repo


def _shared_memory_get_connection():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE merchant_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_id INTEGER NOT NULL,
            reviewer_id INTEGER NOT NULL,
            reviewer_name TEXT,
            review_text TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )

    @contextmanager
    def _get_connection():
        try:
            yield conn
        finally:
            pass

    return conn, _get_connection


def test_create_and_list_merchant_reviews() -> None:
    conn, fake_get_connection = _shared_memory_get_connection()
    with patch.object(repo, "get_connection", fake_get_connection):
        review_id = repo.create_merchant_review(merchant_id=10, reviewer_id=20, reviewer_name="Tester", review_text="Great seller")
        assert review_id > 0
        assert repo.count_merchant_reviews(10) == 1
        rows = repo.list_merchant_reviews(10)
        assert len(rows) == 1
        assert rows[0]["review_text"] == "Great seller"
        assert rows[0]["reviewer_name"] == "Tester"
    conn.close()