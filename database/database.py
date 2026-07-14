"""
database.py
-----------
ממשק גישה ל-SQLite עבור מערכת ניהול האימותים של הבוט.

עקרונות מנחים:
- כל חיבור מנוהל דרך get_connection() (context manager) – נסגר תמיד,
  גם במקרה של חריגה.
- WAL mode מופעל לביצועים טובים יותר בגישה מקבילה (aiogram / asyncio).
- כל פונקציה ציבורית עטופה ב-try/except ומחזירה ערך בטוח (None / [] / False / -1)
  במקרה של כשל, תוך רישום מלא לקובץ הלוג.
- Transactions מפורשים: כל כתיבה מסתיימת ב-conn.commit() מפורש.
- ה-API של הפונקציות הקיימות לא שונה – תאימות מלאה עם שאר הפרויקט.
"""

# from __future__ import annotations חייב להיות השורה הראשונה לאחר ה-docstring.
# מאפשר שימוש ב-list[...] / dict[...] / frozenset[...] כ-type hints
# גם על Python 3.8 (בלעדיו הקוד קורס ב-runtime על גרסאות מתחת ל-3.9).
from __future__ import annotations

import sqlite3
import os
import logging
from contextlib import contextmanager
from typing import Generator, List, Optional
from datetime import datetime
from zoneinfo import ZoneInfo

# -----------------------------------------------------------------------
# הגדרות גלובליות
# -----------------------------------------------------------------------

DB_PATH: str = "database/verify_manager.db"

# ערכי סטטוס חוקיים – שנה כאן בלבד כשמוסיפים מצבים חדשים
VALID_STATUSES: frozenset[str] = frozenset({"pending", "approved", "rejected"})

# שמות העמודות שמותר לעדכן דרך update_verification_fields.
# whitelist מפורש – מונע בניית SQL דינמי עם שמות לא מוכרים.
_UPDATABLE_FIELDS: frozenset[str] = frozenset({"id_photo", "selfie", "social", "video", "code"})

# sqlite3.connect() מקבל float עבור timeout (שניות).
# int עובד בפועל (Python ממיר), אך float מדויק יותר לפי התיעוד.
DB_TIMEOUT: float = 10.0

logger = logging.getLogger(__name__)

# ה-API הציבורי של המודול – מה שייכנס בעת `from database import *`
__all__ = [
    "VALID_STATUSES",
    "DB_PATH",
    "DB_TIMEOUT",
    "get_connection",
    "create_tables",
    "run_migrations",
    "create_verification",
    "get_verifications_by_status",
    "get_verification_by_id",
    "get_verifications_by_telegram_id",
    "get_pending_verification_by_telegram_id",
    "count_verifications_by_status",
    "update_verification_status",
    "update_verification_fields",
    "delete_verification",
]


# -----------------------------------------------------------------------
# ניהול חיבור
# -----------------------------------------------------------------------

@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager שמחזיר חיבור פתוח ל-SQLite וסוגר אותו אוטומטית.

    - יוצר את תיקיית ה-DB אם אינה קיימת.
    - row_factory = sqlite3.Row לגישה לעמודות לפי שם.
    - check_same_thread=False נדרש כי aiogram מריץ callbacks ב-threads שונים.
    - timeout=DB_TIMEOUT מונע תקיעות אם הקובץ נעול.
    - WAL mode מאפשר קריאות מקבילות בזמן כתיבה (ביצועים טובים יותר לבוט).

    Example:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = sqlite3.connect(
        DB_PATH,
        timeout=DB_TIMEOUT,
        check_same_thread=False,  # הכרחי ב-aiogram (asyncio + thread pool)
    )
    conn.row_factory = sqlite3.Row

    # PRAGMA journal_mode=WAL נשמר ב-DB עצמו לאחר ההגדרה הראשונה,
    # אך הגדרתו מחדש בכל חיבור בטוחה ולא גורמת נזק.
    conn.execute("PRAGMA journal_mode=WAL;")
    # אכיפת foreign keys (מוכן לעתיד אם יתווספו טבלאות קשורות)
    conn.execute("PRAGMA foreign_keys=ON;")

    try:
        yield conn
    except sqlite3.Error as exc:
        conn.rollback()
        logger.error("DB error, transaction rolled back: %s", exc, exc_info=True)
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# -----------------------------------------------------------------------
# אתחול הסכמה
# -----------------------------------------------------------------------

