from __future__ import annotations

from database.database import get_connection


def _ensure_system_stats_reset_baseline_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS subscriber_system_stats_reset_baselines (
            id                           INTEGER PRIMARY KEY CHECK (id = 1),
            total_private_msgs_base      INTEGER NOT NULL DEFAULT 0,
            private_msgs_admin_base      INTEGER NOT NULL DEFAULT 0,
            private_msgs_subscriber_base INTEGER NOT NULL DEFAULT 0,
            total_private_chats_base     INTEGER NOT NULL DEFAULT 0,
            open_private_chats_base      INTEGER NOT NULL DEFAULT 0,
            total_activity_events_base   INTEGER NOT NULL DEFAULT 0,
            publication_clicks_base      INTEGER NOT NULL DEFAULT 0,
            reset_at                     TEXT DEFAULT (datetime('now'))
        )
        """
    )


def get_subscriber_personal_stats(subscriber_id: int) -> dict:
    with get_connection() as conn:
        conn.row_factory = _row_factory

        subscriber = conn.execute(
            "SELECT * FROM subscribers WHERE id = ?",
            (subscriber_id,),
        ).fetchone() or {}

        msgs_from_admin = _read_count(conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM subscriber_admin_chat_messages m
            JOIN subscriber_admin_chats c ON c.id = m.chat_id
            WHERE c.subscriber_id = ?
              AND m.sender_role = 'admin'
            """,
            (subscriber_id,),
        ).fetchone())

        msgs_from_subscriber = _read_count(conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM subscriber_admin_chat_messages m
            JOIN subscriber_admin_chats c ON c.id = m.chat_id
            WHERE c.subscriber_id = ?
                            AND m.sender_role IN ('subscriber', 'user')
            """,
            (subscriber_id,),
        ).fetchone())

        sent_publications = _read_count(conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM subscriber_publication_stats
            WHERE subscriber_id = ?
              AND event_key IN ('sent', 'delivered')
            """,
            (subscriber_id,),
        ).fetchone())

        publication_clicks = _read_count(conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM subscriber_publication_stats
            WHERE subscriber_id = ?
              AND event_key IN ('click', 'button_click')
            """,
            (subscriber_id,),
        ).fetchone())

        activity_events = _read_count(conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM subscriber_activity_log
            WHERE subscriber_id = ?
            """,
            (subscriber_id,),
        ).fetchone())

        warnings_count = _read_count(conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM subscriber_activity_log
            WHERE subscriber_id = ?
              AND event_key = 'warning'
            """,
            (subscriber_id,),
        ).fetchone())

        admin_notes_count = _read_count(conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM subscriber_activity_log
            WHERE subscriber_id = ?
              AND event_key = 'admin_note'
            """,
            (subscriber_id,),
        ).fetchone())

        baseline = conn.execute(
            """
            SELECT *
            FROM subscriber_stats_reset_baselines
            WHERE subscriber_id = ?
            """,
            (subscriber_id,),
        ).fetchone() or {}

        login_count = _normalized_delta(
            subscriber.get("login_count"),
            baseline.get("login_count_base")
        )
        basic_activity = _normalized_delta(
            subscriber.get("basic_activity"),
            baseline.get("basic_activity_base")
        )
        activity_events_effective = _normalized_delta(
            activity_events,
            baseline.get("activity_events_base")
        )
        msgs_from_admin_effective = _normalized_delta(
            msgs_from_admin,
            baseline.get("messages_to_subscriber_base")
        )
        msgs_from_subscriber_effective = _normalized_delta(
            msgs_from_subscriber,
            baseline.get("messages_from_subscriber_base")
        )
        sent_publications_effective = _normalized_delta(
            sent_publications,
            baseline.get("publications_sent_base")
        )
        publication_clicks_effective = _normalized_delta(
            publication_clicks,
            baseline.get("publication_clicks_base")
        )

        return {
            "joined_at": subscriber.get("joined_at"),
            "first_seen_at": subscriber.get("first_seen_at"),
            "last_seen_at": subscriber.get("last_seen_at"),
            "login_count": login_count,
            "basic_activity": basic_activity,
            "activity_events": activity_events_effective,
            "messages_sent_to_subscriber": msgs_from_admin_effective,
            "messages_received_from_subscriber": msgs_from_subscriber_effective,
            "publications_sent": sent_publications_effective,
            "publication_button_clicks": publication_clicks_effective,
            "warnings_count": warnings_count,
            "admin_notes_count": admin_notes_count,
        }


