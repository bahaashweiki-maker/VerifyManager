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
                status          TEXT NOT NULL DEFAULT 'draft',
                scheduled_at    TEXT,
                auto_delete_at  TEXT,
                created_by      INTEGER,
                created_at      TEXT DEFAULT (datetime('now'))
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

    logger.info("subscriptions_db initialized")