def create_tables() -> bool:
    """
    יוצר את כל הטבלאות והאינדקסים הנדרשים אם אינם קיימים.

    יש לקרוא לפונקציה זו פעם אחת בעת הפעלת הבוט (on_startup).
    שינויים בסכמה (הוספת עמודות וכד') מתבצעים ב-run_migrations() – לא כאן.

    Returns:
        True אם הפעולה הצליחה, False אם נכשלה.

    הערה: executescript() מבצע COMMIT פנימי לפני הרצה – זו התנהגות
    תקנית של sqlite3 ב-Python, ולכן אין לעטוף ב-transaction ידני.
    """
    try:
        
        with get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS verifications (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    full_name   TEXT,
                    username    TEXT,
                    id_photo    TEXT,
                    selfie      TEXT,
                    social      TEXT,
                    video       TEXT,
                    code        TEXT,
                    status      TEXT NOT NULL DEFAULT 'pending',
                    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                -- אינדקס לחיפוש מהיר לפי סטטוס (שאילתה נפוצה)
                CREATE INDEX IF NOT EXISTS idx_verifications_status
                    ON verifications (status);

                -- אינדקס לחיפוש מהיר לפי telegram_id
                CREATE INDEX IF NOT EXISTS idx_verifications_telegram_id
                    ON verifications (telegram_id);
            """)
        logger.info("DB tables verified/created successfully.")
        return True
    except sqlite3.Error as exc:
        logger.critical("create_tables failed: %s", exc, exc_info=True)
        return False


def run_migrations() -> bool:
    """
    מוסיף עמודות שחסרות בגרסאות ישנות של ה-DB (schema migration בטוח).

    ניתן לקרוא ל-on_startup לאחר create_tables() – לא גורם נזק
    אם העמודות כבר קיימות (שגיאת duplicate column מטופלת בשקט).

    Returns:
        True אם הסתיים בהצלחה (כולל אם לא היה צורך בשינוי), False בשגיאה.
    """
    # כל migration: (תיאור לוג, שאילתת ALTER TABLE)
    migrations: List[tuple[str, str]] = [
        (
            "add updated_at",
            "ALTER TABLE verifications ADD COLUMN"
            " updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
        ),
    ]

    try:
        with get_connection() as conn:
            for description, sql in migrations:
                try:
                    conn.execute(sql)
                    conn.commit()
                    logger.info("Migration applied: %s", description)
                except sqlite3.OperationalError as exc:
                    # "duplicate column name" – העמודה כבר קיימת, ממשיכים
                    if "duplicate column" in str(exc).lower():
                        logger.debug("Migration skipped (already applied): %s", description)
                    else:
                        raise
        return True
    except sqlite3.Error as exc:
        logger.error("run_migrations failed: %s", exc, exc_info=True)
        return False


# -----------------------------------------------------------------------
# יצירה
# -----------------------------------------------------------------------

def create_verification(
    telegram_id: int,
    
    full_name: Optional[str] = None,
    username: Optional[str] = None,
    id_photo: Optional[str] = None,
    selfie: Optional[str] = None,
    social: Optional[str] = None,
    video: Optional[str] = None,
    code: Optional[str] = None,
) -> int:
    """
    יוצר רשומת אימות חדשה בסטטוס 'pending'.

    Parameters:
        telegram_id: מזהה הטלגרם של המשתמש.
        id_photo:    file_id של תמונת תעודת הזהות (אופציונלי).
        selfie:      file_id של הסלפי (אופציונלי).
        social:      קישור לפרופיל הרשת החברתית (אופציונלי).
        video:       file_id של הסרטון (אופציונלי).
        code:        קוד ייחודי לאימות (אופציונלי).

    Returns:
        ה-id של הרשומה החדשה שנוצרה, או -1 במקרה של כשל.
    """
    try:
        now_il = datetime.now(ZoneInfo("Asia/Jerusalem")).strftime("%Y-%m-%d %H:%M:%S")
        with get_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO verifications
                    (telegram_id, full_name, username, id_photo, selfie, social, video, code, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (telegram_id, full_name, username, id_photo, selfie, social, video, code, now_il),
            )
            conn.commit()
            new_id: int = cur.lastrowid  # type: ignore[assignment]
        logger.info("Created verification id=%d for telegram_id=%d", new_id, telegram_id)
        return new_id
    except sqlite3.Error as exc:
        logger.error(
            "create_verification failed for telegram_id=%d: %s",
            telegram_id, exc, exc_info=True,
        )
        return -1


# -----------------------------------------------------------------------
# שליפה
# -----------------------------------------------------------------------

def get_verifications_by_status(status: str) -> List[sqlite3.Row]:
    """
    מחזיר את כל האימותים בסטטוס נתון, ממוינים מהחדש לישן.

    Parameters:
        status: ערך סטטוס חוקי (ראה VALID_STATUSES).

    Returns:
        רשימת שורות (ריקה אם אין תוצאות או בשגיאה).

    Raises:
        ValueError: אם הסטטוס אינו ב-VALID_STATUSES.
    """
    _validate_status(status)
    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM verifications WHERE status = ? ORDER BY id DESC",
                (status,),
            ).fetchall()
        return rows
    except sqlite3.Error as exc:
        logger.error("get_verifications_by_status(%s) failed: %s", status, exc, exc_info=True)
        return []


def get_verification_by_id(verif_id: int) -> Optional[sqlite3.Row]:
    """
    מחזיר רשומת אימות יחידה לפי ה-id שלה.

    Parameters:
        verif_id: המזהה הפנימי של הרשומה.

    Returns:
        שורת sqlite3.Row, או None אם לא נמצאה / בשגיאה.
    """
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM verifications WHERE id = ?",
                (verif_id,),
            ).fetchone()
        return row
    except sqlite3.Error as exc:
        logger.error("get_verification_by_id(%d) failed: %s", verif_id, exc, exc_info=True)
        return None


def get_verifications_by_telegram_id(telegram_id: int) -> List[sqlite3.Row]:
    """
    מחזיר את כל האימותים של משתמש ספציפי, ממוינים מהחדש לישן.

    Parameters:
        telegram_id: מזהה הטלגרם של המשתמש.

    Returns:
        רשימת שורות (ריקה אם אין אימותים למשתמש / בשגיאה).
    """
    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM verifications WHERE telegram_id = ? ORDER BY id DESC",
                (telegram_id,),
            ).fetchall()
        return rows
    except sqlite3.Error as exc:
        logger.error(
            "get_verifications_by_telegram_id(%d) failed: %s",
            telegram_id, exc, exc_info=True,
        )
        return []


def get_pending_verification_by_telegram_id(telegram_id: int) -> Optional[sqlite3.Row]:
    """
    מחזיר את האימות הפעיל (pending) של משתמש, אם קיים.

    שימושי לפני יצירת אימות חדש – למנוע כפילויות.

    Parameters:
        telegram_id: מזהה הטלגרם של המשתמש.

    Returns:
        שורת sqlite3.Row, או None אם אין אימות ממתין / בשגיאה.
    """
    try:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM verifications
                WHERE telegram_id = ? AND status = 'pending'
                ORDER BY id DESC
                LIMIT 1
                """,
                (telegram_id,),
            ).fetchone()
        return row
    except sqlite3.Error as exc:
        logger.error(
            "get_pending_verification_by_telegram_id(%d) failed: %s",
            telegram_id, exc, exc_info=True,
        )
        return None