def reset_subscriber_personal_stats(subscriber_id: int) -> bool:
    with get_connection() as conn:
        conn.row_factory = _row_factory

        subscriber = conn.execute(
            "SELECT login_count, basic_activity FROM subscribers WHERE id = ?",
            (subscriber_id,),
        ).fetchone()
        if not subscriber:
            return False

        msgs_from_admin = _read_count(conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM subscriber_admin_chat_messages m
            JOIN subscriber_admin_chats c ON c.id = m.chat_id
            WHERE c.subscriber_id = ?
              AND m.sender_role = 'admin'
            """,
            (subscriber_id,),
        ).fetchone())

        msgs_from_subscriber = _read_count(conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM subscriber_admin_chat_messages m
            JOIN subscriber_admin_chats c ON c.id = m.chat_id
            WHERE c.subscriber_id = ?
              AND m.sender_role IN ('subscriber', 'user')
            """,
            (subscriber_id,),
        ).fetchone())

        sent_publications = _read_count(conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM subscriber_publication_stats
            WHERE subscriber_id = ?
              AND event_key IN ('sent', 'delivered')
            """,
            (subscriber_id,),
        ).fetchone())

        publication_clicks = _read_count(conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM subscriber_publication_stats
            WHERE subscriber_id = ?
              AND event_key IN ('click', 'button_click')
            """,
            (subscriber_id,),
        ).fetchone())

        activity_events = _read_count(conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM subscriber_activity_log
            WHERE subscriber_id = ?
            """,
            (subscriber_id,),
        ).fetchone())

        conn.execute(
            """
            INSERT INTO subscriber_stats_reset_baselines (
                subscriber_id,
                login_count_base,
                basic_activity_base,
                activity_events_base,
                messages_to_subscriber_base,
                messages_from_subscriber_base,
                publications_sent_base,
                publication_clicks_base,
                reset_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(subscriber_id) DO UPDATE SET
                login_count_base = excluded.login_count_base,
                basic_activity_base = excluded.basic_activity_base,
                activity_events_base = excluded.activity_events_base,
                messages_to_subscriber_base = excluded.messages_to_subscriber_base,
                messages_from_subscriber_base = excluded.messages_from_subscriber_base,
                publications_sent_base = excluded.publications_sent_base,
                publication_clicks_base = excluded.publication_clicks_base,
                reset_at = datetime('now')
            """,
            (
                subscriber_id,
                int(subscriber.get("login_count") or 0),
                int(subscriber.get("basic_activity") or 0),
                activity_events,
                msgs_from_admin,
                msgs_from_subscriber,
                sent_publications,
                publication_clicks,
            ),
        )
        conn.commit()
        return True


def _read_count(row) -> int:
    if row is None:
        return 0
    if isinstance(row, dict):
        return int(row.get("total") or 0)
    try:
        return int(row[0] or 0)
    except Exception:
        return 0


def _normalized_delta(current, baseline) -> int:
    cur = int(current or 0)
    base = int(baseline or 0)
    return max(0, cur - base)


def get_subscriber_activity(subscriber_id: int, limit: int = 50) -> list:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            """
            SELECT *
            FROM subscriber_activity_log
            WHERE subscriber_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (subscriber_id, limit),
        )
        return cur.fetchall()


def get_global_stats_snapshots(limit: int = 30) -> list:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        cur = conn.execute(
            """
            SELECT *
            FROM subscriber_system_stats
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return cur.fetchall()


def get_live_subscription_system_stats() -> dict:
    with get_connection() as conn:
        conn.row_factory = _row_factory
        _ensure_system_stats_reset_baseline_table(conn)

        total_subscribers = _read_count(conn.execute(
            "SELECT COUNT(*) AS total FROM subscribers"
        ).fetchone())
        active_subscribers = _read_count(conn.execute(
            "SELECT COUNT(*) AS total FROM subscribers WHERE status = 'active'"
        ).fetchone())
        suspended_subscribers = _read_count(conn.execute(
            "SELECT COUNT(*) AS total FROM subscribers WHERE status = 'suspended'"
        ).fetchone())
        blocked_subscribers = _read_count(conn.execute(
            "SELECT COUNT(*) AS total FROM subscribers WHERE status = 'blocked'"
        ).fetchone())

        total_publications = _read_count(conn.execute(
            "SELECT COUNT(*) AS total FROM subscriber_publications"
        ).fetchone())
        scheduled_publications = _read_count(conn.execute(
            "SELECT COUNT(*) AS total FROM subscriber_publications WHERE status = 'scheduled'"
        ).fetchone())
        active_publications = _read_count(conn.execute(
            "SELECT COUNT(*) AS total FROM subscriber_publications WHERE status = 'active'"
        ).fetchone())

        total_private_msgs = _read_count(conn.execute(
            "SELECT COUNT(*) AS total FROM subscriber_admin_chat_messages"
        ).fetchone())
        private_msgs_from_admin = _read_count(conn.execute(
            "SELECT COUNT(*) AS total FROM subscriber_admin_chat_messages WHERE sender_role = 'admin'"
        ).fetchone())
        private_msgs_from_subscribers = _read_count(conn.execute(
            "SELECT COUNT(*) AS total FROM subscriber_admin_chat_messages WHERE sender_role IN ('subscriber', 'user')"
        ).fetchone())

        total_private_chats = _read_count(conn.execute(
            "SELECT COUNT(*) AS total FROM subscriber_admin_chats"
        ).fetchone())
        open_private_chats = _read_count(conn.execute(
            "SELECT COUNT(*) AS total FROM subscriber_admin_chats WHERE is_open = 1"
        ).fetchone())

        total_activity_events = _read_count(conn.execute(
            "SELECT COUNT(*) AS total FROM subscriber_activity_log"
        ).fetchone())

        publication_button_clicks = _read_count(conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM subscriber_publication_stats
            WHERE event_key IN ('click', 'button_click')
            """
        ).fetchone())

        baseline = conn.execute(
            """
            SELECT *
            FROM subscriber_system_stats_reset_baselines
            WHERE id = 1
            """
        ).fetchone() or {}

        total_private_msgs = _normalized_delta(total_private_msgs, baseline.get("total_private_msgs_base"))
        private_msgs_from_admin = _normalized_delta(private_msgs_from_admin, baseline.get("private_msgs_admin_base"))
        private_msgs_from_subscribers = _normalized_delta(private_msgs_from_subscribers, baseline.get("private_msgs_subscriber_base"))
        total_private_chats = _normalized_delta(total_private_chats, baseline.get("total_private_chats_base"))
        open_private_chats = _normalized_delta(open_private_chats, baseline.get("open_private_chats_base"))
        total_activity_events = _normalized_delta(total_activity_events, baseline.get("total_activity_events_base"))
        publication_button_clicks = _normalized_delta(publication_button_clicks, baseline.get("publication_clicks_base"))

        return {
            "total_subscribers": total_subscribers,
            "active_subscribers": active_subscribers,
            "suspended_subscribers": suspended_subscribers,
            "blocked_subscribers": blocked_subscribers,
            "total_publications": total_publications,
            "scheduled_publications": scheduled_publications,
            "active_publications": active_publications,
            "total_private_msgs": total_private_msgs,
            "private_msgs_from_admin": private_msgs_from_admin,
            "private_msgs_from_subscribers": private_msgs_from_subscribers,
            "total_private_chats": total_private_chats,
            "open_private_chats": open_private_chats,
            "total_activity_events": total_activity_events,
            "publication_button_clicks": publication_button_clicks,
        }


