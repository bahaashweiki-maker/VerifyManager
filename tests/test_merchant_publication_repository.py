import sqlite3
from contextlib import contextmanager
from unittest.mock import patch
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from repositories import merchant_publication_repository as repo


def _shared_memory_get_connection():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE user_permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            permission TEXT NOT NULL,
            granted_by INTEGER,
            granted_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(telegram_id, permission)
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


def test_normalize_channel_key_from_link_and_handle() -> None:
    assert repo.normalize_channel_key("https://t.me/My-Channel") == "my_channel"
    assert repo.normalize_channel_key("@my channel") == "my_channel"


def test_grant_and_check_merchant_channel_access() -> None:
    conn, fake_get_connection = _shared_memory_get_connection()
    with patch.object(repo, "get_connection", fake_get_connection):
        ok = repo.grant_merchant_channel_access(telegram_id=111, channel_key="https://t.me/DealsVIP", granted_by=1)
        assert ok is True
        assert repo.merchant_can_publish_to_channel(111, "@dealSvip") is True
        assert repo.list_merchant_allowed_channels(111) == ["dealsvip"]
    conn.close()


def test_revoke_merchant_channel_access() -> None:
    conn, fake_get_connection = _shared_memory_get_connection()
    with patch.object(repo, "get_connection", fake_get_connection):
        repo.grant_merchant_channel_access(telegram_id=222, channel_key="shop_news", granted_by=1)
        assert repo.merchant_can_publish_to_channel(222, "shop_news") is True

        revoked = repo.revoke_merchant_channel_access(222, "shop_news")
        assert revoked is True
        assert repo.merchant_can_publish_to_channel(222, "shop_news") is False
    conn.close()


def test_grant_and_revoke_required_channel() -> None:
    conn, fake_get_connection = _shared_memory_get_connection()
    with patch.object(repo, "get_connection", fake_get_connection):
        assert repo.grant_merchant_required_channel(telegram_id=444, channel_key="@NorthNews", granted_by=1) is True
        assert repo.list_merchant_required_channels(444) == ["northnews"]

        assert repo.revoke_merchant_required_channel(444, "northnews") is True
        assert repo.list_merchant_required_channels(444) == []
    conn.close()


def test_set_and_unset_hourly_publish_permission() -> None:
    conn, fake_get_connection = _shared_memory_get_connection()
    with patch.object(repo, "get_connection", fake_get_connection):
        assert repo.merchant_has_hourly_publish(333) is False

        enabled = repo.set_merchant_hourly_publish(333, True, granted_by=1)
        assert enabled is True
        assert repo.merchant_has_hourly_publish(333) is True

        disabled = repo.set_merchant_hourly_publish(333, False)
        assert disabled is True
        assert repo.merchant_has_hourly_publish(333) is False
    conn.close()


def test_list_merchant_ids_by_base_permission() -> None:
    conn, fake_get_connection = _shared_memory_get_connection()
    with patch.object(repo, "get_connection", fake_get_connection):
        repo.grant_merchant_channel_access(telegram_id=700, channel_key="alpha", granted_by=1)
        repo.set_merchant_hourly_publish(telegram_id=700, enabled=True, granted_by=1)

        with repo.get_connection() as conn:
            conn.execute(
                "INSERT INTO user_permissions (telegram_id, permission, granted_by) VALUES (?, ?, ?)",
                (700, "merchant", 1),
            )
            conn.execute(
                "INSERT INTO user_permissions (telegram_id, permission, granted_by) VALUES (?, ?, ?)",
                (701, "merchant", 1),
            )
            conn.commit()

        merchant_ids = repo.list_merchant_ids()
        assert merchant_ids == [700, 701]
    conn.close()
