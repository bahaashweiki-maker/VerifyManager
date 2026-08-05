import sqlite3
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from repositories import merchant_channels_repository as repo


def _shared_memory_get_connection():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE merchant_publication_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            display_name TEXT NOT NULL,
            channel_key TEXT NOT NULL UNIQUE,
            channel_ref TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
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


def test_create_and_list_channels() -> None:
    conn, fake_get_connection = _shared_memory_get_connection()
    with patch.object(repo, "get_connection", fake_get_connection):
        first_id = repo.create_channel("https://t.me/SalesVIP")
        assert first_id > 0

        channels = repo.list_channels()
        assert len(channels) == 1
        assert channels[0]["channel_key"] == "salesvip"
        assert channels[0]["display_name"] == "https://t.me/SalesVIP"
    conn.close()


def test_create_channel_reactivates_existing_key() -> None:
    conn, fake_get_connection = _shared_memory_get_connection()
    with patch.object(repo, "get_connection", fake_get_connection):
        first_id = repo.create_channel("@DealsNow")
        assert first_id > 0
        assert repo.deactivate_channel(first_id) is True

        second_id = repo.create_channel("https://t.me/DealsNow")
        assert second_id == first_id

        active_channels = repo.list_channels()
        assert len(active_channels) == 1
        assert active_channels[0]["is_active"] == 1
    conn.close()


def test_get_channel_by_id_returns_none_when_missing() -> None:
    conn, fake_get_connection = _shared_memory_get_connection()
    with patch.object(repo, "get_connection", fake_get_connection):
        assert repo.get_channel_by_id(999) is None
    conn.close()