def reset_global_action_stats() -> bool:
    with get_connection() as conn:
        _ensure_system_stats_reset_baseline_table(conn)
        total_private_msgs = _read_count(conn.execute(
            "SELECT COUNT(*) AS total FROM subscriber_admin_chat_messages"
        ).fetchone())
        private_msgs_from_admin = _read_count(conn.execute(
            "SELECT COUNT(*) AS total FROM subscriber_admin_chat_messages WHERE sender_role = 'admin'"
        ).fetchone())
        private_msgs_from_subscribers = _read_count(conn.execute(
            "SELECT COUNT(*) AS total FROM subscriber_admin_chat_messages WHERE sender_role IN ('subscriber', 'user')"
        ).fetchone())
        total_private_chats = _read_count(conn.execute(
            "SELECT COUNT(*) AS total FROM subscriber_admin_chats"
        ).fetchone())
        open_private_chats = _read_count(conn.execute(
            "SELECT COUNT(*) AS total FROM subscriber_admin_chats WHERE is_open = 1"
        ).fetchone())
        total_activity_events = _read_count(conn.execute(
            "SELECT COUNT(*) AS total FROM subscriber_activity_log"
        ).fetchone())
        publication_button_clicks = _read_count(conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM subscriber_publication_stats
            WHERE event_key IN ('click', 'button_click')
            """
        ).fetchone())

        conn.execute(
            """
            INSERT INTO subscriber_system_stats_reset_baselines (
                id,
                total_private_msgs_base,
                private_msgs_admin_base,
                private_msgs_subscriber_base,
                total_private_chats_base,
                open_private_chats_base,
                total_activity_events_base,
                publication_clicks_base,
                reset_at
            )
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(id) DO UPDATE SET
                total_private_msgs_base = excluded.total_private_msgs_base,
                private_msgs_admin_base = excluded.private_msgs_admin_base,
                private_msgs_subscriber_base = excluded.private_msgs_subscriber_base,
                total_private_chats_base = excluded.total_private_chats_base,
                open_private_chats_base = excluded.open_private_chats_base,
                total_activity_events_base = excluded.total_activity_events_base,
                publication_clicks_base = excluded.publication_clicks_base,
                reset_at = datetime('now')
            """,
            (
                total_private_msgs,
                private_msgs_from_admin,
                private_msgs_from_subscribers,
                total_private_chats,
                open_private_chats,
                total_activity_events,
                publication_button_clicks,
            ),
        )
        conn.commit()
        return True


def _row_factory(cursor, row):
    fields = [d[0] for d in cursor.description]
    return dict(zip(fields, row))