def count_verifications_by_status(status: str) -> int:
    """
    מחזיר את מספר האימותים בסטטוס נתון.

    שימושי לפאנל ניהול / סטטיסטיקות.

    Parameters:
        status: ערך סטטוס חוקי (ראה VALID_STATUSES).

    Returns:
        מספר השורות, או -1 בשגיאה.

    Raises:
        ValueError: אם הסטטוס אינו ב-VALID_STATUSES.
    """
    _validate_status(status)
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM verifications WHERE status = ?",
                (status,),
            ).fetchone()
        return int(row[0]) if row else 0
    except sqlite3.Error as exc:
        logger.error("count_verifications_by_status(%s) failed: %s", status, exc, exc_info=True)
        return -1


# -----------------------------------------------------------------------
# עדכון
# -----------------------------------------------------------------------

def update_verification_status(verif_id: int, new_status: str) -> bool:
    """
    מעדכן את סטטוס האימות ומרענן את updated_at אוטומטית.

    Parameters:
        verif_id:   המזהה הפנימי של הרשומה.
        new_status: הסטטוס החדש (חייב להיות ב-VALID_STATUSES).

    Returns:
        True אם השורה אכן עודכנה, False אם ה-id לא נמצא או בשגיאה.

    Raises:
        ValueError: אם new_status אינו ב-VALID_STATUSES.
    """
    _validate_status(new_status)
    try:
        with get_connection() as conn:
            cur = conn.execute(
                """
                UPDATE verifications
                SET status     = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (new_status, verif_id),
            )
            conn.commit()
            updated = cur.rowcount > 0

        if updated:
            logger.info("Updated verification id=%d -> status='%s'", verif_id, new_status)
        else:
            logger.warning("update_verification_status: id=%d not found", verif_id)
        return updated

    except sqlite3.Error as exc:
        logger.error(
            "update_verification_status(id=%d, status=%s) failed: %s",
            verif_id, new_status, exc, exc_info=True,
        )
        return False


def update_verification_fields(
    verif_id: int,
    id_photo: Optional[str] = None,
    selfie: Optional[str] = None,
    social: Optional[str] = None,
    video: Optional[str] = None,
    code: Optional[str] = None,
) -> bool:
    """
    מעדכן שדות מדיה של אימות קיים (רק שדות שאינם None).

    שימושי כשהמשתמש שולח קבצים בשלבים נפרדים (conversation handler).
    שמות העמודות נבדקים מול _UPDATABLE_FIELDS לפני בניית ה-SQL.

    Parameters:
        verif_id:  המזהה הפנימי של הרשומה.
        id_photo:  file_id חדש לתמונת ת.ז (אופציונלי).
        selfie:    file_id חדש לסלפי (אופציונלי).
        social:    קישור חדש לרשת חברתית (אופציונלי).
        video:     file_id חדש לסרטון (אופציונלי).
        code:      קוד אימות חדש (אופציונלי).

    Returns:
        True אם עדכון בוצע, False אם אין שדות לעדכן / id לא קיים / שגיאה.
    """
    # בונים dict רק מהשדות שהועברו ומאומתים מול ה-whitelist
    candidate: dict[str, str] = {
        "id_photo": id_photo,   # type: ignore[assignment]
        "selfie":   selfie,     # type: ignore[assignment]
        "social":   social,     # type: ignore[assignment]
        "video":    video,      # type: ignore[assignment]
        "code":     code,       # type: ignore[assignment]
    }
    # מסנן None ומוודא שכל שם עמודה מאושר ב-whitelist
    fields: dict[str, str] = {
        col: val
        for col, val in candidate.items()
        if val is not None and col in _UPDATABLE_FIELDS
    }

    if not fields:
        logger.warning(
            "update_verification_fields called with no valid fields to update (id=%d)", verif_id
        )
        return False

    # SET clause בנוי משמות עמודות ידועים בלבד – אין סיכון SQL injection
    set_clause = ", ".join(f"{col} = ?" for col in fields)
    values: list[object] = [*fields.values(), verif_id]

    try:
        with get_connection() as conn:
            cur = conn.execute(
                f"UPDATE verifications"
                f" SET {set_clause}, updated_at = CURRENT_TIMESTAMP"
                f" WHERE id = ?",
                values,
            )
            conn.commit()
            updated = cur.rowcount > 0

        if updated:
            logger.info(
                "Updated fields %s for verification id=%d", list(fields.keys()), verif_id
            )
        else:
            logger.warning("update_verification_fields: id=%d not found", verif_id)
        return updated

    except sqlite3.Error as exc:
        logger.error(
            "update_verification_fields(id=%d) failed: %s",
            verif_id, exc, exc_info=True,
        )
        return False


# -----------------------------------------------------------------------
# מחיקה
# -----------------------------------------------------------------------

def delete_verification(verif_id: int) -> bool:
    """
    מוחק רשומת אימות לפי id.

    Parameters:
        verif_id: המזהה הפנימי של הרשומה.

    Returns:
        True אם השורה נמחקה, False אם ה-id לא נמצא / בשגיאה.
    """
    try:
        with get_connection() as conn:
            cur = conn.execute(
                "DELETE FROM verifications WHERE id = ?",
                (verif_id,),
            )
            conn.commit()
            deleted = cur.rowcount > 0

        if deleted:
            logger.info("Deleted verification id=%d", verif_id)
        else:
            logger.warning("delete_verification: id=%d not found", verif_id)
        return deleted

    except sqlite3.Error as exc:
        logger.error("delete_verification(id=%d) failed: %s", verif_id, exc, exc_info=True)
        return False


# -----------------------------------------------------------------------
# פונקציות עזר פנימיות
# -----------------------------------------------------------------------

def _validate_status(status: str) -> None:
    """
    בודק שהסטטוס הוא אחד מהערכים המוגדרים ב-VALID_STATUSES.

    Raises:
        ValueError: עם הודעה מפורטת אם הסטטוס אינו חוקי.
    """
    if status not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status '{status}'. "
            f"Allowed values: {sorted(VALID_STATUSES)}"
        )
