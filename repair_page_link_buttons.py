#!/usr/bin/env python3
"""
repair_page_link_buttons.py
----------------------------
סקריפט תיקון חד-פעמי לרשומות פגומות בטבלת publishing_buttons.

מטרה:
    לאתר ולתקן כפתורי page_link שה-target_page_id שלהם:
      (א) None / 0 (חסר), או
      (ב) מצביע לעמוד שכבר לא קיים ב-publishing_pages (dangling reference),
    ולוודא שאף כפתור לא יכול להישאר עם value ארוך/שגוי שעלול לייצר
    callback_data פגום (Button_data_invalid) אחרי התיקון ב-
    publishing_renderer.py / publishing_admin.py.

איך פועל:
    לכל כפתור פגום מסוג page_link:
      1. ניסיון שחזור: אם value מכיל אך ורק ספרות (מחרוזת שלמה של
         מספר), ואותו מספר הוא id קיים בפועל ב-publishing_pages —
         הכפתור "מאומץ" מחדש: target_page_id מתעדכן לאותו מספר,
         ו-value מתאפס ל-''.
      2. אם לא ניתן לשחזר (value ריק, לא-מספרי, או ה-id לא קיים) —
         הכפתור מנוקה (target_page_id=NULL, value='') כדי שלא יוכל
         להוות סיכון, ומדווח לרשימת "לבדיקה ידנית" בסוף הריצה.
         כפתור כזה פשוט לא יופיע במקלדת (_db_btn_to_tg מחזיר None)
         עד שמנהל ישייך לו עמוד יעד מחדש דרך "ערוך ערך" באדמין.

    בנוסף: אם value ארוך במיוחד (>200 תווים) — לא ננסה "לשחזר" ממנו
    בשום מקרה (ודאי לא page id אמיתי), רק ננקה.

שימוש:
    python3 repair_page_link_buttons.py /path/to/database.db          # dry-run (ברירת מחדל)
    python3 repair_page_link_buttons.py /path/to/database.db --apply  # מבצע בפועל

מומלץ:
    לקחת גיבוי לקובץ ה-DB לפני הרצה עם --apply:
        cp database.db database.db.bak-before-repair
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db_path", help="נתיב לקובץ ה-SQLite (למשל database.db)")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="לבצע את התיקון בפועל. בלי הדגל — dry-run בלבד (מציג מה היה קורה).",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="לדלג על גיבוי אוטומטי של קובץ ה-DB לפני --apply (לא מומלץ).",
    )
    args = parser.parse_args()

    if args.apply and not args.no_backup:
        backup_path = f"{args.db_path}.bak-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        shutil.copy2(args.db_path, backup_path)
        print(f"📦 גיבוי נוצר: {backup_path}")

    conn = sqlite3.connect(args.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # כל כפתורי ה-page_link הקיימים
    rows = conn.execute(
        "SELECT id, label, value, target_page_id FROM publishing_buttons"
        " WHERE button_type = 'page_link'"
    ).fetchall()

    existing_page_ids = {
        r[0] for r in conn.execute("SELECT id FROM publishing_pages").fetchall()
    }

    recoverable: list[tuple[int, str, int]] = []   # (btn_id, label, recovered_page_id)
    needs_manual: list[tuple[int, str, str]] = []  # (btn_id, label, reason)

    for row in rows:
        btn_id  = row["id"]
        label   = row["label"]
        value   = row["value"] or ""
        target  = row["target_page_id"]

        target_ok = target is not None and target in existing_page_ids
        if target_ok:
            continue  # כפתור תקין — לא נוגעים בו

        # כפתור פגום: target_page_id חסר או dangling
        candidate = value.strip()
        if candidate.isdigit() and len(candidate) <= 10:
            candidate_id = int(candidate)
            if candidate_id in existing_page_ids:
                recoverable.append((btn_id, label, candidate_id))
                continue

        reason = (
            "target_page_id חסר/לא קיים, value לא ניתן לשחזור "
            f"(len={len(value)})"
        )
        needs_manual.append((btn_id, label, reason))

    print(f"\nנמצאו {len(rows)} כפתורי page_link בסך הכול.")
    print(f"  ✅ תקינים:                {len(rows) - len(recoverable) - len(needs_manual)}")
    print(f"  🔧 ניתנים לשחזור אוטומטי: {len(recoverable)}")
    print(f"  ⚠️  דורשים בדיקה ידנית:   {len(needs_manual)}\n")

    if recoverable:
        print("--- שחזור אוטומטי (target_page_id ישוחזר מ-value) ---")
        for btn_id, label, page_id in recoverable:
            print(f"  btn_id={btn_id:<6} label={label!r:<40} -> target_page_id={page_id}")

    if needs_manual:
        print("\n--- דורש בדיקה ידנית (ינוקה, יש לשייך עמוד יעד מחדש דרך האדמין) ---")
        for btn_id, label, reason in needs_manual:
            print(f"  btn_id={btn_id:<6} label={label!r:<40} ({reason})")

    if not args.apply:
        print("\n🔍 זהו dry-run בלבד — שום דבר לא נכתב ל-DB.")
        print("   הריצו שוב עם --apply כדי לבצע בפועל.")
        conn.close()
        return 0

    # --- ביצוע בפועל ---
    for btn_id, _label, page_id in recoverable:
        conn.execute(
            "UPDATE publishing_buttons"
            " SET target_page_id = ?, value = '', updated_at = CURRENT_TIMESTAMP"
            " WHERE id = ?",
            (page_id, btn_id),
        )

    for btn_id, _label, _reason in needs_manual:
        conn.execute(
            "UPDATE publishing_buttons"
            " SET target_page_id = NULL, value = '', updated_at = CURRENT_TIMESTAMP"
            " WHERE id = ?",
            (btn_id,),
        )

    conn.commit()
    conn.close()

    print(f"\n✅ בוצע. {len(recoverable)} כפתורים שוחזרו, "
          f"{len(needs_manual)} כפתורים נוקו וממתינים לשיוך ידני מחדש.")
    return 0


if __name__ == "__main__":
    sys.exit(main())