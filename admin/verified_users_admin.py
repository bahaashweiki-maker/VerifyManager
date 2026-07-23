"""
admin/verified_users_admin.py
─────────────────────────────────────────────────────────────────────────────
מרכז שליטה על מאומתים — VerifyManager

Callbacks:
    VUSERS_LIST                        — רשימת מאומתים
    VUSERS_VIEW_{vid}                  — פרופיל + לוח בקרה
    VUSERS_TYPE_{vid}                  — בחירת סוג משתמש
    VUSERS_TYPE_SET_{vid}_{type_key}   — שמירת סוג משתמש
    VUSERS_WARN_LIST_{vid}             — ניהול אזהרות
    VUSERS_WARN_ADD_{vid}              — פרומפט הוספת אזהרה
    VUSERS_WARN_DEL_{vid}_{wid}        — מחיקת אזהרה
    VUSERS_SUSPEND_{vid}               — בחירת משך השעיה
    VUSERS_SUSPEND_DO_{vid}_{dur}      — ביצוע השעיה
    VUSERS_UNSUSPEND_{vid}             — ביטול השעיה
    VUSERS_BLOCK_{vid}                 — אישור חסימה
    VUSERS_BLOCK_CONFIRM_{vid}         — ביצוע חסימה
    VUSERS_UNBLOCK_{vid}               — אישור שחרור חסימה
    VUSERS_UNBLOCK_CONFIRM_{vid}       — ביצוע שחרור
    VUSERS_PERMS_{vid}                 — הרשאות כלליות
    VUSERS_PERM_TOGGLE_{vid}_{k}       — toggle הרשאה כללית
    VUSERS_CATALOGS_{vid}              — קטלוגים של המשתמש
    VUSERS_CAT_TOGGLE_{vid}_{s}        — toggle הרשאת קטלוג ידני
    VUSERS_MSG_{vid}                   — שליחת הודעה
    VUSERS_NOTES_{vid}                 — ניהול הערות מנהל
    VUSERS_NOTE_ADD_{vid}              — פרומפט הוספת הערה
    VUSERS_NOTE_DEL_{vid}_{nid}        — מחיקת הערה
    VUSERS_HISTORY_{vid}               — היסטוריית פעולות
    VUSERS_REVOKE_{vid}                — אישור ביטול אימות
    VUSERS_REVOKE_CONFIRM_{vid}        — ביצוע ביטול אימות
    VUSERS_DELETE_DOS_{vid}            — אישור מחיקת תיק אימות
    VUSERS_DELETE_DOS_CONFIRM_{vid}    — ביצוע מחיקת תיק אימות
    VUSERS_CATMGR                      — ניהול קטלוגים (כללי)
    VUSERS_CATMGR_NEW                  — פרומפט יצירת קטלוג חדש
    VUSERS_CATMGR_EDIT_{cid}           — עריכת קטלוג
    VUSERS_CATMGR_AUD_{cid}_{aud}      — שינוי קהל יעד
    VUSERS_CATMGR_PUB_{cid}           — toggle is_publishable
    VUSERS_CATMGR_RO_{cid}            — toggle is_readonly
    VUSERS_CATMGR_DEL_{cid}           — אישור מחיקת קטלוג
    VUSERS_CATMGR_DEL_OK_{cid}        — ביצוע מחיקה
    VUSERS_CANCEL                      — ביטול קלט

state ב-context.user_data:
    vusers_state      — מצב קלט פעיל
    vusers_vid        — verification_id של המשתמש הנוכחי
    vusers_cid        — catalog_id בזמן עריכה
    vusers_chat_id    — chat_id של הודעה לעדכון
    vusers_msg_id     — message_id של הודעה לעדכון
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config.user_permissions import USER_PERMISSIONS
from services.verified_users_service import (
    # משתמש
    get_all_verified_users,
    get_verified_user_by_id,
    get_verified_users_count,
    revoke_verification,
    delete_verification_dossier,
    # סוג משתמש
    get_user_type,
    set_user_type,
    get_user_type_display,
    USER_TYPES,
    # אזהרות
    add_warning,
    get_warnings,
    get_warning_by_id,
    delete_warning,
    get_warnings_count,
    # השעיות
    suspend_user,
    lift_suspension,
    get_active_suspension,
    is_suspended,
    SUSPEND_LABELS,
    # חסימה
    block_verified_user,
    unblock_verified_user,
    # הרשאות כלליות
    get_user_general_permissions,
    grant_general_permission,
    revoke_general_permission,
    # קטלוגים
    get_all_catalogs,
    get_catalog_by_id,
    get_custom_catalogs,
    get_auto_catalogs_for_user,
    get_user_catalog_slugs,
    toggle_catalog_permission,
    create_catalog,
    update_catalog,
    delete_catalog,
    CATALOG_AUDIENCES,
    # הודעות
    log_message,
    # הערות
    add_admin_note,
    get_admin_notes,
    get_admin_note_by_id,
    delete_admin_note,
    # היסטוריה
    get_user_history,
)

from services.verification_chats_service import (
    create_verification_chat,
    get_user_verification_chats,
    get_verification_chat,
    close_verification_chat,
    add_verification_chat_message,
    get_verification_chat_messages,
    get_verification_chat_message,
)

logger = logging.getLogger(__name__)

# ─── State keys ───────────────────────────────────────────────────────────────
_STATE   = "vusers_state"
_VID     = "vusers_vid"
_CID     = "vusers_cid"
_CHAT_ID = "vusers_chat_id"
_MSG_ID  = "vusers_msg_id"

_AWAIT_WARN     = "VUSERS_AWAIT_WARN"
_AWAIT_MSG      = "VUSERS_AWAIT_MSG"
_AWAIT_NOTE     = "VUSERS_AWAIT_NOTE"
_AWAIT_CAT_NAME = "VUSERS_AWAIT_CAT_NAME"
_AWAIT_CHAT_MSG = "VCHAT_AWAIT_MSG"

# ── שיחות אימות — state keys ───────────────────────────────────────────────────
_VCHAT_VID = "vchat_vid"
_VCHAT_ID  = "vchat_id"


# ─────────────────────────────────────────────────────────────────────────────
# ניתוב ראשי
# ─────────────────────────────────────────────────────────────────────────────

async def verified_users_route(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    data  = query.data
    try:
        qfrom = getattr(query.from_user, 'id', None)
    except Exception:
        qfrom = None

    if data == "VUSERS_LIST":
        return await _show_users_list(update, context)

    if data.startswith("VUSERS_VIEW_"):
        vid = int(data[len("VUSERS_VIEW_"):])
        return await _show_user_view(update, context, vid)

    # ── סוג משתמש ─────────────────────────────────────────────────────────────
    if data.startswith("VUSERS_TYPE_SET_"):
        suffix = data[len("VUSERS_TYPE_SET_"):]
        idx    = suffix.index("_")
        vid    = int(suffix[:idx])
        tkey   = suffix[idx + 1:]
        return await _execute_set_type(update, context, vid, tkey)

    if data.startswith("VUSERS_TYPE_"):
        vid = int(data[len("VUSERS_TYPE_"):])
        return await _show_type_selection(update, context, vid)

    # ── אזהרות ────────────────────────────────────────────────────────────────
    if data.startswith("VUSERS_WARN_LIST_"):
        vid = int(data[len("VUSERS_WARN_LIST_"):])
        print(f"[DEBUG] verified_users_route -> VUSERS_WARN_LIST routing to _show_warnings_list vid={vid!r}")
        return await _show_warnings_list(update, context, vid)

    if data.startswith("VUSERS_WARN_ADD_"):
        vid = int(data[len("VUSERS_WARN_ADD_"):])
        print(f"[DEBUG] verified_users_route -> VUSERS_WARN_ADD routing to _prompt_add_warning vid={vid!r}")
        return await _prompt_add_warning(update, context, vid)

    if data.startswith("VUSERS_WARN_DEL_"):
        suffix = data[len("VUSERS_WARN_DEL_"):]
        vid, wid = _split_two_ids(suffix)
        print(f"[DEBUG] verified_users_route -> VUSERS_WARN_DEL routing to _delete_warning_action vid={vid!r} wid={wid!r}")
        return await _delete_warning_action(update, context, vid, wid)

    if data.startswith("VUSERS_WARN_VIEW_"):
        # VUSERS_WARN_VIEW_{vid}_{wid} -> show full warning content with back button
        suffix = data[len("VUSERS_WARN_VIEW_"):]
        parts = suffix.split("_", 1)
        if len(parts) == 2:
            vid = int(parts[0])
            wid = int(parts[1])
            print(f"[DEBUG] verified_users_route -> VUSERS_WARN_VIEW routing to _view_warning vid={vid!r} wid={wid!r}")
            return await _view_warning(update, context, vid, wid)
        else:
            return await _show_warnings_list(update, context, int(parts[0]) if parts else 0)

    # ── השעיות ────────────────────────────────────────────────────────────────
    if data.startswith("VUSERS_SUSPEND_DO_"):
        suffix = data[len("VUSERS_SUSPEND_DO_"):]
        idx    = suffix.index("_")
        vid    = int(suffix[:idx])
        dur    = suffix[idx + 1:]
        print(f"[DEBUG] verified_users_route -> VUSERS_SUSPEND_DO routing to _execute_suspend vid={vid!r} dur={dur!r}")
        return await _execute_suspend(update, context, vid, dur)

    if data.startswith("VUSERS_SUSPEND_"):
        vid = int(data[len("VUSERS_SUSPEND_"):])
        print(f"[DEBUG] verified_users_route -> VUSERS_SUSPEND routing to _show_suspend_menu vid={vid!r}")
        return await _show_suspend_menu(update, context, vid)

    if data.startswith("VUSERS_UNSUSPEND_"):
        vid = int(data[len("VUSERS_UNSUSPEND_"):])
        print(f"[DEBUG] verified_users_route -> VUSERS_UNSUSPEND routing to _execute_unsuspend vid={vid!r}")
        return await _execute_unsuspend(update, context, vid)

    # ── חסימה ─────────────────────────────────────────────────────────────────
    if data.startswith("VUSERS_BLOCK_CONFIRM_"):
        vid = int(data[len("VUSERS_BLOCK_CONFIRM_"):])
        print(f"[DEBUG] verified_users_route -> VUSERS_BLOCK_CONFIRM routing to _execute_block vid={vid!r}")
        return await _execute_block(update, context, vid)

    if data.startswith("VUSERS_BLOCK_"):
        vid = int(data[len("VUSERS_BLOCK_"):])
        print(f"[DEBUG] verified_users_route -> VUSERS_BLOCK routing to _confirm_block vid={vid!r}")
        return await _confirm_block(update, context, vid)

    if data.startswith("VUSERS_UNBLOCK_CONFIRM_"):
        vid = int(data[len("VUSERS_UNBLOCK_CONFIRM_"):])
        print(f"[DEBUG] verified_users_route -> VUSERS_UNBLOCK_CONFIRM routing to _execute_unblock vid={vid!r}")
        return await _execute_unblock(update, context, vid)

    if data.startswith("VUSERS_UNBLOCK_"):
        vid = int(data[len("VUSERS_UNBLOCK_"):])
        print(f"[DEBUG] verified_users_route -> VUSERS_UNBLOCK routing to _confirm_unblock vid={vid!r}")
        return await _confirm_unblock(update, context, vid)

    # ── הרשאות כלליות ─────────────────────────────────────────────────────────
    if data.startswith("VUSERS_PERM_TOGGLE_"):
        suffix = data[len("VUSERS_PERM_TOGGLE_"):]
        idx    = suffix.index("_")
        vid    = int(suffix[:idx])
        key    = suffix[idx + 1:]
        return await _toggle_general_permission(update, context, vid, key)

    if data.startswith("VUSERS_PERMS_"):
        vid = int(data[len("VUSERS_PERMS_"):])
        return await _show_permissions(update, context, vid)

    # ── קטלוגים per-user ──────────────────────────────────────────────────────
    if data.startswith("VUSERS_CAT_TOGGLE_"):
        suffix = data[len("VUSERS_CAT_TOGGLE_"):]
        idx    = suffix.index("_")
        vid    = int(suffix[:idx])
        slug   = suffix[idx + 1:]
        return await _toggle_catalog_action(update, context, vid, slug)

    if data.startswith("VUSERS_CATALOGS_"):
        vid = int(data[len("VUSERS_CATALOGS_"):])
        return await _show_user_catalogs(update, context, vid)

    # ── ניהול קטלוגים (כללי) ─────────────────────────────────────────────────
    if data == "VUSERS_CATMGR":
        return await _show_catalog_manager(update, context)

    if data == "VUSERS_CATMGR_NEW":
        return await _prompt_new_catalog(update, context)

    if data.startswith("VUSERS_CATMGR_AUD_"):
        suffix = data[len("VUSERS_CATMGR_AUD_"):]
        idx    = suffix.index("_")
        cid    = int(suffix[:idx])
        aud    = suffix[idx + 1:]
        return await _set_catalog_audience(update, context, cid, aud)

    if data.startswith("VUSERS_CATMGR_PUB_"):
        cid = int(data[len("VUSERS_CATMGR_PUB_"):])
        return await _toggle_catalog_publishable(update, context, cid)

    if data.startswith("VUSERS_CATMGR_RO_"):
        cid = int(data[len("VUSERS_CATMGR_RO_"):])
        return await _toggle_catalog_readonly(update, context, cid)

    if data.startswith("VUSERS_CATMGR_DEL_OK_"):
        cid = int(data[len("VUSERS_CATMGR_DEL_OK_"):])
        return await _execute_delete_catalog(update, context, cid)

    if data.startswith("VUSERS_CATMGR_DEL_"):
        cid = int(data[len("VUSERS_CATMGR_DEL_"):])
        return await _confirm_delete_catalog(update, context, cid)

    if data.startswith("VUSERS_CATMGR_EDIT_"):
        cid = int(data[len("VUSERS_CATMGR_EDIT_"):])
        return await _show_catalog_edit(update, context, cid)

    # ── הודעה / הערות / היסטוריה ───────────────────────────────────────────────
    if data.startswith("VUSERS_MSG_"):
        vid = int(data[len("VUSERS_MSG_"):])
        return await _prompt_send_message(update, context, vid)

    if data.startswith("VUSERS_NOTE_ADD_"):
        vid = int(data[len("VUSERS_NOTE_ADD_"):])
        return await _prompt_add_note(update, context, vid)

    if data.startswith("VUSERS_NOTE_DEL_"):
        suffix = data[len("VUSERS_NOTE_DEL_"):]
        vid, nid = _split_two_ids(suffix)
        return await _delete_note_action(update, context, vid, nid)

    if data.startswith("VUSERS_NOTE_VIEW_"):
        # VUSERS_NOTE_VIEW_{vid}_{nid} -> show full note content with back button
        suffix = data[len("VUSERS_NOTE_VIEW_"):]
        parts = suffix.split("_", 1)
        if len(parts) == 2:
            vid = int(parts[0])
            nid = int(parts[1])
            return await _view_note(update, context, vid, nid)
        else:
            return await _show_notes_list(update, context, int(parts[0]) if parts else 0)

    if data.startswith("VUSERS_NOTES_"):
        vid = int(data[len("VUSERS_NOTES_"):])
        return await _show_notes_list(update, context, vid)

    if data.startswith("VUSERS_HISTORY_"):
        vid = int(data[len("VUSERS_HISTORY_"):])
        return await _show_history(update, context, vid)

    # ── ביטול אימות ───────────────────────────────────────────────────────────
    if data.startswith("VUSERS_REVOKE_CONFIRM_"):
        vid = int(data[len("VUSERS_REVOKE_CONFIRM_"):])
        return await _execute_revoke(update, context, vid)

    if data.startswith("VUSERS_REVOKE_"):
        vid = int(data[len("VUSERS_REVOKE_"):])
        return await _confirm_revoke(update, context, vid)

    # ── מחיקת תיק אימות ───────────────────────────────────────────────────────────
    if data.startswith("VUSERS_DELETE_DOS_CONFIRM_"):
        vid = int(data[len("VUSERS_DELETE_DOS_CONFIRM_"):])
        return await _execute_delete_dossier(update, context, vid)

    if data.startswith("VUSERS_DELETE_DOS_"):
        vid = int(data[len("VUSERS_DELETE_DOS_"):])
        return await _confirm_delete_dossier(update, context, vid)

    # ── שיחות אימות ───────────────────────────────────────────────────────────
    if data.startswith("VCHAT_MEDIA_BACK_"):
        suffix = data[len("VCHAT_MEDIA_BACK_"):]
        vid, chat_id = _split_two_ids(suffix)
        return await _back_from_chat_media(update, context, vid, chat_id)

    if data.startswith("VCHAT_MEDIA_"):
        suffix = data[len("VCHAT_MEDIA_"):]
        parts = suffix.split("_")
        vid = int(parts[0]); chat_id = int(parts[1]); msg_id = int(parts[2])
        return await _show_chat_media(update, context, vid, chat_id, msg_id)

    if data.startswith("VCHAT_CLOSE_OK_"):
        suffix = data[len("VCHAT_CLOSE_OK_"):]
        vid, chat_id = _split_two_ids(suffix)
        return await _execute_close_chat(update, context, vid, chat_id)

    if data.startswith("VCHAT_CLOSE_"):
        suffix = data[len("VCHAT_CLOSE_"):]
        vid, chat_id = _split_two_ids(suffix)
        return await _confirm_close_chat(update, context, vid, chat_id)

    if data.startswith("VCHAT_SEND_"):
        suffix = data[len("VCHAT_SEND_"):]
        vid, chat_id = _split_two_ids(suffix)
        return await _prompt_send_chat_message(update, context, vid, chat_id)

    if data.startswith("VCHAT_VIEW_"):
        suffix = data[len("VCHAT_VIEW_"):]
        vid, chat_id = _split_two_ids(suffix)
        return await _show_chat_messages(update, context, vid, chat_id)

    if data.startswith("VCHAT_OPEN_"):
        vid = int(data[len("VCHAT_OPEN_"):])
        return await _open_verification_chat(update, context, vid)

    if data.startswith("VCHAT_LIST_"):
        vid = int(data[len("VCHAT_LIST_"):])
        return await _show_verification_chats(update, context, vid)

    if data == "VUSERS_CANCEL":
        return await _cancel_input(update, context)


async def _view_note(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int, nid: int
) -> None:
    """Show full admin note content and back button to notes list."""
    v = get_verified_user_by_id(vid)
    if not v:
        await update.callback_query.answer("⚠️ משתמש לא נמצא.", show_alert=True)
        return

    n = get_admin_note_by_id(nid)
    if not n:
        await update.callback_query.answer("⚠️ הערה לא נמצאה.", show_alert=True)
        return

    text = (
        f"📝 <b>הערת מנהל</b>\n\n"
        f"{n.get('note', '')}\n\n"
        f"<i>נרשמה בתאריך: {_fmt_date(n.get('created_at'))}</i>"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ חזרה", callback_data=f"VUSERS_NOTES_{vid}")],
    ])

    await update.callback_query.edit_message_text(text=text, reply_markup=keyboard, parse_mode="HTML")


# ─────────────────────────────────────────────────────────────────────────────
# קלט טקסט מהמשתמש
# ─────────────────────────────────────────────────────────────────────────────
async def handle_verified_users_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    state = context.user_data.get(_STATE, "")
    text  = (update.message.text or "").strip()

    try:
        await update.message.delete()
    except Exception:
        pass

    if state == _AWAIT_WARN:
        await _process_add_warning(update, context, text)
    elif state == _AWAIT_MSG:
        await _process_send_message(update, context, text)
    elif state == _AWAIT_NOTE:
        await _process_add_note(update, context, text)
    elif state == _AWAIT_CAT_NAME:
        await _process_new_catalog(update, context, text)
    elif state == _AWAIT_CHAT_MSG:
        await _process_send_chat_message(update, context, text)


# ─────────────────────────────────────────────────────────────────────────────
# רשימת מאומתים
# ─────────────────────────────────────────────────────────────────────────────

async def _show_users_list(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    _clear_state(context)
    users = get_all_verified_users()

    buttons = []
    for u in users:
        name  = u["full_name"] or u["username"] or "משתמש לא ידוע"
        tkey  = get_user_type(u["telegram_id"])
        status_emoji = "🟢" if u.get("status") == "approved" else ("🚫" if u.get("status") == "blocked" else "🔴")
        emoji = USER_TYPES.get(tkey, {}).get("emoji", "👤")
        buttons.append([InlineKeyboardButton(
            f"{status_emoji} {emoji} {name}",
            callback_data=f"VUSERS_VIEW_{u['id']}",
        )])

    buttons.append([InlineKeyboardButton("📂 ניהול קטלוגים", callback_data="VUSERS_CATMGR")])
    buttons.append([InlineKeyboardButton("🔙 חזרה", callback_data="ADMIN_PANEL")])

    header = (
        f"👥 <b>מאומתים</b> ({len(users)})\n\nבחר משתמש:"
        if users else
        "👥 <b>ניהול מאומתים</b>\n\nאין מאומתים כרגע."
    )

    await update.callback_query.edit_message_text(
        text=header,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────────────────────────────────────
# פרופיל + לוח בקרה
# ─────────────────────────────────────────────────────────────────────────────

async def _show_user_view(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int
) -> None:
    _clear_state(context)
    v = get_verified_user_by_id(vid)
    if not v:
        await update.callback_query.answer("⚠️ משתמש לא נמצא.", show_alert=True)
        return

    tgid         = v["telegram_id"]
    name         = v["full_name"] or "ללא שם"
    username     = f"📛 @{v['username']}\n" if v.get("username") else ""
    date         = _fmt_date(v["created_at"])
    warn_count   = get_warnings_count(tgid)
    suspension   = get_active_suspension(tgid)
    is_blocked   = v["status"] == "blocked"
    type_display = get_user_type_display(tgid)

    suspend_line = (
        f"⏸️ מושעה עד: {_fmt_date(suspension['suspended_until']) if suspension['suspended_until'] else 'קבוע'}\n"
        if suspension else "✅ לא מושעה\n"
    )
    status_value = v.get("status")
    if status_value == "approved":
        status_line = "🟢 מאומת\n"
    elif status_value == "blocked":
        status_line = "🚫 חסום\n"
    else:
        status_line = "🔴 לא מאומת\n"

    text = (
        f"👤 <b>{name}</b>\n"
        f"{username}"
        f"🆔 <code>{tgid}</code>\n"
        f"📅 אומת: {date}\n"
        f"🏷️ סוג: <b>{type_display}</b>\n\n"
        f"{status_line}"
        f"⚠️ אזהרות: <b>{warn_count}</b>\n"
        f"{suspend_line}"
    )

    block_btn = (
        InlineKeyboardButton("✅ שחרר חסימה", callback_data=f"VUSERS_UNBLOCK_{vid}")
        if is_blocked else
        InlineKeyboardButton("🚫 חסום",       callback_data=f"VUSERS_BLOCK_{vid}")
    )
    suspend_btn = (
        InlineKeyboardButton("🔓 בטל השעיה", callback_data=f"VUSERS_UNSUSPEND_{vid}")
        if suspension else
        InlineKeyboardButton("⏸️ השעיה",     callback_data=f"VUSERS_SUSPEND_{vid}")
    )

    keyboard_buttons = [
        [
            InlineKeyboardButton(f"⚠️ אזהרות ({warn_count})", callback_data=f"VUSERS_WARN_LIST_{vid}"),
            suspend_btn,
        ],
        [
            block_btn,
            InlineKeyboardButton("❌ בטל אימות", callback_data=f"VUSERS_REVOKE_{vid}"),
        ],
        [
            InlineKeyboardButton("🏷️ סוג משתמש", callback_data=f"VUSERS_TYPE_{vid}"),
            InlineKeyboardButton("🔐 הרשאות",    callback_data=f"VUSERS_PERMS_{vid}"),
        ],
        [
            InlineKeyboardButton("📂 קטלוגים", callback_data=f"VUSERS_CATALOGS_{vid}"),
            InlineKeyboardButton("💬 הודעה",   callback_data=f"VUSERS_MSG_{vid}"),
        ],
        [
            InlineKeyboardButton("📝 הערות",    callback_data=f"VUSERS_NOTES_{vid}"),
            InlineKeyboardButton("📜 היסטוריה", callback_data=f"VUSERS_HISTORY_{vid}"),
        ],
    ]

    keyboard_buttons.append([
        InlineKeyboardButton("💬 שיחות אימות", callback_data=f"VCHAT_LIST_{vid}"),
    ])

    keyboard_buttons.append([
        InlineKeyboardButton("🗑️ מחק תיק אימות", callback_data=f"VUSERS_DELETE_DOS_{vid}"),
    ])

    keyboard_buttons.append([
        InlineKeyboardButton("🔙 חזרה לרשימה", callback_data="VUSERS_LIST"),
    ])

    keyboard = InlineKeyboardMarkup(keyboard_buttons)

    await update.callback_query.edit_message_text(
        text=text, reply_markup=keyboard, parse_mode="HTML"
    )


# ─────────────────────────────────────────────────────────────────────────────
# סוג משתמש
# ─────────────────────────────────────────────────────────────────────────────

async def _show_type_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int
) -> None:
    v = get_verified_user_by_id(vid)
    if not v:
        await update.callback_query.answer("⚠️ משתמש לא נמצא.", show_alert=True)
        return

    current = get_user_type(v["telegram_id"])

    buttons = []
    for key, info in USER_TYPES.items():
        mark = "◉" if key == current else "○"
        buttons.append([InlineKeyboardButton(
            f"{mark} {info['emoji']} {info['label']}",
            callback_data=f"VUSERS_TYPE_SET_{vid}_{key}",
        )])

    buttons.append([InlineKeyboardButton("🔙 חזרה", callback_data=f"VUSERS_VIEW_{vid}")])

    await update.callback_query.edit_message_text(
        text=(
            f"🏷️ <b>סוג משתמש</b>\n\n"
            f"בחר סוג עבור המאומת.\n"
            f"הסוג קובע אילו קטלוגים יוצגו לו אוטומטית."
        ),
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def _execute_set_type(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int, type_key: str
) -> None:
    v = get_verified_user_by_id(vid)
    if not v:
        await update.callback_query.answer("⚠️ משתמש לא נמצא.", show_alert=True)
        return

    caller_id = update.callback_query.from_user.id
    success   = set_user_type(v["telegram_id"], type_key, assigned_by=caller_id)
    info      = USER_TYPES.get(type_key, {})

    if success:
        await update.callback_query.answer(
            f"✅ סוג עודכן: {info.get('emoji', '')} {info.get('label', type_key)}"
        )
    else:
        await update.callback_query.answer("❌ שגיאה בשמירת הסוג.", show_alert=True)

    await _show_user_view(update, context, vid)


# ─────────────────────────────────────────────────────────────────────────────
# אזהרות
# ─────────────────────────────────────────────────────────────────────────────

async def _show_warnings_list(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int
) -> None:
    print(f"[DEBUG] _show_warnings_list START vid={vid!r}")
    _clear_state(context)
    v = get_verified_user_by_id(vid)
    if not v:
        await update.callback_query.answer("⚠️ משתמש לא נמצא.", show_alert=True)
        return

    tg_id = v["telegram_id"]
    print(f"[DEBUG] _show_warnings_list calling get_warnings for telegram_id={tg_id!r}")
    try:
        warnings = get_warnings(tg_id)
        print(f"[DEBUG] _show_warnings_list DB returned {len(warnings) if warnings is not None else 0} records")
    except Exception:
        import traceback
        print("[DEBUG] _show_warnings_list DB call raised exception:")
        traceback.print_exc()
        raise

    buttons = []
    for w in warnings:
        short = w["reason"][:30] + ("…" if len(w["reason"]) > 30 else "")
        date  = _fmt_date(w["created_at"])
        # Open full warning on click
        buttons.append([
            InlineKeyboardButton(f"⚠️ {short} | {date}", callback_data=f"VUSERS_WARN_VIEW_{vid}_{w['id']}"),
            InlineKeyboardButton("🗑", callback_data=f"VUSERS_WARN_DEL_{vid}_{w['id']}"),
        ])

    buttons.append([InlineKeyboardButton("➕ הוסף אזהרה", callback_data=f"VUSERS_WARN_ADD_{vid}")])
    buttons.append([InlineKeyboardButton("🔙 חזרה",        callback_data=f"VUSERS_VIEW_{vid}")])

    print(f"[DEBUG] _show_warnings_list built keyboard with {len(buttons)} rows")
    try:
        print(f"[DEBUG] _show_warnings_list editing message text (warnings_count={len(warnings)})")
        await update.callback_query.edit_message_text(
            text=(
                f"⚠️ <b>אזהרות</b> ({len(warnings)})\n\n"
                f"{'אין אזהרות עדיין.' if not warnings else ''}"
            ),
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML",
        )
        print(f"[DEBUG] _show_warnings_list edit_message_text succeeded")
    except Exception:
        import traceback
        print("[DEBUG] _show_warnings_list edit_message_text raised exception:")
        traceback.print_exc()
        raise


async def _prompt_add_warning(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int
) -> None:
    query = update.callback_query
    context.user_data[_STATE]   = _AWAIT_WARN
    context.user_data[_VID]     = vid
    context.user_data[_CHAT_ID] = query.message.chat_id
    context.user_data[_MSG_ID]  = query.message.message_id

    await query.edit_message_text(
        text="⚠️ <b>הוספת אזהרה</b>\n\nשלח את סיבת האזהרה:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ ביטול", callback_data="VUSERS_CANCEL")],
        ]),
        parse_mode="HTML",
    )


async def _process_add_warning(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> None:
    vid     = context.user_data.pop(_VID, None)
    chat_id = context.user_data.pop(_CHAT_ID, None)
    msg_id  = context.user_data.pop(_MSG_ID, None)
    context.user_data.pop(_STATE, None)

    if not text or not vid:
        return

    v = get_verified_user_by_id(vid)
    if not v:
        return

    caller_id = update.message.from_user.id
    success   = add_warning(v["telegram_id"], text, created_by=caller_id)

    msg = (
        f"✅ <b>אזהרה נוספה</b>\n\nסיבה: {text}"
        if success else
        "❌ שגיאה בהוספת האזהרה."
    )

    # Notify the warned user immediately when the warning was saved
    if success:
        try:
            warn_count = get_warnings_count(v["telegram_id"]) or 1
            user_text = (
                f"⚠️ אזהרה {warn_count} מתוך 3\n\n"
                "קיבלת אזהרה ממנהלי המערכת.\n\n"
                "אנא הקפד לפעול בהתאם לכללי הפלטפורמה."
            )
            await context.bot.send_message(chat_id=v["telegram_id"], text=user_text)
        except Exception:
            # Do not fail the admin flow if user notification fails
            pass

    await _edit_stored(context, chat_id, msg_id, msg, _back_to_view_kb(vid))


async def _delete_warning_action(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int, wid: int
) -> None:
    delete_warning(wid)
    await update.callback_query.answer("🗑 האזהרה נמחקה.")
    await _show_warnings_list(update, context, vid)


async def _view_warning(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int, wid: int
) -> None:
    """Show full warning content and back button to warnings list."""
    v = get_verified_user_by_id(vid)
    if not v:
        await update.callback_query.answer("⚠️ משתמש לא נמצא.", show_alert=True)
        return

    w = get_warning_by_id(wid)
    if not w:
        await update.callback_query.answer("⚠️ אזהרה לא נמצאה.", show_alert=True)
        return

    text = (
        f"⚠️ <b>אזהרה</b>\n\n"
        f"{w.get('reason', '')}\n\n"
        f"<i>נרשמה בתאריך: {_fmt_date(w.get('created_at'))}</i>"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ חזרה", callback_data=f"VUSERS_WARN_LIST_{vid}")],
    ])

    await update.callback_query.edit_message_text(text=text, reply_markup=keyboard, parse_mode="HTML")


# ─────────────────────────────────────────────────────────────────────────────
# השעיות
# ─────────────────────────────────────────────────────────────────────────────

async def _show_suspend_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int
) -> None:
    _clear_state(context)
    v = get_verified_user_by_id(vid)
    if not v:
        await update.callback_query.answer("⚠️ משתמש לא נמצא.", show_alert=True)
        return

    suspension = get_active_suspension(v["telegram_id"])

    if suspension:
        until = (
            _fmt_date(suspension["suspended_until"])
            if suspension["suspended_until"] else "קבוע"
        )
        text = (
            f"⏸️ <b>המשתמש מושעה כעת</b>\n\n"
            f"עד: {until}\n"
            f"סיבה: {suspension['reason'] or 'לא צוינה'}"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔓 בטל השעיה", callback_data=f"VUSERS_UNSUSPEND_{vid}")],
            [InlineKeyboardButton("🔙 חזרה",       callback_data=f"VUSERS_VIEW_{vid}")],
        ])
    else:
        text = "⏸️ <b>השעיית משתמש</b>\n\nבחר משך השעיה:"
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("יום אחד", callback_data=f"VUSERS_SUSPEND_DO_{vid}_1d"),
                InlineKeyboardButton("שבוע",    callback_data=f"VUSERS_SUSPEND_DO_{vid}_7d"),
            ],
            [
                InlineKeyboardButton("חודש", callback_data=f"VUSERS_SUSPEND_DO_{vid}_30d"),
                InlineKeyboardButton("קבוע", callback_data=f"VUSERS_SUSPEND_DO_{vid}_perm"),
            ],
            [InlineKeyboardButton("🔙 חזרה", callback_data=f"VUSERS_VIEW_{vid}")],
        ])

    await update.callback_query.edit_message_text(
        text=text, reply_markup=keyboard, parse_mode="HTML"
    )


async def _execute_suspend(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int, dur: str
) -> None:
    v = get_verified_user_by_id(vid)
    if not v:
        await update.callback_query.answer("⚠️ משתמש לא נמצא.", show_alert=True)
        return

    caller_id = update.callback_query.from_user.id
    success   = suspend_user(v["telegram_id"], dur, created_by=caller_id)
    label     = SUSPEND_LABELS.get(dur, dur)

    if success:
        await update.callback_query.answer(f"⏸️ הושעה ל{label}.")
        try:
            await context.bot.send_message(
                chat_id=v["telegram_id"],
                text=(
                    f"⏸️ <b>חשבונך הושעה.</b>\n\n"
                    f"משך: <b>{label}</b>\n\n"
                    f"לפרטים נוספים פנה למנהל המערכת."
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass
    else:
        await update.callback_query.answer("❌ שגיאה בהשעיה.", show_alert=True)

    await _show_user_view(update, context, vid)


async def _execute_unsuspend(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int
) -> None:
    v = get_verified_user_by_id(vid)
    if not v:
        await update.callback_query.answer("⚠️ משתמש לא נמצא.", show_alert=True)
        return

    lift_suspension(v["telegram_id"])
    await update.callback_query.answer("🔓 ההשעיה בוטלה.")
    try:
        await context.bot.send_message(
            chat_id=v["telegram_id"],
            text=(
                "🔓 <b>ההשעיה שלך בוטלה.</b>\n\n"
                "אתה יכול להמשיך להשתמש במערכת."
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await _show_user_view(update, context, vid)


# ─────────────────────────────────────────────────────────────────────────────
# חסימה / שחרור
# ─────────────────────────────────────────────────────────────────────────────

async def _confirm_block(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int
) -> None:
    v = get_verified_user_by_id(vid)
    if not v:
        await update.callback_query.answer("⚠️ משתמש לא נמצא.", show_alert=True)
        return
    name = v["full_name"] or v.get("username") or str(v["telegram_id"])

    await update.callback_query.edit_message_text(
        text=(
            f"🚫 <b>אישור חסימה</b>\n\n"
            f"משתמש: <b>{name}</b>\n\n"
            f"פעולה זו תחסום את המשתמש לחלוטין.\n"
            f"האם להמשיך?"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ כן, חסום", callback_data=f"VUSERS_BLOCK_CONFIRM_{vid}")],
            [InlineKeyboardButton("❌ ביטול",    callback_data=f"VUSERS_VIEW_{vid}")],
        ]),
        parse_mode="HTML",
    )


async def _execute_block(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int
) -> None:
    v         = get_verified_user_by_id(vid)
    caller_id = update.callback_query.from_user.id
    success   = block_verified_user(vid, performed_by=caller_id)
    await update.callback_query.answer(
        "🚫 המשתמש נחסם." if success else "❌ שגיאה.", show_alert=not success
    )
    if success and v:
        try:
            await context.bot.send_message(
                chat_id=v["telegram_id"],
                text=(
                    "🚫 <b>חשבונך נחסם.</b>\n\n"
                    "לפרטים נוספים פנה למנהל המערכת."
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass
    await _show_user_view(update, context, vid)


async def _confirm_unblock(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int
) -> None:
    await update.callback_query.edit_message_text(
        text="✅ <b>שחרור חסימה</b>\n\nהאם לשחרר את חסימת המשתמש?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ כן, שחרר", callback_data=f"VUSERS_UNBLOCK_CONFIRM_{vid}")],
            [InlineKeyboardButton("❌ ביטול",    callback_data=f"VUSERS_VIEW_{vid}")],
        ]),
        parse_mode="HTML",
    )


async def _execute_unblock(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int
) -> None:
    v         = get_verified_user_by_id(vid)
    caller_id = update.callback_query.from_user.id
    success   = unblock_verified_user(vid, performed_by=caller_id)
    await update.callback_query.answer(
        "✅ החסימה שוחררה." if success else "❌ שגיאה.", show_alert=not success
    )
    if success and v:
        try:
            await context.bot.send_message(
                chat_id=v["telegram_id"],
                text=(
                    "✅ <b>חסימתך שוחררה.</b>\n\n"
                    "אתה יכול להמשיך להשתמש במערכת."
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass
    await _show_user_view(update, context, vid)


# ─────────────────────────────────────────────────────────────────────────────
# הרשאות כלליות
# ─────────────────────────────────────────────────────────────────────────────

async def _show_permissions(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int
) -> None:
    v = get_verified_user_by_id(vid)
    if not v:
        await update.callback_query.answer("⚠️ משתמש לא נמצא.", show_alert=True)
        return

    tgid          = v["telegram_id"]
    current_perms = set(get_user_general_permissions(tgid))

    buttons = []
    for perm in USER_PERMISSIONS:
        key   = perm["key"]
        label = perm["label"]
        icon  = "✅" if key in current_perms else "❌"
        buttons.append([InlineKeyboardButton(
            f"{icon} {label}",
            callback_data=f"VUSERS_PERM_TOGGLE_{vid}_{key}",
        )])

    buttons.append([InlineKeyboardButton("🔙 חזרה", callback_data=f"VUSERS_VIEW_{vid}")])

    await update.callback_query.edit_message_text(
        text=(
            f"🔐 <b>הרשאות כלליות</b>\n"
            f"🆔 <code>{tgid}</code>\n\n"
            f"✅ פעיל  |  ❌ כבוי\n"
            f"<i>לחץ להפעיל / לבטל.</i>"
        ),
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def _toggle_general_permission(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int, key: str
) -> None:
    v = get_verified_user_by_id(vid)
    if not v:
        await update.callback_query.answer("⚠️ משתמש לא נמצא.", show_alert=True)
        return

    tgid          = v["telegram_id"]
    caller_id     = update.callback_query.from_user.id
    current_perms = set(get_user_general_permissions(tgid))

    if key in current_perms:
        revoke_general_permission(tgid, key)
        await update.callback_query.answer(f"❌ הוסרה: {key}")
    else:
        grant_general_permission(tgid, key, granted_by=caller_id)
        await update.callback_query.answer(f"✅ הופעלה: {key}")

    await _show_permissions(update, context, vid)


# ─────────────────────────────────────────────────────────────────────────────
# קטלוגים per-user
# ─────────────────────────────────────────────────────────────────────────────

async def _show_user_catalogs(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int
) -> None:
    v = get_verified_user_by_id(vid)
    if not v:
        await update.callback_query.answer("⚠️ משתמש לא נמצא.", show_alert=True)
        return

    tgid        = v["telegram_id"]
    auto_cats   = get_auto_catalogs_for_user(tgid)
    custom_cats = get_custom_catalogs()
    user_slugs  = get_user_catalog_slugs(tgid)

    lines = []

    # קטלוגים אוטומטיים — תצוגה בלבד
    if auto_cats:
        lines.append("🔄 <b>אוטומטי לפי סוג:</b>")
        for cat in auto_cats:
            tags = " ".join(filter(None, [
                "📢" if cat.get("is_publishable") else "",
                "👁"  if cat.get("is_readonly")    else "",
            ]))
            lines.append(f"  ✅ {cat['name']}{(' ' + tags) if tags else ''}")
        lines.append("")

    # קטלוגים ידניים — ניתנים לtoggle
    buttons = []
    if custom_cats:
        lines.append("<b>הקצאה ידנית:</b>  ✅ פעיל | ❌ כבוי")
        for cat in custom_cats:
            slug = cat["slug"]
            name = cat["name"]
            tags = " ".join(filter(None, [
                "📢" if cat.get("is_publishable") else "",
                "👁"  if cat.get("is_readonly")    else "",
            ]))
            icon = "✅" if slug in user_slugs else "❌"
            buttons.append([InlineKeyboardButton(
                f"{icon} {name}{(' ' + tags) if tags else ''}",
                callback_data=f"VUSERS_CAT_TOGGLE_{vid}_{slug}",
            )])

    if not auto_cats and not custom_cats:
        lines.append("אין קטלוגים פעילים במערכת.\n<i>הוסף קטלוגים דרך ניהול קטלוגים.</i>")

    buttons.append([InlineKeyboardButton("🔙 חזרה", callback_data=f"VUSERS_VIEW_{vid}")])

    await update.callback_query.edit_message_text(
        text=(
            f"📂 <b>קטלוגים</b>\n"
            f"🆔 <code>{tgid}</code>\n\n"
            + "\n".join(lines)
        ),
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def _toggle_catalog_action(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int, slug: str
) -> None:
    v = get_verified_user_by_id(vid)
    if not v:
        await update.callback_query.answer("⚠️ משתמש לא נמצא.", show_alert=True)
        return

    tgid      = v["telegram_id"]
    caller_id = update.callback_query.from_user.id
    granted   = toggle_catalog_permission(tgid, slug, granted_by=caller_id)

    await update.callback_query.answer(
        f"✅ הופעל: {slug}" if granted else f"❌ בוטל: {slug}"
    )
    await _show_user_catalogs(update, context, vid)


# ─────────────────────────────────────────────────────────────────────────────
# ניהול קטלוגים (כללי)
# ─────────────────────────────────────────────────────────────────────────────

async def _show_catalog_manager(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    _clear_state(context)
    catalogs = get_all_catalogs()

    buttons = []
    for cat in catalogs:
        aud_label = CATALOG_AUDIENCES.get(cat.get("audience", "custom"), "?")
        tags      = " ".join(filter(None, [
            "📢" if cat.get("is_publishable") else "",
            "👁"  if cat.get("is_readonly")    else "",
        ]))
        buttons.append([InlineKeyboardButton(
            f"📂 {cat['name']}  [{aud_label}]{(' ' + tags) if tags else ''}",
            callback_data=f"VUSERS_CATMGR_EDIT_{cat['id']}",
        )])

    buttons.append([InlineKeyboardButton("➕ קטלוג חדש", callback_data="VUSERS_CATMGR_NEW")])
    buttons.append([InlineKeyboardButton("🔙 חזרה",       callback_data="VUSERS_LIST")])

    await update.callback_query.edit_message_text(
        text=(
            f"📂 <b>ניהול קטלוגים</b> ({len(catalogs)})\n\n"
            f"לחץ על קטלוג לעריכה, או הוסף חדש."
        ),
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def _prompt_new_catalog(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    context.user_data[_STATE]   = _AWAIT_CAT_NAME
    context.user_data[_CHAT_ID] = query.message.chat_id
    context.user_data[_MSG_ID]  = query.message.message_id

    await query.edit_message_text(
        text="📂 <b>קטלוג חדש</b>\n\nשלח את <b>שם הקטלוג</b>:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ ביטול", callback_data="VUSERS_CANCEL")],
        ]),
        parse_mode="HTML",
    )


async def _process_new_catalog(
    update: Update, context: ContextTypes.DEFAULT_TYPE, name: str
) -> None:
    chat_id = context.user_data.pop(_CHAT_ID, None)
    msg_id  = context.user_data.pop(_MSG_ID, None)
    context.user_data.pop(_STATE, None)

    if not name:
        return

    cat_id = create_catalog(name=name, audience="custom")

    if cat_id:
        msg = f"✅ <b>קטלוג נוצר:</b> {name}\n\nעדכן הגדרות:"
        kb  = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚙️ עריכת הגדרות",  callback_data=f"VUSERS_CATMGR_EDIT_{cat_id}")],
            [InlineKeyboardButton("🔙 לרשימת קטלוגים", callback_data="VUSERS_CATMGR")],
        ])
    else:
        msg = "❌ שגיאה ביצירת הקטלוג. ייתכן שהשם כבר קיים."
        kb  = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 לרשימת קטלוגים", callback_data="VUSERS_CATMGR")],
        ])

    await _edit_stored(context, chat_id, msg_id, msg, kb)


async def _show_catalog_edit(
    update: Update, context: ContextTypes.DEFAULT_TYPE, cid: int
) -> None:
    _clear_state(context)
    cat = get_catalog_by_id(cid)
    if not cat:
        await update.callback_query.answer("⚠️ קטלוג לא נמצא.", show_alert=True)
        return

    audience       = cat.get("audience", "custom")
    is_publishable = bool(cat.get("is_publishable"))
    is_readonly    = bool(cat.get("is_readonly"))

    aud_label = CATALOG_AUDIENCES.get(audience, audience)
    pub_icon  = "✅" if is_publishable else "❌"
    ro_icon   = "✅" if is_readonly    else "❌"

    # כפתורי בחירת קהל יעד — שני עמודות
    aud_buttons = []
    row = []
    for key, label in CATALOG_AUDIENCES.items():
        mark = "◉" if key == audience else "○"
        row.append(InlineKeyboardButton(
            f"{mark} {label}",
            callback_data=f"VUSERS_CATMGR_AUD_{cid}_{key}",
        ))
        if len(row) == 2:
            aud_buttons.append(row)
            row = []
    if row:
        aud_buttons.append(row)

    keyboard = InlineKeyboardMarkup([
        *aud_buttons,
        [
            InlineKeyboardButton(f"{pub_icon} לפרסום",      callback_data=f"VUSERS_CATMGR_PUB_{cid}"),
            InlineKeyboardButton(f"{ro_icon} צפייה בלבד",   callback_data=f"VUSERS_CATMGR_RO_{cid}"),
        ],
        [InlineKeyboardButton("🗑 מחק קטלוג", callback_data=f"VUSERS_CATMGR_DEL_{cid}")],
        [InlineKeyboardButton("🔙 חזרה",       callback_data="VUSERS_CATMGR")],
    ])

    await update.callback_query.edit_message_text(
        text=(
            f"📂 <b>{cat['name']}</b>\n"
            f"<code>{cat['slug']}</code>\n\n"
            f"👥 קהל יעד: <b>{aud_label}</b>\n"
            f"📢 לפרסום: <b>{'כן' if is_publishable else 'לא'}</b>\n"
            f"👁 צפייה בלבד: <b>{'כן' if is_readonly else 'לא'}</b>\n\n"
            f"<i>לחץ על ◉/○ לשינוי קהל יעד.</i>"
        ),
        reply_markup=keyboard,
        parse_mode="HTML",
    )


async def _set_catalog_audience(
    update: Update, context: ContextTypes.DEFAULT_TYPE, cid: int, audience: str
) -> None:
    success = update_catalog(cid, audience=audience)
    label   = CATALOG_AUDIENCES.get(audience, audience)
    await update.callback_query.answer(
        f"✅ קהל יעד: {label}" if success else "❌ שגיאה.", show_alert=not success
    )
    await _show_catalog_edit(update, context, cid)


async def _toggle_catalog_publishable(
    update: Update, context: ContextTypes.DEFAULT_TYPE, cid: int
) -> None:
    cat = get_catalog_by_id(cid)
    if not cat:
        await update.callback_query.answer("⚠️ קטלוג לא נמצא.", show_alert=True)
        return
    new_val = not bool(cat.get("is_publishable"))
    update_catalog(cid, is_publishable=new_val)
    await update.callback_query.answer("📢 לפרסום: " + ("כן" if new_val else "לא"))
    await _show_catalog_edit(update, context, cid)


async def _toggle_catalog_readonly(
    update: Update, context: ContextTypes.DEFAULT_TYPE, cid: int
) -> None:
    cat = get_catalog_by_id(cid)
    if not cat:
        await update.callback_query.answer("⚠️ קטלוג לא נמצא.", show_alert=True)
        return
    new_val = not bool(cat.get("is_readonly"))
    update_catalog(cid, is_readonly=new_val)
    await update.callback_query.answer("👁 צפייה בלבד: " + ("כן" if new_val else "לא"))
    await _show_catalog_edit(update, context, cid)


async def _confirm_delete_catalog(
    update: Update, context: ContextTypes.DEFAULT_TYPE, cid: int
) -> None:
    cat = get_catalog_by_id(cid)
    if not cat:
        await update.callback_query.answer("⚠️ קטלוג לא נמצא.", show_alert=True)
        return

    await update.callback_query.edit_message_text(
        text=(
            f"🗑 <b>מחיקת קטלוג</b>\n\n"
            f"שם: <b>{cat['name']}</b>\n\n"
            f"פעולה זו תסיר את הקטלוג מהמערכת.\n"
            f"האם להמשיך?"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ כן, מחק", callback_data=f"VUSERS_CATMGR_DEL_OK_{cid}")],
            [InlineKeyboardButton("❌ ביטול",   callback_data=f"VUSERS_CATMGR_EDIT_{cid}")],
        ]),
        parse_mode="HTML",
    )


async def _execute_delete_catalog(
    update: Update, context: ContextTypes.DEFAULT_TYPE, cid: int
) -> None:
    success = delete_catalog(cid)
    await update.callback_query.answer(
        "✅ הקטלוג נמחק." if success else "❌ שגיאה.", show_alert=not success
    )
    await _show_catalog_manager(update, context)


# ─────────────────────────────────────────────────────────────────────────────
# שליחת הודעה
# ─────────────────────────────────────────────────────────────────────────────

async def _prompt_send_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int
) -> None:
    query = update.callback_query
    context.user_data[_STATE]   = _AWAIT_MSG
    context.user_data[_VID]     = vid
    context.user_data[_CHAT_ID] = query.message.chat_id
    context.user_data[_MSG_ID]  = query.message.message_id

    await query.edit_message_text(
        text="💬 <b>שליחת הודעה</b>\n\nכתוב את ההודעה שברצונך לשלוח:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ ביטול", callback_data="VUSERS_CANCEL")],
        ]),
        parse_mode="HTML",
    )


async def _process_send_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> None:
    vid     = context.user_data.pop(_VID, None)
    chat_id = context.user_data.pop(_CHAT_ID, None)
    msg_id  = context.user_data.pop(_MSG_ID, None)
    context.user_data.pop(_STATE, None)

    if not text or not vid:
        return

    v = get_verified_user_by_id(vid)
    if not v:
        return

    caller_id = update.message.from_user.id

    try:
        await context.bot.send_message(chat_id=v["telegram_id"], text=text)
        log_message(v["telegram_id"], text, sent_by=caller_id)
        msg = "✅ <b>ההודעה נשלחה בהצלחה.</b>"
    except Exception as exc:
        logger.error("send_message to %s failed: %s", v["telegram_id"], exc)
        msg = f"❌ שגיאה בשליחת ההודעה:\n<code>{exc}</code>"

    await _edit_stored(context, chat_id, msg_id, msg, _back_to_view_kb(vid))


# ─────────────────────────────────────────────────────────────────────────────
# הערות מנהל
# ─────────────────────────────────────────────────────────────────────────────

async def _show_notes_list(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int
) -> None:
    print(f"[DEBUG] _show_notes_list START vid={vid!r}")
    _clear_state(context)
    v = get_verified_user_by_id(vid)
    if not v:
        await update.callback_query.answer("⚠️ משתמש לא נמצא.", show_alert=True)
        return

    tg_id = v["telegram_id"]
    print(f"[DEBUG] _show_notes_list calling get_admin_notes for telegram_id={tg_id!r}")
    try:
        notes = get_admin_notes(tg_id)
        print(f"[DEBUG] _show_notes_list DB returned {len(notes) if notes is not None else 0} records")
    except Exception as exc:
        import traceback
        print("[DEBUG] _show_notes_list DB call raised exception:")
        traceback.print_exc()
        raise

    # build display text
    text = (
        f"📝 <b>הערות מנהל</b> ({len(notes)})\n\n"
        f"{'אין הערות עדיין.' if not notes else ''}"
    )
    print(f"[DEBUG] _show_notes_list built text (length={len(text)})")

    buttons = []
    for n in notes:
        short = n["note"][:30] + ("…" if len(n["note"]) > 30 else "")
        date  = _fmt_date(n["created_at"])
        # Open full note on click
        buttons.append([
            InlineKeyboardButton(f"📝 {short} | {date}", callback_data=f"VUSERS_NOTE_VIEW_{vid}_{n['id']}"),
            InlineKeyboardButton("🗑", callback_data=f"VUSERS_NOTE_DEL_{vid}_{n['id']}"),
        ])

    buttons.append([InlineKeyboardButton("➕ הוסף הערה", callback_data=f"VUSERS_NOTE_ADD_{vid}")])
    buttons.append([InlineKeyboardButton("🔙 חזרה",      callback_data=f"VUSERS_VIEW_{vid}")])

    print(f"[DEBUG] _show_notes_list built keyboard with {len(buttons)} rows")
    try:
        print(f"[DEBUG] _show_notes_list before edit_message_text (notes_count={len(notes)})")
        await update.callback_query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML",
        )
        print(f"[DEBUG] _show_notes_list edit_message_text succeeded")
    except Exception:
        import traceback
        print("[DEBUG] _show_notes_list edit_message_text raised exception:")
        traceback.print_exc()
        raise

async def _prompt_add_note(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int
) -> None:
    query = update.callback_query
    context.user_data[_STATE]   = _AWAIT_NOTE
    context.user_data[_VID]     = vid
    context.user_data[_CHAT_ID] = query.message.chat_id
    context.user_data[_MSG_ID]  = query.message.message_id

    await query.edit_message_text(
        text="📝 <b>הוספת הערה</b>\n\nכתוב את ההערה הפנימית:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ ביטול", callback_data="VUSERS_CANCEL")],
        ]),
        parse_mode="HTML",
    )


async def _process_add_note(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> None:
    vid     = context.user_data.pop(_VID, None)
    chat_id = context.user_data.pop(_CHAT_ID, None)
    msg_id  = context.user_data.pop(_MSG_ID, None)
    context.user_data.pop(_STATE, None)

    if not text or not vid:
        return

    v = get_verified_user_by_id(vid)
    if not v:
        return

    caller_id = update.message.from_user.id
    success   = add_admin_note(v["telegram_id"], text, created_by=caller_id)

    msg = "✅ <b>ההערה נשמרה.</b>" if success else "❌ שגיאה בשמירת ההערה."
    await _edit_stored(context, chat_id, msg_id, msg, _back_to_view_kb(vid))


async def _delete_note_action(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int, nid: int
) -> None:
    delete_admin_note(nid)
    await update.callback_query.answer("🗑 ההערה נמחקה.")
    await _show_notes_list(update, context, vid)


# ─────────────────────────────────────────────────────────────────────────────
# היסטוריית פעולות
# ─────────────────────────────────────────────────────────────────────────────

async def _show_history(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int
) -> None:
    _clear_state(context)
    v = get_verified_user_by_id(vid)
    if not v:
        await update.callback_query.answer("⚠️ משתמש לא נמצא.", show_alert=True)
        return

    events = get_user_history(v["telegram_id"], limit=25)

    if not events:
        body = "אין פעולות רשומות עדיין."
    else:
        lines = []
        for e in events:
            date = e["created_at"][:10] if e["created_at"] else ""
            lines.append(f"{e['icon']} {e['label']} <i>({date})</i>")
        body = "\n".join(lines)

    await update.callback_query.edit_message_text(
        text=f"📜 <b>היסטוריית פעולות</b>\n\n{body}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 חזרה", callback_data=f"VUSERS_VIEW_{vid}")],
        ]),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────────────────────────────────────
# ביטול אימות
# ─────────────────────────────────────────────────────────────────────────────

async def _confirm_revoke(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int
) -> None:
    v = get_verified_user_by_id(vid)
    if not v:
        await update.callback_query.answer("⚠️ משתמש לא נמצא.", show_alert=True)
        return
    name = v["full_name"] or v.get("username") or str(v["telegram_id"])

    await update.callback_query.edit_message_text(
        text=(
            f"❌ <b>ביטול אימות</b>\n\n"
            f"משתמש: <b>{name}</b>\n\n"
            f"פעולה זו תבטל את מעמד המאומת ותחזיר את הסטטוס ל-<b>נדחה</b>.\n"
            f"האם להמשיך?"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ כן, בטל אימות", callback_data=f"VUSERS_REVOKE_CONFIRM_{vid}")],
            [InlineKeyboardButton("❌ ביטול",         callback_data=f"VUSERS_VIEW_{vid}")],
        ]),
        parse_mode="HTML",
    )


async def _execute_revoke(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int
) -> None:
    v         = get_verified_user_by_id(vid)
    caller_id = update.callback_query.from_user.id
    success   = revoke_verification(vid, performed_by=caller_id)

    if success:
        if v:
            try:
                await context.bot.send_message(
                    chat_id=v["telegram_id"],
                    text=(
                        "❌ <b>האימות שלך בוטל.</b>\n\n"
                        "ניתן להגיש בקשת אימות חדשה דרך המערכת."
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass
        msg      = "✅ <b>האימות בוטל.</b>\n\nהמשתמש הוחזר לסטטוס נדחה."
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 חזרה לרשימה", callback_data="VUSERS_LIST")],
        ])
    else:
        msg      = "❌ שגיאה בביטול האימות."
        keyboard = _back_to_view_kb(vid)

    await update.callback_query.edit_message_text(
        text=msg, reply_markup=keyboard, parse_mode="HTML"
    )


# ─────────────────────────────────────────────────────────────────────────────
# מחיקת תיק אימות
# ─────────────────────────────────────────────────────────────────────────────

async def _confirm_delete_dossier(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int
) -> None:
    v = get_verified_user_by_id(vid)
    if not v:
        await update.callback_query.answer("⚠️ משתמש לא נמצא.", show_alert=True)
        return
    name = v["full_name"] or v.get("username") or str(v["telegram_id"])

    await update.callback_query.edit_message_text(
        text=(
            f"🗑️ <b>מחיקת תיק אימות</b>\n\n"
            f"משתמש: <b>{name}</b>\n\n"
            f"פעולה זו תמחק:\n"
            f"• כל רשומות האימות של המשתמש\n"
            f"• כל שיחות האימות\n"
            f"• כל הודעות שיחות האימות\n\n"
            f"<b>המשתמש עצמו לא יימחק</b> והוא יוכל להתחיל אימות חדש.\n\n"
            f"האם להמשיך?"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ כן, מחק תיק", callback_data=f"VUSERS_DELETE_DOS_CONFIRM_{vid}")],
            [InlineKeyboardButton("❌ ביטול",         callback_data=f"VUSERS_VIEW_{vid}")],
        ]),
        parse_mode="HTML",
    )


async def _execute_delete_dossier(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int
) -> None:
    v = get_verified_user_by_id(vid)
    if not v:
        await update.callback_query.answer("⚠️ משתמש לא נמצא.", show_alert=True)
        return
    
    telegram_id = v["telegram_id"]
    
    try:
        success = delete_verification_dossier(telegram_id)
        
        if success:
            msg = (
                "✅ <b>תיק האימות נמחק.</b>\n\n"
                f"כל הרשומות, שיחות והודעות של המשתמש נמחקו.\n"
                f"המשתמש עדיין קיים במערכת ויכול להגיש בקשת אימות חדשה."
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 חזרה לרשימה", callback_data="VUSERS_LIST")],
            ])
        else:
            msg      = "❌ שגיאה במחיקת תיק האימות."
            keyboard = _back_to_view_kb(vid)
    except Exception as exc:
        logger.exception("_execute_delete_dossier failed for telegram_id=%s: %s", telegram_id, exc)
        msg      = f"❌ שגיאה: {exc}"
        keyboard = _back_to_view_kb(vid)

    await update.callback_query.edit_message_text(
        text=msg, reply_markup=keyboard, parse_mode="HTML"
    )


# ─────────────────────────────────────────────────────────────────────────────
# ביטול קלט
# ─────────────────────────────────────────────────────────────────────────────

async def _cancel_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    vid = context.user_data.get(_VID)
    _clear_state(context)
    if vid:
        await _show_user_view(update, context, vid)
    else:
        await _show_users_list(update, context)


# ─────────────────────────────────────────────────────────────────────────────
# פונקציות עזר
# ─────────────────────────────────────────────────────────────────────────────

def _clear_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in (_STATE, _VID, _CID, _CHAT_ID, _MSG_ID, _VCHAT_VID, _VCHAT_ID):
        context.user_data.pop(key, None)


def _fmt_date(ts) -> str:
    if not ts:
        return "-"
    try:
        return f"{ts[8:10]}.{ts[5:7]}.{ts[:4]}"
    except Exception:
        return str(ts)


# ─────────────────────────────────────────────────────────────────────────────
# שיחות אימות
# ─────────────────────────────────────────────────────────────────────────────

def _build_chat_view(vid: int, chat_id: int):
    """בונה (text, keyboard) לתצוגת שיחה."""
    v    = get_verified_user_by_id(vid)
    chat = get_verification_chat(chat_id)
    if not v or not chat:
        return "⚠️ שיחה לא נמצאה.", InlineKeyboardMarkup([[]])

    messages = get_verification_chat_messages(chat_id)
    name     = v["full_name"] or str(v["telegram_id"])

    lines = [f"💬 <b>שיחה עם {name}</b>"]
    if not chat["is_open"]:
        lines.append("🔴 השיחה סגורה")
    lines.append("")

    media_buttons = []
    for msg in messages[-20:]:
        role = "👤 משתמש" if msg["sender_role"] == "user" else "🛡 אדמין"
        mtype = msg["message_type"]
        if mtype == "text":
            txt = (msg.get("content_text") or "")
            if len(txt) > 80:
                txt = txt[:77] + "..."
            lines.append(f"<b>{role}:</b> {txt}")
        elif mtype == "photo":
            lines.append(f"<b>{role}:</b> 📷 תמונה")
            media_buttons.append([InlineKeyboardButton(
                f"📷 הצג ({msg['id']})",
                callback_data=f"VCHAT_MEDIA_{vid}_{chat_id}_{msg['id']}",
            )])
        elif mtype == "video":
            lines.append(f"<b>{role}:</b> 🎥 סרטון")
            media_buttons.append([InlineKeyboardButton(
                f"🎥 הצג ({msg['id']})",
                callback_data=f"VCHAT_MEDIA_{vid}_{chat_id}_{msg['id']}",
            )])
        elif mtype == "document":
            lines.append(f"<b>{role}:</b> 📎 מסמך")

    if not messages:
        lines.append("אין הודעות עדיין.")

    action_rows = []
    if chat["is_open"]:
        action_rows.append([
            InlineKeyboardButton("✉️ שלח הודעה", callback_data=f"VCHAT_SEND_{vid}_{chat_id}"),
            InlineKeyboardButton("🔒 סגור שיחה", callback_data=f"VCHAT_CLOSE_{vid}_{chat_id}"),
        ])

    keyboard = InlineKeyboardMarkup(
        action_rows + media_buttons + [[InlineKeyboardButton("🔙 חזרה", callback_data=f"VCHAT_LIST_{vid}")]]
    )
    return "\n".join(lines), keyboard


async def _show_verification_chats(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int
) -> None:
    _clear_state(context)
    v = get_verified_user_by_id(vid)
    if not v:
        await update.callback_query.answer("⚠️ משתמש לא נמצא.", show_alert=True)
        return

    chats = get_user_verification_chats(v["telegram_id"])
    name  = v["full_name"] or str(v["telegram_id"])

    buttons = []
    for chat in reversed(chats):
        status = "🟢" if chat["is_open"] else "🔴"
        date   = _fmt_date(chat["created_at"])
        buttons.append([InlineKeyboardButton(
            f"{status} שיחה מ-{date}",
            callback_data=f"VCHAT_VIEW_{vid}_{chat['id']}",
        )])

    buttons.append([InlineKeyboardButton("💬 פתח שיחה חדשה", callback_data=f"VCHAT_OPEN_{vid}")])
    buttons.append([InlineKeyboardButton("🔙 חזרה לפרופיל",  callback_data=f"VUSERS_VIEW_{vid}")])

    await update.callback_query.edit_message_text(
        text=(
            f"💬 <b>שיחות אימות</b>\n<b>{name}</b>\n\n"
            + ("בחר שיחה:" if chats else "אין שיחות עדיין.")
        ),
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def _open_verification_chat(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int
) -> None:
    v = get_verified_user_by_id(vid)
    if not v:
        await update.callback_query.answer("⚠️ משתמש לא נמצא.", show_alert=True)
        return

    admin_id = update.callback_query.from_user.id
    chat_id  = create_verification_chat(v["telegram_id"], vid, admin_id)
    if not chat_id:
        await update.callback_query.answer("❌ שגיאה בפתיחת שיחה.", show_alert=True)
        return

    try:
        await context.bot.send_message(
            chat_id=v["telegram_id"],
            text=(
                "🛡️ <b>מרכז האימות</b>\n\n"
                "שלום,\n"
                "ערוץ התקשורת המאובטח שלך עם צוות האימות הופעל.\n\n"
                "כעת ניתן להעביר הודעות, מסמכים וקבצים עד לסיום הטיפול.\n\n"
                "✨ אנו זמינים עבורך לאורך תהליך האימות.\n\n"
                "🔐 צוות האימות"
            ),
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.exception("_open_verification_chat notify user failed (vid=%s, chat_id=%s): %s", vid, chat_id, exc)
        close_verification_chat(chat_id)
        await update.callback_query.answer("❌ פתיחת השיחה נכשלה: לא ניתן לשלוח הודעת פתיחה למשתמש.", show_alert=True)
        return

    add_verification_chat_message(chat_id, "admin", "text", content_text="💬 שיחה נפתחה.")

    text, keyboard = _build_chat_view(vid, chat_id)
    await update.callback_query.edit_message_text(text=text, reply_markup=keyboard, parse_mode="HTML")


async def _show_chat_messages(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int, chat_id: int
) -> None:
    _clear_state(context)
    text, keyboard = _build_chat_view(vid, chat_id)
    await update.callback_query.edit_message_text(text=text, reply_markup=keyboard, parse_mode="HTML")


async def _prompt_send_chat_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int, chat_id: int
) -> None:
    context.user_data[_STATE]     = _AWAIT_CHAT_MSG
    context.user_data[_VCHAT_VID] = vid
    context.user_data[_VCHAT_ID]  = chat_id
    context.user_data[_CHAT_ID]   = update.callback_query.message.chat_id
    context.user_data[_MSG_ID]    = update.callback_query.message.message_id

    await update.callback_query.edit_message_text(
        text="✉️ <b>שלח הודעה למשתמש</b>\n\nכתוב את ההודעה:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ ביטול", callback_data=f"VCHAT_VIEW_{vid}_{chat_id}"),
        ]]),
        parse_mode="HTML",
    )


async def _process_send_chat_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> None:
    vid       = context.user_data.get(_VCHAT_VID)
    chat_id   = context.user_data.get(_VCHAT_ID)
    tg_chat   = context.user_data.get(_CHAT_ID)
    msg_id    = context.user_data.get(_MSG_ID)
    _clear_state(context)

    if not vid or not chat_id:
        return

    v = get_verified_user_by_id(vid)
    if not v:
        return

    add_verification_chat_message(chat_id, "admin", "text", content_text=text)

    try:
        await context.bot.send_message(
            chat_id=v["telegram_id"],
            text=f"💬 <b>הודעה מנציג:</b>\n\n{text}",
            parse_mode="HTML",
        )
    except Exception:
        pass

    chat_text, keyboard = _build_chat_view(vid, chat_id)
    try:
        await context.bot.edit_message_text(
            chat_id=tg_chat,
            message_id=msg_id,
            text=chat_text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    except Exception:
        await context.bot.send_message(
            chat_id=tg_chat,
            text=chat_text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )


async def _show_chat_media(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int, chat_id: int, msg_id: int
) -> None:
    msg = get_verification_chat_message(msg_id)
    if not msg or not msg.get("file_id"):
        await update.callback_query.answer("⚠️ מדיה לא נמצאה.", show_alert=True)
        return

    back_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ חזור", callback_data=f"VCHAT_MEDIA_BACK_{vid}_{chat_id}"),
    ]])

    if msg["message_type"] == "photo":
        await context.bot.send_photo(
            chat_id=update.callback_query.message.chat_id,
            photo=msg["file_id"],
            caption="📷 תמונה מהשיחה",
            reply_markup=back_kb,
        )
    elif msg["message_type"] == "video":
        await context.bot.send_video(
            chat_id=update.callback_query.message.chat_id,
            video=msg["file_id"],
            caption="🎥 סרטון מהשיחה",
            reply_markup=back_kb,
        )


async def _back_from_chat_media(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int, chat_id: int
) -> None:
    """מוחק את הודעת המדיה ושולח מחדש את מסך השיחה."""
    try:
        await update.callback_query.message.delete()
    except Exception:
        pass

    chat_text, keyboard = _build_chat_view(vid, chat_id)
    await context.bot.send_message(
        chat_id=update.callback_query.message.chat_id,
        text=chat_text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


async def _confirm_close_chat(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int, chat_id: int
) -> None:
    await update.callback_query.edit_message_text(
        text="🔒 <b>סגירת שיחה</b>\n\nהאם לסגור את השיחה?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ כן, סגור", callback_data=f"VCHAT_CLOSE_OK_{vid}_{chat_id}")],
            [InlineKeyboardButton("❌ ביטול",     callback_data=f"VCHAT_VIEW_{vid}_{chat_id}")],
        ]),
        parse_mode="HTML",
    )


async def _execute_close_chat(
    update: Update, context: ContextTypes.DEFAULT_TYPE, vid: int, chat_id: int
) -> None:
    v = get_verified_user_by_id(vid)
    chat = get_verification_chat(chat_id)
    if not chat:
        await update.callback_query.answer("⚠️ שיחה לא נמצאה.", show_alert=True)
        return

    if not close_verification_chat(chat_id):
        await update.callback_query.answer("❌ שגיאה בסגירת השיחה.", show_alert=True)
        return

    # ודא שאין שיחות פתוחות נוספות לאותו אימות
    if v:
        chats = get_user_verification_chats(v["telegram_id"])
        for c in chats:
            if c.get("verification_id") == vid and c.get("is_open"):
                close_verification_chat(c["id"])

    if v:
        try:
            await context.bot.send_message(
                chat_id=v["telegram_id"],
                text=(
                    "🛡️ <b>מרכז האימות</b>\n\n"
                    "הטיפול בפנייה הסתיים וערוץ התקשורת נסגר.\n\n"
                    "במידת הצורך, צוות האימות ייצור איתך קשר מחדש.\n\n"
                    "🙏 תודה על שיתוף הפעולה.\n\n"
                    "🔐 צוות האימות"
                ),
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.exception("_execute_close_chat notify user failed (vid=%s, chat_id=%s): %s", vid, chat_id, exc)
            await update.callback_query.answer("⚠️ השיחה נסגרה, אך הודעת הסגירה למשתמש לא נשלחה.", show_alert=True)

    await update.callback_query.edit_message_text(
        text="✅ <b>השיחה נסגרה.</b>",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 חזרה לשיחות", callback_data=f"VCHAT_LIST_{vid}"),
        ]]),
        parse_mode="HTML",
    )


async def handle_verification_chat_user_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """מטפל בהודעת משתמש כשיש לו שיחה פתוחה. מחזיר True אם ההודעה טופלה."""
    user_id = update.message.from_user.id
    chats   = get_user_verification_chats(user_id)
    open_chats = [c for c in chats if c.get("is_open")]

    if not open_chats:
        return False

    active_chat = open_chats[-1]
    chat_id     = active_chat["id"]
    msg         = update.message

    if msg.photo:
        file_id = msg.photo[-1].file_id
        add_verification_chat_message(chat_id, "user", "photo", file_id=file_id)
        label = "📷 תמונה"
    elif msg.video:
        file_id = msg.video.file_id
        add_verification_chat_message(chat_id, "user", "video", file_id=file_id)
        label = "🎥 סרטון"
    elif msg.document:
        file_id = msg.document.file_id
        add_verification_chat_message(chat_id, "user", "document", file_id=file_id)
        label = "📎 מסמך"
    elif msg.text:
        add_verification_chat_message(chat_id, "user", "text", content_text=msg.text)
        label = f"💬 {msg.text[:100]}"
    else:
        return False

    try:
        await msg.reply_text("✅ ההודעה נשלחה לנציג.")
    except Exception:
        pass

    admin_id = active_chat["opened_by"]
    vid      = active_chat["verification_id"]
    try:
        await context.bot.send_message(
            chat_id=admin_id,
            text=(
                f"📩 <b>הודעה חדשה בשיחה</b>\n\n"
                f"מאת: <code>{user_id}</code>\n"
                f"{label}"
            ),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📂 פתח שיחה", callback_data=f"VCHAT_VIEW_{vid}_{chat_id}"),
            ]]),
            parse_mode="HTML",
        )
    except Exception:
        pass

    return True


def _split_two_ids(suffix: str) -> tuple:
    """מפצל מחרוזת '123_456' לשני int-ים."""
    parts = suffix.split("_", 1)
    return int(parts[0]), int(parts[1])


def _back_to_view_kb(vid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 חזרה לפרופיל", callback_data=f"VUSERS_VIEW_{vid}")],
    ])


async def _edit_stored(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id,
    msg_id,
    text: str,
    keyboard: InlineKeyboardMarkup,
) -> None:
    if not chat_id or not msg_id:
        return
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.error("_edit_stored failed: %s", exc)
