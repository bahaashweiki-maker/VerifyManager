import sqlite3
import sys
import os

DB = "database/verify_manager.db"

if not os.path.exists(DB):
    print(f"❌ DB לא נמצא בנתיב: {os.path.abspath(DB)}")
    print(f"   תיקייה נוכחית: {os.getcwd()}")
    sys.exit(1)

conn = sqlite3.connect(DB)
conn.row_factory = lambda c, r: dict(zip([d[0] for d in c.description], r))

print(f"✅ DB נמצא: {os.path.abspath(DB)}\n")

# --- טבלאות קיימות ---
tables = [r["name"] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
).fetchall()]
print(f"=== טבלאות ב-DB ===\n{tables}\n")

# --- catalogs ---
print("=== catalogs ===")
try:
    rows = conn.execute("SELECT id, slug, name, audience, is_active FROM catalogs").fetchall()
    if rows:
        for r in rows:
            print(r)
    else:
        print("(ריקה — אין שורות)")
except Exception as e:
    print(f"❌ שגיאה: {e}")

# --- publishing_pages עם catalog_slug ---
print("\n=== publishing_pages עם catalog_slug ===")
try:
    rows = conn.execute(
        "SELECT id, title, catalog_slug FROM publishing_pages "
        "WHERE catalog_slug IS NOT NULL AND catalog_slug != ''"
    ).fetchall()
    if rows:
        for r in rows:
            print(r)
    else:
        print("(אין עמודים עם catalog_slug)")
except Exception as e:
    print(f"❌ שגיאה: {e}")

# --- user_type_assignments ---
print("\n=== user_type_assignments ===")
try:
    rows = conn.execute("SELECT * FROM user_type_assignments").fetchall()
    if rows:
        for r in rows:
            print(r)
    else:
        print("(ריקה — אין שורות)")
except Exception as e:
    print(f"❌ שגיאה: {e}")

# --- user_permissions ---
print("\n=== user_permissions ===")
try:
    rows = conn.execute("SELECT * FROM user_permissions").fetchall()
    if rows:
        for r in rows:
            print(r)
    else:
        print("(ריקה — אין שורות)")
except Exception as e:
    print(f"❌ שגיאה: {e}")

conn.close()
print("\n✅ סיום אבחון")