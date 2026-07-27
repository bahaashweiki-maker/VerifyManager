"""
database/subscriptions_models.py
--------------------------------
Subscription module database schema (standalone).
Creates only new tables for the subscriptions system.
"""

from __future__ import annotations

import logging

from database.database import get_connection

logger = logging.getLogger(__name__)


def init_subscriptions_db() -> None:
    """Create subscriptions module tables if they do not already exist."""
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS subscribers (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id     INTEGER NOT NULL UNIQUE,
                full_name       TEXT,
                username        TEXT,
                status          TEXT NOT NULL DEFAULT 'active',
                joined_at       TEXT DEFAULT (datetime('now')),
                first_seen_at   TEXT,
                last_seen_at    TEXT,
                login_count     INTEGER NOT NULL DEFAULT 0,
                basic_activity  INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriber_activity_log (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                subscriber_id  INTEGER NOT NULL,
                event_key      TEXT NOT NULL,
                payload        TEXT,
                created_at     TEXT DEFAULT (datetime('now')),
                FOREIGN KEY(subscriber_id) REFERENCES subscribers(id)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriber_admin_chats (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                subscriber_id  INTEGER NOT NULL,
                admin_id       INTEGER NOT NULL,
                is_open        INTEGER NOT NULL DEFAULT 1,
                created_at     TEXT DEFAULT (datetime('now')),
                closed_at      TEXT,
                FOREIGN KEY(subscriber_id) REFERENCES subscribers(id)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriber_admin_chat_messages (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id         INTEGER NOT NULL,
                sender_role     TEXT NOT NULL,
                sender_id       INTEGER,
                message_text    TEXT,
                file_id         TEXT,
                created_at      TEXT DEFAULT (datetime('now')),
                FOREIGN KEY(chat_id) REFERENCES subscriber_admin_chats(id)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriber_publications (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                title           TEXT,
                content_text    TEXT,
                media_type      TEXT,
                file_id         TEXT,
                target_type     TEXT NOT NULL DEFAULT 'all',
                target_value    TEXT,
                status          TEXT NOT NULL DEFAULT 'draft',
                scheduled_at    TEXT,
                is_recurring    INTEGER NOT NULL DEFAULT 0,
                repeat_every_minutes INTEGER,
                next_run_at     TEXT,
                last_sent_at    TEXT,
                sent_success_count INTEGER NOT NULL DEFAULT 0,
                sent_fail_count INTEGER NOT NULL DEFAULT 0,
                total_targets   INTEGER NOT NULL DEFAULT 0,
                auto_delete_at  TEXT,
                created_by      INTEGER,
                created_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now'))
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriber_publication_buttons (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                publication_id  INTEGER NOT NULL,
                title           TEXT NOT NULL,
                url             TEXT,
                order_index     INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(publication_id) REFERENCES subscriber_publications(id)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriber_publication_stats (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                publication_id  INTEGER NOT NULL,
                subscriber_id   INTEGER,
                event_key       TEXT NOT NULL,
                created_at      TEXT DEFAULT (datetime('now')),
                FOREIGN KEY(publication_id) REFERENCES subscriber_publications(id),
                FOREIGN KEY(subscriber_id) REFERENCES subscribers(id)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriber_system_stats (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date         TEXT NOT NULL,
                total_subscribers     INTEGER NOT NULL DEFAULT 0,
                active_subscribers    INTEGER NOT NULL DEFAULT 0,
                suspended_subscribers INTEGER NOT NULL DEFAULT 0,
                total_publications    INTEGER NOT NULL DEFAULT 0,
                total_private_msgs    INTEGER NOT NULL DEFAULT 0,
                created_at            TEXT DEFAULT (datetime('now'))
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriber_stats_reset_baselines (
                subscriber_id                 INTEGER PRIMARY KEY,
                login_count_base             INTEGER NOT NULL DEFAULT 0,
                basic_activity_base          INTEGER NOT NULL DEFAULT 0,
                activity_events_base         INTEGER NOT NULL DEFAULT 0,
                messages_to_subscriber_base  INTEGER NOT NULL DEFAULT 0,
                messages_from_subscriber_base INTEGER NOT NULL DEFAULT 0,
                publications_sent_base       INTEGER NOT NULL DEFAULT 0,
                publication_clicks_base      INTEGER NOT NULL DEFAULT 0,
                reset_at                     TEXT DEFAULT (datetime('now')),
                FOREIGN KEY(subscriber_id) REFERENCES subscribers(id)
            )
            """
        )

        conn.commit()

    _migrate_add_column("subscriber_publications", "media_type", "TEXT")
    _migrate_add_column("subscriber_publications", "file_id", "TEXT")
    _migrate_add_column("subscriber_publications", "target_type", "TEXT NOT NULL DEFAULT 'all'")
    _migrate_add_column("subscriber_publications", "target_value", "TEXT")
    _migrate_add_column("subscriber_publications", "is_recurring", "INTEGER NOT NULL DEFAULT 0")
    _migrate_add_column("subscriber_publications", "repeat_every_minutes", "INTEGER")
    _migrate_add_column("subscriber_publications", "next_run_at", "TEXT")
    _migrate_add_column("subscriber_publications", "last_sent_at", "TEXT")
    _migrate_add_column("subscriber_publications", "sent_success_count", "INTEGER NOT NULL DEFAULT 0")
    _migrate_add_column("subscriber_publications", "sent_fail_count", "INTEGER NOT NULL DEFAULT 0")
    _migrate_add_column("subscriber_publications", "total_targets", "INTEGER NOT NULL DEFAULT 0")
    _migrate_add_column("subscriber_publications", "updated_at", "TEXT DEFAULT (datetime('now'))")

    logger.info("subscriptions_db initialized")


def _migrate_add_column(table: str, column: str, definition: str) -> None:
    try:
        with get_connection() as conn:
            existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if column in existing:
                return
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            conn.commit()
    except Exception:
        # Best-effort migration: keep startup resilient for existing deployments.
        pass
