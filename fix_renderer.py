"""
fix_renderer.py
---------------
Run from the bot root directory.
1. Fixes U+2026 corruption in publishing_renderer.py
2. Applies AUTH-DEBUG patches if not yet applied
3. Verifies syntax
"""
import ast
import os
import sys

PR_PATH = os.path.join("app", "engine", "publishing_renderer.py")

# ---------------------------------------------------------------------------
# Step 1: read file
# ---------------------------------------------------------------------------
with open(PR_PATH, "r", encoding="utf-8") as fh:
    content = fh.read()

# ---------------------------------------------------------------------------
# Step 2: fix any U+2026 corruption
# ---------------------------------------------------------------------------
ELLIPSIS = "\u2026"

fixes = {
    "blocked_target_ids.add(" + ELLIPSIS + ")": 'blocked_target_ids.add(btn["target_page_id"])',
    "return row[0] if row else " + ELLIPSIS: 'return row[0] if row else "none"',
}

fixed_count = 0
for bad, good in fixes.items():
    if bad in content:
        content = content.replace(bad, good)
        print(f"[FIX] Replaced: {bad!r}")
        fixed_count += 1

if ELLIPSIS in content:
    positions = [i for i, c in enumerate(content) if c == ELLIPSIS]
    lines = []
    for pos in positions:
        line_no = content[:pos].count("\n") + 1
        lines.append(line_no)
    print(f"[WARNING] U+2026 still present at lines: {lines}")
    print("[WARNING] Manual fix required for these lines.")
else:
    if fixed_count:
        print("[OK] All U+2026 corruption fixed.")
    else:
        print("[OK] No U+2026 found — file was clean.")

# ---------------------------------------------------------------------------
# Step 3: apply AUTH-DEBUG patches if not yet applied
# ---------------------------------------------------------------------------

PATCH_MARKER = "[AUTH-DEBUG]"
already_patched = PATCH_MARKER in content

if already_patched:
    print("[OK] AUTH-DEBUG patches already present — skipping.")
else:
    print("[PATCH] Applying AUTH-DEBUG patches...")

    # --- Patch A: _get_allowed_slugs ---
    OLD_A = (
        "    try:\n"
        "        auto_catalogs = get_auto_catalogs_for_user(telegram_id)\n"
        "        manual_slugs  = get_user_catalog_slugs(telegram_id)\n"
        '        return {cat["slug"] for cat in auto_catalogs} | manual_slugs\n'
        "    except Exception as exc:\n"
        "        logger.error(\n"
        '            "_get_allowed_slugs failed for telegram_id=%s: %s", telegram_id, exc\n'
        "        )\n"
        "        return set()"
    )
    NEW_A = (
        "    try:\n"
        "        auto_catalogs = get_auto_catalogs_for_user(telegram_id)\n"
        "        manual_slugs  = get_user_catalog_slugs(telegram_id)\n"
        '        auto_slugs    = {cat["slug"] for cat in auto_catalogs}\n'
        "        combined      = auto_slugs | manual_slugs\n"
        '        print(f"[AUTH-DEBUG] _get_allowed_slugs(telegram_id={telegram_id})")\n'
        '        print(f"[AUTH-DEBUG]   auto_slugs={auto_slugs}")\n'
        '        print(f"[AUTH-DEBUG]   manual_slugs={manual_slugs}")\n'
        '        print(f"[AUTH-DEBUG]   combined allowed={combined}")\n'
        "        return combined\n"
        "    except Exception as exc:\n"
        '        print(f"[AUTH-DEBUG] _get_allowed_slugs(telegram_id={telegram_id}) EXCEPTION: {exc}")\n'
        "        logger.error(\n"
        '            "_get_allowed_slugs failed for telegram_id=%s: %s", telegram_id, exc\n'
        "        )\n"
        "        return set()"
    )

    # --- Patch B: handle_user_nav page block ---
    # Uses unicode escapes so the script itself stays ASCII-safe.
    # \U0001f512 = lock emoji, \u05d0...\u05d4 = Hebrew text
    LOCK_MSG = (
        "\u05d0\u05d9\u05df \u05dc\u05da \u05d4\u05e8\u05e9\u05d0\u05d4 "
        "\u05dc\u05e6\u05e4\u05d5\u05ea \u05d1\u05ea\u05d5\u05db\u05df \u05d6\u05d4."
    )

    OLD_B = (
        '        if _raw is not None and _raw["is_active"]:\n'
        '            page_slug = _raw["catalog_slug"]\n'
        "            if page_slug:\n"
        "                allowed = _get_allowed_slugs(query.from_user.id)\n"
        "                if page_slug not in allowed:\n"
        "                    await query.answer(\n"
        '                        "\U0001f512 ' + LOCK_MSG + '",\n'
        "                        show_alert=True,\n"
        "                    )\n"
        "                    return"
    )
    NEW_B = (
        '        if _raw is not None and _raw["is_active"]:\n'
        '            page_slug = _raw["catalog_slug"]\n'
        '            print(f"[AUTH-DEBUG] handle_user_nav page action")\n'
        '            print(f"[AUTH-DEBUG]   telegram_id={query.from_user.id!r}, page_id={page_id}")\n'
        '            print(f"[AUTH-DEBUG]   page_slug from DB={page_slug!r}  (type={type(page_slug).__name__})")\n'
        "            if page_slug:\n"
        "                allowed = _get_allowed_slugs(query.from_user.id)\n"
        '                print(f"[AUTH-DEBUG]   COMPARISON: page_slug={page_slug!r}  in allowed={allowed}  result={page_slug in allowed}")\n'
        "                if page_slug not in allowed:\n"
        '                    print(f"[AUTH-DEBUG]   ACCESS DENIED")\n'
        "                    await query.answer(\n"
        '                        "\U0001f512 ' + LOCK_MSG + '",\n'
        "                        show_alert=True,\n"
        "                    )\n"
        "                    return\n"
        "            else:\n"
        '                print(f"[AUTH-DEBUG]   page_slug is empty/None -- no access check needed")'
    )

    applied = 0
    for tag, old, new in [("_get_allowed_slugs", OLD_A, NEW_A),
                           ("handle_user_nav page block", OLD_B, NEW_B)]:
        if old in content:
            content = content.replace(old, new, 1)
            print(f"  [PATCH] Applied: {tag}")
            applied += 1
        else:
            print(f"  [SKIP] Pattern not found: {tag}")
            print(f"         (file may have different whitespace or already be patched)")

    if applied == 0:
        print("[WARNING] No patches applied. Check the file manually.")

# ---------------------------------------------------------------------------
# Step 4: write back and verify syntax
# ---------------------------------------------------------------------------
with open(PR_PATH, "w", encoding="utf-8") as fh:
    fh.write(content)

try:
    ast.parse(content)
    print(f"\n[OK] Syntax valid: {PR_PATH}")
except SyntaxError as e:
    print(f"\n[ERROR] SyntaxError after patching: {e}")
    print("Restore from backup and contact support.")
    sys.exit(1)

print("\nDone. Restart the bot.")
