"""
database/publishing_models.py
------------------------------
אתחול טבלאות מודול הפרסום.

קריאה: הוסף `init_publishing_db()` לפונקציית on_startup שלך, אחרי `create_tables()`.

דוגמה ב-app/main.py:
    from database.publishing_models import init_publishing_db
    ...
    create_tables()
    init_publishing_db()
"""

from __future__ import annotations

import logging
import sqlite3

from database.database import get_connection

logger = logging.getLogger(__name__)


def init_publishing_db() -> bool:
    """
    יוצר את 3 הטבלאות של מודול הפרסום אם אינן קיימות.

    - publishing_home    — שורה יחידה (singleton) לדף הבית
    - publishing_pages   — עמודים/קטלוגים עם עומק בלתי מוגבל
    - publishing_buttons — כפתורים לכל עמוד / דף בית

    Returns:
        True אם הצליח, False אם נכשל.
    """
    try:
        with get_connection() as conn:
            conn.executescript("""
                -- ===== דף הבית (singleton) =====
                CREATE TABLE IF NOT EXISTS publishing_home (
                    id              INTEGER PRIMARY KEY CHECK (id = 1),
                    image_file_id   TEXT,
                    text            TEXT,
                    is_active       INTEGER NOT NULL DEFAULT 1,
                    -- עמודות עתידיות לניהול הרשאות (לא מופעלות עדיין)
                    required_role   TEXT,
                    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                -- הכנסת שורת singleton אם אינה קיימת
                INSERT OR IGNORE INTO publishing_home (id) VALUES (1);

                -- ===== עמודים =====
                CREATE TABLE IF NOT EXISTS publishing_pages (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    parent_id       INTEGER REFERENCES publishing_pages(id) ON DELETE CASCADE,
                    title           TEXT NOT NULL,
                    image_file_id   TEXT,
                    text            TEXT,
                    page_type       TEXT NOT NULL DEFAULT 'page',   -- 'page' | 'catalog'
                    sort_order      INTEGER NOT NULL DEFAULT 0,
                    is_active       INTEGER NOT NULL DEFAULT 1,
                    -- עמודות עתידיות להרשאות
                    required_role   TEXT,
                    can_view_role   TEXT,
                    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_pub_pages_parent
                    ON publishing_pages (parent_id, sort_order);

                -- ===== כפתורים =====
                CREATE TABLE IF NOT EXISTS publishing_buttons (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    -- כפתור שייך לדף בית (home_id=1) או לעמוד (page_id)
                    home_id         INTEGER REFERENCES publishing_home(id) ON DELETE CASCADE,
                    page_id         INTEGER REFERENCES publishing_pages(id) ON DELETE CASCADE,
                    label           TEXT NOT NULL,
                    button_type     TEXT NOT NULL DEFAULT 'text',
                    -- 7 סוגי כפתורים:
                    -- text       – הודעת טקסט
                    -- url        – קישור חיצוני
                    -- page_link  – ניווט לעמוד פנימי
                    -- phone      – מספר טלפון
                    -- email      – כתובת מייל
                    -- location   – מיקום (lat,lon)
                    -- share      – שיתוף הבוט
                    value           TEXT,       -- URL / טקסט / page_id / ...
                    target_page_id  INTEGER REFERENCES publishing_pages(id) ON DELETE SET NULL,
                    sort_order      INTEGER NOT NULL DEFAULT 0,
                    row_index       INTEGER NOT NULL DEFAULT 0,   -- שורה במקלדת
                    is_active       INTEGER NOT NULL DEFAULT 1,
                    -- עמודות עתידיות להרשאות
                    required_role   TEXT,
                    can_click_role  TEXT,
                    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    -- כל כפתור שייך בדיוק למקום אחד
                    CHECK (
                        (home_id IS NOT NULL AND page_id IS NULL)
                        OR
                        (home_id IS NULL AND page_id IS NOT NULL)
                    )
                );

                CREATE INDEX IF NOT EXISTS idx_pub_buttons_home
                    ON publishing_buttons (home_id, sort_order);

                CREATE INDEX IF NOT EXISTS idx_pub_buttons_page
                    ON publishing_buttons (page_id, sort_order);
            """)

        logger.info("Publishing DB tables verified/created successfully.")
        return True

    except sqlite3.Error as exc:
        logger.critical("init_publishing_db failed: %s", exc, exc_info=True)
        return False