"""
admin/publishing_admin.py
---------------------------
ConversationHandler מלא לניהול מודול הפרסום.

רישום ב-app/bot.py — שורה אחת:

    from admin.publishing_admin import build_publishing_handler
    application.add_handler(
        build_publishing_handler(
            is_admin_fn=lambda u: (
                is_super_admin(u.effective_user.id)
                or has_permission(u.effective_user.id, "admin")
            )
        ),
        group=-1,
    )

פרמטר is_admin_fn:
    פונקציה (sync) שמקבלת Update ומחזירה bool.

תלויות:
    repositories/pub_page_repository.py   — פונקציות pub_* לעמודים
    repositories/pub_button_repository.py — פונקציות pub_* לכפתורים
    services/home_service.py              — לוגיקת דף הבית
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ---------- תפריט ניהול ראשי ----------
from admin.admin import admin_panel

# ---------- UI גנרי (כל המערכת) ----------
from admin.ui_helpers import (
    answer_query,
    edit_or_send,
    safe_delete_message,
    kb_confirm_delete,
)

# ---------- states + callback helpers ----------
from admin.publishing_states import (
    cb, parse_cb,
    BUTTON_TYPES,
    S_MAIN_MENU,
    S_HOME_MENU,  S_HOME_WAIT_IMAGE, S_HOME_WAIT_TEXT,
    S_PAGES_LIST, S_PAGE_VIEW,
    S_PAGE_WAIT_TITLE, S_PAGE_WAIT_IMAGE, S_PAGE_WAIT_TEXT,
    S_BTN_LIST,   S_BTN_VIEW,
    S_BTN_WAIT_LABEL, S_BTN_WAIT_VALUE,
    S_BTN_SELECT_TYPE, S_BTN_SELECT_PAGE,
    S_CONFIRM_DELETE,
)

# ---------- מקלדות פרסום ----------
from admin.publishing_keyboards import (
    kb_main_menu,
    kb_home_menu,
    kb_pages_list,
    kb_page_view,
    kb_buttons_list,
    kb_button_type_select,
    kb_button_type_change,
    kb_button_view,
    kb_select_target_page,
    kb_wait_input,
    kb_catalog_audience_select,
)

# ---------- שירות דף הבית ----------
from services.home_service import (
    get_home_data,
    update_home_image,
    update_home_media,
    clear_home_image,
    clear_home_media,
    update_home_text,
    toggle_home_active,
)

# ---------- שירות קטלוגים ----------
from services.verified_users_service import (
    get_all_catalogs, create_catalog, update_catalog,
    CATALOG_AUDIENCES,
)

# ---------- repositories ייעודיים למודול הפרסום ----------
from repositories.pub_page_repository import (
    pub_get_pages_by_parent,
    pub_get_page_by_id,
    pub_get_all_pages,
    pub_create_page,
    pub_update_page_title,
    pub_update_page_image,
    pub_update_page_media,
    pub_update_page_text,
    pub_update_catalog_slug,
    pub_delete_page,
    pub_toggle_page_active,
    pub_move_page_up,
    pub_move_page_down,
)
from repositories.pub_button_repository import (
    pub_get_buttons_for_home,
    pub_get_buttons_for_page,
    pub_get_button_by_id,
    pub_create_button,
    pub_update_button_label,
    pub_update_button_value,
    pub_update_button_type,
    pub_update_button_target_page,
    pub_delete_button,
    pub_toggle_button_active,
    pub_move_button_up,
    pub_move_button_down,
    pub_move_button_left,
    pub_move_button_right,
    pub_duplicate_button,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# context.user_data keys (פרטיים למודול זה — prefix _pub_)
# ---------------------------------------------------------------------------
_K_BTN_ID     = "_pub_btn_id"
_K_PAGE_ID    = "_pub_page_id"
_K_OWNER_TYPE = "_pub_owner_type"   # "home" | "page"
_K_OWNER_ID   = "_pub_owner_id"
_K_BTN_TYPE   = "_pub_btn_type"
_K_NEW_LABEL  = "_pub_new_label"
_K_NEW_PTYPE  = "_pub_new_page_type"
_K_NEW_PARENT = "_pub_new_parent"
_K_DEL_TARGET = "_pub_del_target"   # dict {kind, id, ...}
_K_TARGET_PG  = "_pub_target_page"
_K_ROW_INDEX  = "_pub_row_index"    # int = הוסף לשורה קיימת, None = שורה חדשה
_K_NEW_TITLE   = "_pub_new_title"    # כותרת בהמתנה לבחירת קטלוג
_K_NEW_CAT_NAME = "_pub_new_cat_name"  # שם קטלוג חדש בהמתנה לבחירת audience

# מצבי שיחה מקומיים (לא מוגדרים ב-publishing_states.py)
_S_PAGE_WAIT_CATALOG              = 17   # המתנה לבחירת קטלוג קיים
_S_PAGE_WAIT_NEW_CATALOG_NAME     = 18   # המתנה לשם קטלוג חדש
_S_PAGE_WAIT_CATALOG_AUDIENCE     = 19   # המתנה לבחירת audience לקטלוג (יצירה/עריכה)
_S_PAGE_RELINK_CATALOG            = 20   # המתנה לבחירת קטלוג חדש לעמוד קיים (שינוי קישור)

# מיפוי כיוון -> פונקציית הזזת כפתור
_BTN_MOVE_FN = {
    "up":    pub_move_button_up,
    "down":  pub_move_button_down,
    "left":  pub_move_button_left,
    "right": pub_move_button_right,
}


# ===========================================================================
# FACTORY
# ===========================================================================

def build_publishing_handler(
    is_admin_fn: Callable[[Update], bool],
    command: str = "publishing",
) -> ConversationHandler:
    """
    בונה ומחזיר ConversationHandler מוגדר לניהול מודול הפרסום.

    Parameters:
        is_admin_fn: פונקציה (sync) שמקבלת Update ומחזירה bool.
        command:     פקודת הפעלה (ברירת מחדל: /publishing).
    """

    # ===================================================================
    # ENTRY + תפריט ראשי
    # ===================================================================

    async def cmd_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        if not is_admin_fn(update):
            return ConversationHandler.END
        _clear_state(context)
        await edit_or_send(update, context, "📢 <b>מודול הפרסום</b>", kb_main_menu())
        return S_MAIN_MENU

    async def cb_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await answer_query(update)
        _clear_state(context)
        await update.callback_query.edit_message_text(
            "📢 <b>מודול הפרסום</b>", reply_markup=kb_main_menu(), parse_mode="HTML"
        )
        return S_MAIN_MENU

    async def cb_close(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await answer_query(update)
        await admin_panel(update, context)
        return ConversationHandler.END

    # ===================================================================
    # דף הבית
    # ===================================================================

    async def cb_home_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await answer_query(update)
        home = get_home_data()
        if home is None:
            await answer_query(update, "שגיאה בטעינת דף הבית", alert=True)
            return S_MAIN_MENU
        await update.callback_query.edit_message_text(
            _home_text(home),
            reply_markup=kb_home_menu(
                has_image=bool(home["image_file_id"]),
                has_text=bool(home["text"]),
                is_active=bool(home["is_active"]),
            ),
            parse_mode="HTML",
        )
        return S_HOME_MENU

    async def cb_home_edit_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await answer_query(update)
        await update.callback_query.edit_message_text(
            "שלח תמונה / GIF / וידאו לדף הבית:",
            reply_markup=kb_wait_input(cb("home", "menu")),
        )
        return S_HOME_WAIT_IMAGE

    async def cb_home_clear_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await answer_query(update)
        clear_home_image()
        return await _refresh_home(update)

    async def cb_home_edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await answer_query(update)
        await update.callback_query.edit_message_text(
            "שלח את הטקסט החדש לדף הבית (HTML נתמך):",
            reply_markup=kb_wait_input(cb("home", "menu")),
        )
        return S_HOME_WAIT_TEXT

    async def cb_home_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await answer_query(update)
        toggle_home_active()
        return await _refresh_home(update)

    async def msg_home_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        msg = update.message
        if msg.photo:
            file_id    = msg.photo[-1].file_id
            media_type = "photo"
        elif msg.animation:
            file_id    = msg.animation.file_id
            media_type = "animation"
        elif msg.video:
            file_id    = msg.video.file_id
            media_type = "video"
        elif msg.audio:
            file_id    = msg.audio.file_id
            media_type = "audio"
        elif msg.voice:
            file_id    = msg.voice.file_id
            media_type = "voice"
        elif msg.document:
            file_id    = msg.document.file_id
            media_type = "document"
        elif msg.video_note:
            file_id    = msg.video_note.file_id
            media_type = "video_note"
        elif msg.sticker:
            file_id    = msg.sticker.file_id
            media_type = "sticker"
        else:
            await msg.reply_text("סוג מדיה לא נתמך.")
            return S_HOME_WAIT_IMAGE
        update_home_media(file_id, media_type)
        await msg.reply_text("המדיה עודכנה.")
        return await _send_home_menu(update, context)

    async def msg_home_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        update_home_text((update.message.text or "").strip())
        await update.message.reply_text("הטקסט עודכן.")
        return await _send_home_menu(update, context)

    async def _refresh_home(update: Update) -> int:
        home = get_home_data()
        if home is None:
            return S_MAIN_MENU
        await update.callback_query.edit_message_text(
            _home_text(home),
            reply_markup=kb_home_menu(
                has_image=bool(home["image_file_id"]),
                has_text=bool(home["text"]),
                is_active=bool(home["is_active"]),
            ),
            parse_mode="HTML",
        )
        return S_HOME_MENU

    async def _send_home_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        home = get_home_data()
        if home is None:
            return S_MAIN_MENU
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=_home_text(home),
            reply_markup=kb_home_menu(
                has_image=bool(home["image_file_id"]),
                has_text=bool(home["text"]),
                is_active=bool(home["is_active"]),
            ),
            parse_mode="HTML",
        )
        return S_HOME_MENU

    # ===================================================================
    # עמודים
    # ===================================================================

    async def cb_pages_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await answer_query(update)
        parts     = parse_cb(update.callback_query.data)
        raw       = parts[2] if len(parts) > 2 else "root"
        parent_id = None if raw == "root" else int(raw)
        pages     = pub_get_pages_by_parent(parent_id)
        back_cb   = cb("main") if parent_id is None else cb("page", "view", parent_id)
        title     = "עמודים ראשיים" if parent_id is None else "עמודי-בן"
        await update.callback_query.edit_message_text(
            f"<b>{title}</b>",
            reply_markup=kb_pages_list(pages, parent_id, back_cb),
            parse_mode="HTML",
        )
        return S_PAGES_LIST

    async def cb_page_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await answer_query(update)
        page_id = int(parse_cb(update.callback_query.data)[2])
        return await _show_page(update, context, page_id)

    async def cb_page_new(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await answer_query(update)
        parts     = parse_cb(update.callback_query.data)
        ptype     = "catalog" if parts[1] == "new_catalog" else "page"
        parent_id = None if parts[2] == "0" else int(parts[2])
        context.user_data.update({_K_PAGE_ID: None, _K_NEW_PTYPE: ptype, _K_NEW_PARENT: parent_id})
        label = "קטלוג" if ptype == "catalog" else "עמוד"
        await update.callback_query.edit_message_text(
            f"<b>עמוד חדש ({label})</b>\nשלח את הכותרת:",
            reply_markup=kb_wait_input(cb("pages", "list", parent_id or "root")),
            parse_mode="HTML",
        )
        return S_PAGE_WAIT_TITLE

    async def cb_page_edit_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await answer_query(update)
        page_id = int(parse_cb(update.callback_query.data)[2])
        context.user_data[_K_PAGE_ID] = page_id
        await update.callback_query.edit_message_text(
            "שלח את הכותרת החדשה:",
            reply_markup=kb_wait_input(cb("page", "view", page_id)),
        )
        return S_PAGE_WAIT_TITLE

    async def cb_page_edit_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await answer_query(update)
        page_id = int(parse_cb(update.callback_query.data)[2])
        context.user_data[_K_PAGE_ID] = page_id
        await update.callback_query.edit_message_text(
            "שלח תמונה / GIF / וידאו לעמוד:",
            reply_markup=kb_wait_input(cb("page", "view", page_id)),
        )
        return S_PAGE_WAIT_IMAGE

    async def cb_page_edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await answer_query(update)
        page_id = int(parse_cb(update.callback_query.data)[2])
        context.user_data[_K_PAGE_ID] = page_id
        await update.callback_query.edit_message_text(
            "שלח את הטקסט (HTML נתמך):",
            reply_markup=kb_wait_input(cb("page", "view", page_id)),
        )
        return S_PAGE_WAIT_TEXT

    async def cb_page_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await answer_query(update)
        page_id = int(parse_cb(update.callback_query.data)[2])
        pub_toggle_page_active(page_id)
        return await _show_page(update, context, page_id)

    async def cb_page_move(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await answer_query(update)
        parts   = parse_cb(update.callback_query.data)
        page_id = int(parts[2])
        (pub_move_page_up if parts[1] == "up" else pub_move_page_down)(page_id)
        return await _show_page(update, context, page_id)

    async def cb_page_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await answer_query(update)
        page_id = int(parse_cb(update.callback_query.data)[2])
        page    = pub_get_page_by_id(page_id)
        if page is None:
            return S_PAGES_LIST
        context.user_data[_K_DEL_TARGET] = {
            "kind": "page", "id": page_id, "parent_id": page["parent_id"]
        }
        await update.callback_query.edit_message_text(
            f"למחוק את <b>{page['title']}</b>?\nכל עמודי-הבן והכפתורים ימחקו.",
            reply_markup=kb_confirm_delete(
                confirm_cb=cb("confirm_delete"),
                cancel_cb=cb("page", "view", page_id),
            ),
            parse_mode="HTML",
        )
        return S_CONFIRM_DELETE

    async def msg_page_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        title   = (update.message.text or "").strip()
        page_id = context.user_data.get(_K_PAGE_ID)
        if not title:
            await update.message.reply_text("הכותרת לא יכולה להיות ריקה.")
            return S_PAGE_WAIT_TITLE
        if page_id:
            # עריכת כותרת לעמוד קיים — זרימה ללא שינוי
            ok = pub_update_page_title(page_id, title)
            await update.message.reply_text("נשמר." if ok else "שגיאה.")
            if page_id:
                return await _send_page(update, context, page_id)
            return S_PAGES_LIST

        ptype     = context.user_data.get(_K_NEW_PTYPE, "page")
        parent_id = context.user_data.get(_K_NEW_PARENT)

        if ptype == "catalog":
            # שמירת הכותרת בהמתנה לבחירת הקטלוג
            context.user_data[_K_NEW_TITLE] = title
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="בחר את הקטלוג לשיוך העמוד:",
                reply_markup=_build_catalog_picker_kb(parent_id),
            )
            return _S_PAGE_WAIT_CATALOG

        # עמוד רגיל — יצירה מיידית ללא בחירת קטלוג
        new_id = pub_create_page(title=title, page_type=ptype, parent_id=parent_id)
        ok     = new_id > 0
        if ok:
            context.user_data[_K_PAGE_ID] = new_id
            page_id = new_id
        await update.message.reply_text("נשמר." if ok else "שגיאה.")
        if page_id:
            return await _send_page(update, context, page_id)
        return S_PAGES_LIST

    async def cb_page_catalog_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """מקבל בחירת קטלוג, יוצר את עמוד הקטלוג עם ה-slug הנבחר."""
        await answer_query(update)
        parts     = parse_cb(update.callback_query.data)   # ["page", "pick_catalog", "<slug>"]
        slug      = parts[2]
        title     = context.user_data.pop(_K_NEW_TITLE, "")
        ptype     = context.user_data.get(_K_NEW_PTYPE, "catalog")
        parent_id = context.user_data.get(_K_NEW_PARENT)

        new_id = pub_create_page(
            title=title, page_type=ptype, parent_id=parent_id, catalog_slug=slug
        )
        if new_id > 0:
            context.user_data[_K_PAGE_ID] = new_id
            return await _show_page(update, context, new_id)

        await update.callback_query.edit_message_text("שגיאה ביצירת העמוד.")
        return S_PAGES_LIST

    async def cb_page_create_catalog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """לחיצה על '➕ צור קטלוג חדש' — מבקש שם לקטלוג החדש."""
        await answer_query(update)
        parent_id = context.user_data.get(_K_NEW_PARENT)
        await update.callback_query.edit_message_text(
            "שלח את שם הקטלוג החדש:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "◀️ ביטול",
                    callback_data=cb("pages", "list", parent_id or "root"),
                )
            ]]),
        )
        return _S_PAGE_WAIT_NEW_CATALOG_NAME

    async def msg_page_new_catalog_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """קבלת שם קטלוג חדש — שומר ועובר לבחירת audience."""
        name      = (update.message.text or "").strip()
        parent_id = context.user_data.get(_K_NEW_PARENT)
        if not name:
            await update.message.reply_text("השם לא יכול להיות ריק. נסה שוב:")
            return _S_PAGE_WAIT_NEW_CATALOG_NAME

        context.user_data[_K_NEW_CAT_NAME] = name
        back_cb = cb("pages", "list", parent_id or "root")
        await update.message.reply_text(
            f"קטלוג: <b>{name}</b>\n\nמי יוכל לראות את הקטלוג הזה?",
            reply_markup=kb_catalog_audience_select(
                mode="new",
                audiences=CATALOG_AUDIENCES,
                back_cb=back_cb,
            ),
            parse_mode="HTML",
        )
        return _S_PAGE_WAIT_CATALOG_AUDIENCE

    async def cb_catalog_new_audience(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """בחירת audience לקטלוג חדש — יוצר את הקטלוג ומציג בוחר קטלוגים (הודעה יחידה)."""
        await answer_query(update)
        parts     = parse_cb(update.callback_query.data)   # ["catalog","new_audience","<key>"]
        audience  = parts[2]
        name      = context.user_data.pop(_K_NEW_CAT_NAME, "")
        parent_id = context.user_data.get(_K_NEW_PARENT)

        cat_id = create_catalog(name=name, audience=audience)
        label  = CATALOG_AUDIENCES.get(audience, audience)
        header = (
            f"✅ הקטלוג <b>{name}</b> נוצר (הרשאות: {label}).\n\nבחר קטלוג לשיוך העמוד:"
            if cat_id else
            "⚠️ שגיאה ביצירת הקטלוג (ייתכן שהשם כבר קיים).\n\nבחר קטלוג קיים:"
        )
        await update.callback_query.edit_message_text(
            header,
            reply_markup=_build_catalog_picker_kb(parent_id),
            parse_mode="HTML",
        )
        return _S_PAGE_WAIT_CATALOG

    async def cb_catalog_edit_audience(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """פתיחת בורר audience לקטלוג קיים — נקרא ממסך עריכת עמוד."""
        await answer_query(update)
        parts   = parse_cb(update.callback_query.data)   # ["catalog","edit_audience","<page_id>"]
        page_id = int(parts[2])
        context.user_data[_K_PAGE_ID] = page_id
        page    = pub_get_page_by_id(page_id)
        if page is None or page["page_type"] != "catalog":
            return S_PAGE_VIEW

        back_cb = cb("page", "view", page_id)
        await update.callback_query.edit_message_text(
            f"קטלוג: <b>{page['title']}</b>\n\nבחר מי יוכל לראות את הקטלוג:",
            reply_markup=kb_catalog_audience_select(
                mode=f"edit:{page_id}",
                audiences=CATALOG_AUDIENCES,
                back_cb=back_cb,
            ),
            parse_mode="HTML",
        )
        return _S_PAGE_WAIT_CATALOG_AUDIENCE

    async def cb_catalog_apply_audience(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """שמירת audience חדש לקטלוג קיים — מעדכן ב-DB וחוזר לתצוגת העמוד."""
        await answer_query(update)
        parts    = parse_cb(update.callback_query.data)  # ["catalog","apply_audience","<page_id>","<key>"]
        page_id  = int(parts[2])
        audience = parts[3]

        page = pub_get_page_by_id(page_id)
        if page is None:
            await update.callback_query.answer("שגיאה: הקטלוג לא נמצא.")
            return await _show_page(update, context, page_id)

        # מציאת ה-catalog_id לפי ה-slug
        slug   = page["catalog_slug"]
        if not slug:
            await update.callback_query.answer("שגיאה: לקטלוג אין slug.")
            return await _show_page(update, context, page_id)
        cats   = get_all_catalogs()
        cat    = next((c for c in cats if c["slug"] == slug), None)
        if cat is None:
            await update.callback_query.answer("שגיאה: קטלוג לא קיים במסד הנתונים.")
            return await _show_page(update, context, page_id)

        ok    = update_catalog(cat["id"], audience=audience)
        label = CATALOG_AUDIENCES.get(audience, audience)
        await update.callback_query.answer(
            f"✅ עודכן: {label}" if ok else "⚠️ שגיאה בעדכון"
        )
        return await _show_page(update, context, page_id)

    async def cb_page_relink_catalog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """פתיחת בורר קטלוג לשינוי הקישור בעמוד קטלוג קיים."""
        await answer_query(update)
        parts   = parse_cb(update.callback_query.data)   # ["catalog","relink","<page_id>"]
        page_id = int(parts[2])
        context.user_data[_K_PAGE_ID] = page_id
        page    = pub_get_page_by_id(page_id)
        if page is None or page["page_type"] != "catalog":
            return S_PAGE_VIEW
        current = page["catalog_slug"] or "(לא מוגדר)"
        await update.callback_query.edit_message_text(
            f"<b>{page['title']}</b>\n"
            f"קטלוג מקושר כעת: <code>{current}</code>\n\n"
            f"בחר קטלוג חדש לשיוך:",
            reply_markup=_build_relink_catalog_kb(page_id),
            parse_mode="HTML",
        )
        return _S_PAGE_RELINK_CATALOG

    async def cb_page_apply_relink(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """שמירת קטלוג חדש לעמוד קיים ושמירת השינוי ב-DB."""
        await answer_query(update)
        parts    = parse_cb(update.callback_query.data)  # ["catalog","apply_relink","<page_id>","<slug>"]
        page_id  = int(parts[2])
        new_slug = parts[3]
        ok = pub_update_catalog_slug(page_id, new_slug)
        await update.callback_query.answer(
            f"✅ קטלוג שונה ל: {new_slug}" if ok else "⚠️ שגיאה בעדכון"
        )
        return await _show_page(update, context, page_id)

    async def msg_page_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        page_id = context.user_data.get(_K_PAGE_ID)
        msg = update.message
        if msg.photo:
            file_id    = msg.photo[-1].file_id
            media_type = "photo"
        elif msg.animation:
            file_id    = msg.animation.file_id
            media_type = "animation"
        elif msg.video:
            file_id    = msg.video.file_id
            media_type = "video"
        elif msg.audio:
            file_id    = msg.audio.file_id
            media_type = "audio"
        elif msg.voice:
            file_id    = msg.voice.file_id
            media_type = "voice"
        elif msg.document:
            file_id    = msg.document.file_id
            media_type = "document"
        elif msg.video_note:
            file_id    = msg.video_note.file_id
            media_type = "video_note"
        elif msg.sticker:
            file_id    = msg.sticker.file_id
            media_type = "sticker"
        else:
            await msg.reply_text("סוג מדיה לא נתמך.")
            return S_PAGE_WAIT_IMAGE
        if not page_id:
            await msg.reply_text("שגיאה: לא נמצא מזהה עמוד.")
            return S_PAGE_WAIT_IMAGE
        pub_update_page_media(page_id, file_id, media_type)
        await msg.reply_text("המדיה עודכנה.")
        return await _send_page(update, context, page_id)

    async def msg_page_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        page_id = context.user_data.get(_K_PAGE_ID)
        if not page_id:
            return S_PAGES_LIST
        pub_update_page_text(page_id, (update.message.text or "").strip())
        await update.message.reply_text("הטקסט עודכן.")
        return await _send_page(update, context, page_id)

    async def _show_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page_id: int) -> int:
        """עורך את ההודעה הנוכחית לתצוגת עמוד (callback)."""
        page = pub_get_page_by_id(page_id)
        if page is None:
            return S_PAGES_LIST
        children = pub_get_pages_by_parent(page_id)
        context.user_data[_K_PAGE_ID] = page_id
        await update.callback_query.edit_message_text(
            _page_text(page, len(children)),
            reply_markup=kb_page_view(
                page_id=page_id,
                is_active=bool(page["is_active"]),
                has_children=bool(children),
                parent_id=page["parent_id"],
                page_type=page["page_type"],
            ),
            parse_mode="HTML",
        )
        return S_PAGE_VIEW

    async def _send_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page_id: int) -> int:
        """שולח תצוגת עמוד כהודעה חדשה (אחרי message)."""
        page = pub_get_page_by_id(page_id)
        if page is None:
            return S_PAGES_LIST
        children = pub_get_pages_by_parent(page_id)
        context.user_data[_K_PAGE_ID] = page_id
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=_page_text(page, len(children)),
            reply_markup=kb_page_view(
                page_id=page_id,
                is_active=bool(page["is_active"]),
                has_children=bool(children),
                parent_id=page["parent_id"],
                page_type=page["page_type"],
            ),
            parse_mode="HTML",
        )
        return S_PAGE_VIEW

    # ===================================================================
    # כפתורים
    # ===================================================================

    async def cb_btn_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await answer_query(update)
        parts      = parse_cb(update.callback_query.data)
        owner_type = parts[2]
        owner_id   = int(parts[3])
        context.user_data.update({_K_OWNER_TYPE: owner_type, _K_OWNER_ID: owner_id})
        buttons    = (pub_get_buttons_for_home(owner_id) if owner_type == "home"
                      else pub_get_buttons_for_page(owner_id))
        back_cb    = cb("home", "menu") if owner_type == "home" else cb("page", "view", owner_id)
        await update.callback_query.edit_message_text(
            f"<b>כפתורים</b> ({len(buttons)})",
            reply_markup=kb_buttons_list(buttons, owner_type, owner_id, back_cb),
            parse_mode="HTML",
        )
        return S_BTN_LIST

    async def cb_btn_new(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await answer_query(update)
        parts      = parse_cb(update.callback_query.data)
        owner_type = parts[2]
        owner_id   = int(parts[3])
        context.user_data.update({
            _K_OWNER_TYPE: owner_type,
            _K_OWNER_ID:   owner_id,
            _K_BTN_ID:     None,
            _K_ROW_INDEX:  None,
        })
        await update.callback_query.edit_message_text(
            "<b>כפתור חדש</b>\nבחר סוג:",
            reply_markup=kb_button_type_select(owner_type, owner_id),
            parse_mode="HTML",
        )
        return S_BTN_SELECT_TYPE

    async def cb_btn_add_to_row(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """
        יוצר כפתור חדש באותו row_index של הכפתור הנוכחי.
        לאחר היצירה ניתן לבדוק את כפתורי left/right בין שני הכפתורים בשורה.
        """
        await answer_query(update)
        btn_id = int(parse_cb(update.callback_query.data)[2])
        btn    = pub_get_button_by_id(btn_id)
        if btn is None:
            return S_BTN_LIST
        owner_type = "home" if btn["home_id"] else "page"
        owner_id   = btn["home_id"] or btn["page_id"]
        context.user_data.update({
            _K_OWNER_TYPE: owner_type,
            _K_OWNER_ID:   owner_id,
            _K_BTN_ID:     None,
            _K_ROW_INDEX:  btn["row_index"],
        })
        await update.callback_query.edit_message_text(
            "<b>כפתור חדש באותה שורה</b>\nבחר סוג:",
            reply_markup=kb_button_type_select(owner_type, owner_id),
            parse_mode="HTML",
        )
        return S_BTN_SELECT_TYPE

    async def cb_btn_set_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await answer_query(update)
        parts      = parse_cb(update.callback_query.data)
        btype      = parts[2]
        owner_type = parts[3]
        owner_id   = int(parts[4])
        context.user_data.update({_K_BTN_TYPE: btype, _K_OWNER_TYPE: owner_type, _K_OWNER_ID: owner_id})

        if btype == "share":
            btn_id = _do_create_btn(context, label="שיתוף", value="share")
            if btn_id and btn_id > 0:
                context.user_data[_K_BTN_ID] = btn_id
                return await _show_btn(update, context, btn_id)
            return S_BTN_LIST

        if btype == "page_link":
            pages = pub_get_all_pages()
            await update.callback_query.edit_message_text(
                "בחר עמוד יעד:",
                reply_markup=kb_select_target_page(pages, 0),
            )
            return S_BTN_SELECT_PAGE

        await update.callback_query.edit_message_text(
            f"סוג: <b>{BUTTON_TYPES[btype]}</b>\nשלח תווית לכפתור:",
            reply_markup=kb_wait_input(cb("btn", "list", owner_type, owner_id)),
            parse_mode="HTML",
        )
        return S_BTN_WAIT_LABEL

    async def cb_btn_set_target(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await answer_query(update)
        parts     = parse_cb(update.callback_query.data)
        target_id = int(parts[3])
        page      = pub_get_page_by_id(target_id)
        page_title = page["title"] if page else str(target_id)

        btn_id = context.user_data.get(_K_BTN_ID)

        # מצב עריכה: כפתור קיים שינה סוג ל-page_link דרך cb_btn_apply_type
        if btn_id:
            pub_update_button_type(btn_id, "page_link")
            pub_update_button_target_page(btn_id, target_id)
            await update.callback_query.edit_message_text(
                f"✅ עמוד יעד עודכן: <b>{page_title}</b>",
                parse_mode="HTML",
            )
            return await _show_btn(update, context, btn_id)

        # מצב יצירה: כפתור חדש — שומרים target ומבקשים תווית
        context.user_data[_K_TARGET_PG] = target_id
        owner_type = context.user_data.get(_K_OWNER_TYPE, "home")
        owner_id   = context.user_data.get(_K_OWNER_ID, 1)
        await update.callback_query.edit_message_text(
            f"עמוד יעד: <b>{page_title}</b>\nשלח תווית לכפתור:",
            reply_markup=kb_wait_input(cb("btn", "list", owner_type, owner_id)),
            parse_mode="HTML",
        )
        return S_BTN_WAIT_LABEL

    async def cb_btn_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await answer_query(update)
        btn_id = int(parse_cb(update.callback_query.data)[2])
        return await _show_btn(update, context, btn_id)

    async def cb_btn_edit_label(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await answer_query(update)
        btn_id = int(parse_cb(update.callback_query.data)[2])
        context.user_data[_K_BTN_ID] = btn_id
        await update.callback_query.edit_message_text(
            "שלח תווית חדשה:",
            reply_markup=kb_wait_input(cb("btn", "view", btn_id)),
        )
        return S_BTN_WAIT_LABEL

    async def cb_btn_edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await answer_query(update)
        btn_id = int(parse_cb(update.callback_query.data)[2])
        context.user_data[_K_BTN_ID] = btn_id
        await update.callback_query.edit_message_text(
            "שלח ערך חדש:",
            reply_markup=kb_wait_input(cb("btn", "view", btn_id)),
        )
        return S_BTN_WAIT_VALUE

    async def cb_btn_edit_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """מציג בורר סוג לכפתור קיים (עדכון בלבד - לא יצירה)."""
        await answer_query(update)
        btn_id = int(parse_cb(update.callback_query.data)[2])
        context.user_data[_K_BTN_ID] = btn_id
        await update.callback_query.edit_message_text(
            "בחר סוג חדש לכפתור:",
            reply_markup=kb_button_type_change(btn_id),
        )
        return S_BTN_SELECT_TYPE

    async def cb_btn_apply_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """מעדכן את סוג הכפתור הקיים ומחזיר לתצוגתו."""
        await answer_query(update)
        parts  = parse_cb(update.callback_query.data)
        btype  = parts[2]
        btn_id = int(parts[3])

        # page_link: חייב לבחור עמוד יעד — פותחים בורר לפני שמירת הסוג
        if btype == "page_link":
            context.user_data[_K_BTN_ID]   = btn_id
            context.user_data[_K_BTN_TYPE] = btype
            pages = pub_get_all_pages()
            await update.callback_query.edit_message_text(
                "בחר עמוד יעד:",
                reply_markup=kb_select_target_page(pages, btn_id),
            )
            return S_BTN_SELECT_PAGE

        pub_update_button_type(btn_id, btype)
        context.user_data[_K_BTN_ID] = btn_id
        return await _show_btn(update, context, btn_id)

    async def cb_btn_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await answer_query(update)
        btn_id = int(parse_cb(update.callback_query.data)[2])
        pub_toggle_button_active(btn_id)
        return await _show_btn(update, context, btn_id)

    async def cb_btn_move(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """
        מטפל בהזזת כפתור בכל 4 הכיוונים:
          up/down    -- שינוי row_index (מעבר שורה).
          left/right -- swap sort_order בתוך אותה שורה.

        אם ההזזה לא הצליחה (הכפתור כבר בקצה):
          - מציג toast בלבד.
          - לא קורא ל-answer_query().
          - לא קורא ל-_show_btn() -- מונע BadRequest: Message is not modified.
        """
        parts     = parse_cb(update.callback_query.data)
        direction = parts[1]
        btn_id    = int(parts[2])
        fn        = _BTN_MOVE_FN.get(direction)
        moved     = fn(btn_id) if fn else False

        if not moved:
            await update.callback_query.answer("אין לאן להזיז")
            return S_BTN_VIEW

        await answer_query(update)
        return await _show_btn(update, context, btn_id)

    async def cb_btn_duplicate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await answer_query(update)
        btn_id = int(parse_cb(update.callback_query.data)[2])
        new_id = pub_duplicate_button(btn_id)
        if new_id and new_id > 0:
            await answer_query(update, "שוכפל")
        return await _refresh_btn_list(update, context)

    async def cb_btn_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await answer_query(update)
        btn_id = int(parse_cb(update.callback_query.data)[2])
        btn    = pub_get_button_by_id(btn_id)
        if btn is None:
            return S_BTN_LIST
        owner_type = "home" if btn["home_id"] else "page"
        owner_id   = btn["home_id"] or btn["page_id"]
        context.user_data[_K_DEL_TARGET] = {
            "kind": "btn", "id": btn_id, "owner_type": owner_type, "owner_id": owner_id
        }
        await update.callback_query.edit_message_text(
            f"למחוק את הכפתור <b>{btn['label']}</b>?",
            reply_markup=kb_confirm_delete(
                confirm_cb=cb("confirm_delete"),
                cancel_cb=cb("btn", "view", btn_id),
            ),
            parse_mode="HTML",
        )
        return S_CONFIRM_DELETE

    async def msg_btn_label(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        label      = (update.message.text or "").strip()
        btn_id     = context.user_data.get(_K_BTN_ID)
        if not label:
            await update.message.reply_text("התווית לא יכולה להיות ריקה.")
            return S_BTN_WAIT_LABEL
        if btn_id:
            pub_update_button_label(btn_id, label)
            await update.message.reply_text("עודכן.")
            return await _send_btn(update, context, btn_id)
        context.user_data[_K_NEW_LABEL] = label
        btype = context.user_data.get(_K_BTN_TYPE, "text")

        # page_link: עמוד היעד נבחר כבר ב-cb_btn_set_target — יוצרים ישירות
        if btype == "page_link":
            target = context.user_data.get(_K_TARGET_PG)
            if not target:
                # target חסר — מחזירים לבורר (לא אמור לקרות בזרימה תקינה)
                owner_type = context.user_data.get(_K_OWNER_TYPE, "home")
                owner_id   = context.user_data.get(_K_OWNER_ID, 1)
                await update.message.reply_text(
                    "⚠️ לא נבחר עמוד יעד. חזור ובחר עמוד מהרשימה.",
                    reply_markup=kb_wait_input(cb("btn", "list", owner_type, owner_id)),
                )
                return S_BTN_LIST
            new_id = _do_create_btn(context, label=label, value="", target_page_id=target)
            if new_id and new_id > 0:
                context.user_data[_K_BTN_ID] = new_id
                await update.message.reply_text("הכפתור נוצר.")
                return await _send_btn(update, context, new_id)
            await update.message.reply_text("שגיאה ביצירת הכפתור.")
            return S_BTN_LIST

        hints = {
            "text":     "הקלד את תוכן ההודעה:",
            "url":      "הדבק קישור (https://...):",
            "phone":    "הכנס מספר טלפון:",
            "email":    "הכנס כתובת מייל:",
            "location": "הכנס קואורדינטות (lat,lon):",
        }
        await update.message.reply_text(hints.get(btype, "הכנס ערך:"))
        return S_BTN_WAIT_VALUE

    async def msg_btn_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        value  = (update.message.text or "").strip()
        btn_id = context.user_data.get(_K_BTN_ID)
        if btn_id:
            pub_update_button_value(btn_id, value)
            await update.message.reply_text("עודכן.")
            return await _send_btn(update, context, btn_id)
        label  = context.user_data.get(_K_NEW_LABEL, "כפתור")
        btype  = context.user_data.get(_K_BTN_TYPE, "text")
        target = context.user_data.get(_K_TARGET_PG)
        # חסימת page_link ללא target_page_id — לא אמור לקרות, אבל מגן כנגד עקיפה
        if btype == "page_link" and not target:
            owner_type = context.user_data.get(_K_OWNER_TYPE, "home")
            owner_id   = context.user_data.get(_K_OWNER_ID, 1)
            await update.message.reply_text(
                "⚠️ כפתור ניווט לעמוד חייב לכלול עמוד יעד. חזור ובחר עמוד מהרשימה.",
                reply_markup=kb_wait_input(cb("btn", "list", owner_type, owner_id)),
            )
            return S_BTN_LIST
        new_id = _do_create_btn(context, label=label, value=value, target_page_id=target)
        if new_id and new_id > 0:
            context.user_data[_K_BTN_ID] = new_id
            await update.message.reply_text("הכפתור נוצר.")
            return await _send_btn(update, context, new_id)
        await update.message.reply_text("שגיאה.")
        return S_BTN_LIST

    # ===================================================================
    # אישור מחיקה גנרי
    # ===================================================================

    async def cb_confirm_delete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await answer_query(update)
        target = context.user_data.pop(_K_DEL_TARGET, None)
        if not target:
            return S_MAIN_MENU

        if target["kind"] == "page":
            pub_delete_page(target["id"])
            back_cb    = cb("pages", "list", target.get("parent_id") or "root")
            next_state = S_PAGES_LIST
        else:
            pub_delete_button(target["id"])
            back_cb    = cb("btn", "list", target["owner_type"], target["owner_id"])
            next_state = S_BTN_LIST

        await update.callback_query.edit_message_text(
            "נמחק בהצלחה.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("חזור", callback_data=back_cb)
            ]]),
        )
        return next_state

    # ===================================================================
    # helpers פנימיים
    # ===================================================================

    async def _show_btn(update: Update, context: ContextTypes.DEFAULT_TYPE, btn_id: int) -> int:
        btn = pub_get_button_by_id(btn_id)
        if btn is None:
            return S_BTN_LIST
        owner_type = "home" if btn["home_id"] else "page"
        owner_id   = btn["home_id"] or btn["page_id"]
        context.user_data.update({_K_BTN_ID: btn_id, _K_OWNER_TYPE: owner_type, _K_OWNER_ID: owner_id})
        await update.callback_query.edit_message_text(
            _btn_text(btn),
            reply_markup=kb_button_view(btn_id, bool(btn["is_active"]), owner_type, owner_id),
            parse_mode="HTML",
        )
        return S_BTN_VIEW

    async def _send_btn(update: Update, context: ContextTypes.DEFAULT_TYPE, btn_id: int) -> int:
        btn = pub_get_button_by_id(btn_id)
        if btn is None:
            return S_BTN_LIST
        owner_type = "home" if btn["home_id"] else "page"
        owner_id   = btn["home_id"] or btn["page_id"]
        context.user_data.update({_K_BTN_ID: btn_id, _K_OWNER_TYPE: owner_type, _K_OWNER_ID: owner_id})
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=_btn_text(btn),
            reply_markup=kb_button_view(btn_id, bool(btn["is_active"]), owner_type, owner_id),
            parse_mode="HTML",
        )
        return S_BTN_VIEW

    async def _refresh_btn_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        owner_type = context.user_data.get(_K_OWNER_TYPE, "home")
        owner_id   = context.user_data.get(_K_OWNER_ID, 1)
        buttons    = (pub_get_buttons_for_home(owner_id) if owner_type == "home"
                      else pub_get_buttons_for_page(owner_id))
        back_cb    = cb("home", "menu") if owner_type == "home" else cb("page", "view", owner_id)
        await update.callback_query.edit_message_text(
            f"<b>כפתורים</b> ({len(buttons)})",
            reply_markup=kb_buttons_list(buttons, owner_type, owner_id, back_cb),
            parse_mode="HTML",
        )
        return S_BTN_LIST

    def _do_create_btn(
        context: ContextTypes.DEFAULT_TYPE,
        label: str,
        value: str,
        target_page_id: Optional[int] = None,
    ) -> int:
        owner_type = context.user_data.get(_K_OWNER_TYPE, "home")
        owner_id   = context.user_data.get(_K_OWNER_ID, 1)
        btype      = context.user_data.get(_K_BTN_TYPE, "text")
        row_index  = context.user_data.get(_K_ROW_INDEX)
        return pub_create_button(
            label=label,
            button_type=btype,
            value=value,
            home_id=owner_id        if owner_type == "home" else None,
            page_id=owner_id        if owner_type == "page" else None,
            target_page_id=target_page_id,
            row_index=row_index,
        )

    def _build_catalog_picker_kb(parent_id) -> InlineKeyboardMarkup:
        """בונה מקלדת לבחירת קטלוג כולל כפתור יצירת קטלוג חדש."""
        catalogs = get_all_catalogs()
        rows = [
            [InlineKeyboardButton(
                f"📂 {cat['name']}",
                callback_data=cb("page", "pick_catalog", cat["slug"]),
            )]
            for cat in catalogs
        ]
        rows.append([InlineKeyboardButton(
            "➕ צור קטלוג חדש",
            callback_data=cb("page", "create_catalog"),
        )])
        rows.append([InlineKeyboardButton(
            "◀️ ביטול",
            callback_data=cb("pages", "list", parent_id or "root"),
        )])
        return InlineKeyboardMarkup(rows)

    def _build_relink_catalog_kb(page_id: int) -> InlineKeyboardMarkup:
        """מקלדת לשינוי קישור הקטלוג של עמוד קיים — מציגה רק קטלוגים פעילים."""
        catalogs = get_all_catalogs()
        rows = [
            [InlineKeyboardButton(
                f"📂 {cat['name']}  ({cat['slug']})",
                callback_data=cb("catalog", "apply_relink", page_id, cat["slug"]),
            )]
            for cat in catalogs
        ]
        rows.append([InlineKeyboardButton(
            "◀️ ביטול",
            callback_data=cb("page", "view", page_id),
        )])
        return InlineKeyboardMarkup(rows)

    def _clear_state(context: ContextTypes.DEFAULT_TYPE) -> None:
        for key in (_K_BTN_ID, _K_PAGE_ID, _K_OWNER_TYPE, _K_OWNER_ID,
                    _K_BTN_TYPE, _K_NEW_LABEL, _K_NEW_PTYPE, _K_NEW_PARENT,
                    _K_DEL_TARGET, _K_TARGET_PG, _K_ROW_INDEX,
                    _K_NEW_TITLE, _K_NEW_CAT_NAME):
            context.user_data.pop(key, None)

    # ===================================================================
    # בניית ConversationHandler
    # ===================================================================

    text_msg  = filters.TEXT & ~filters.COMMAND
    media_msg = (
        filters.PHOTO | filters.ANIMATION | filters.VIDEO |
        filters.AUDIO | filters.VOICE | filters.Document.ALL |
        filters.VIDEO_NOTE | filters.Sticker.ALL
    )

    return ConversationHandler(
        entry_points=[
            CommandHandler(command, cmd_entry),
            CallbackQueryHandler(cb_main, pattern=r"^pub:main$"),
        ],
        states={
            S_MAIN_MENU: [
                CallbackQueryHandler(cb_home_menu,   pattern=r"^pub:home:menu$"),
                CallbackQueryHandler(cb_pages_list,  pattern=r"^pub:pages:list:"),
                CallbackQueryHandler(cb_close,       pattern=r"^pub:close$"),
            ],
            S_HOME_MENU: [
                CallbackQueryHandler(cb_home_edit_image,  pattern=r"^pub:home:edit_image$"),
                CallbackQueryHandler(cb_home_edit_text,   pattern=r"^pub:home:edit_text$"),
                CallbackQueryHandler(cb_home_clear_image, pattern=r"^pub:home:clear_image$"),
                CallbackQueryHandler(cb_home_toggle,      pattern=r"^pub:home:toggle$"),
                CallbackQueryHandler(cb_btn_list,         pattern=r"^pub:btn:list:"),
                CallbackQueryHandler(cb_main,             pattern=r"^pub:main$"),
            ],
            S_HOME_WAIT_IMAGE: [
                MessageHandler(media_msg, msg_home_image),
                CallbackQueryHandler(cb_home_menu, pattern=r"^pub:home:menu$"),
            ],
            S_HOME_WAIT_TEXT: [
                MessageHandler(text_msg, msg_home_text),
                CallbackQueryHandler(cb_home_menu, pattern=r"^pub:home:menu$"),
            ],
            S_PAGES_LIST: [
                CallbackQueryHandler(cb_page_view,  pattern=r"^pub:page:view:"),
                CallbackQueryHandler(cb_page_new,   pattern=r"^pub:page:new"),
                CallbackQueryHandler(cb_pages_list, pattern=r"^pub:pages:list:"),
                CallbackQueryHandler(cb_main,       pattern=r"^pub:main$"),
            ],
            S_PAGE_VIEW: [
                CallbackQueryHandler(cb_page_edit_title,       pattern=r"^pub:page:edit_title:"),
                CallbackQueryHandler(cb_page_edit_image,       pattern=r"^pub:page:edit_image:"),
                CallbackQueryHandler(cb_page_edit_text,        pattern=r"^pub:page:edit_text:"),
                CallbackQueryHandler(cb_page_toggle,           pattern=r"^pub:page:toggle:"),
                CallbackQueryHandler(cb_page_delete,           pattern=r"^pub:page:delete:"),
                CallbackQueryHandler(cb_page_move,             pattern=r"^pub:page:(up|down):"),
                CallbackQueryHandler(cb_page_view,             pattern=r"^pub:page:view:"),
                CallbackQueryHandler(cb_pages_list,            pattern=r"^pub:pages:list:"),
                CallbackQueryHandler(cb_btn_list,              pattern=r"^pub:btn:list:"),
                CallbackQueryHandler(cb_catalog_edit_audience, pattern=r"^pub:catalog:edit_audience:"),
                CallbackQueryHandler(cb_page_relink_catalog,   pattern=r"^pub:catalog:relink:"),
                CallbackQueryHandler(cb_main,                  pattern=r"^pub:main$"),
            ],
            S_PAGE_WAIT_TITLE: [
                MessageHandler(text_msg, msg_page_title),
                CallbackQueryHandler(cb_page_view,  pattern=r"^pub:page:view:"),
                CallbackQueryHandler(cb_pages_list, pattern=r"^pub:pages:list:"),
            ],
            _S_PAGE_WAIT_CATALOG: [
                CallbackQueryHandler(cb_page_catalog_pick,   pattern=r"^pub:page:pick_catalog:"),
                CallbackQueryHandler(cb_page_create_catalog, pattern=r"^pub:page:create_catalog$"),
                CallbackQueryHandler(cb_pages_list,          pattern=r"^pub:pages:list:"),
                CallbackQueryHandler(cb_main,                pattern=r"^pub:main$"),
            ],
            _S_PAGE_WAIT_NEW_CATALOG_NAME: [
                MessageHandler(text_msg, msg_page_new_catalog_name),
                CallbackQueryHandler(cb_pages_list, pattern=r"^pub:pages:list:"),
                CallbackQueryHandler(cb_main,       pattern=r"^pub:main$"),
            ],
            _S_PAGE_WAIT_CATALOG_AUDIENCE: [
                CallbackQueryHandler(cb_catalog_new_audience,   pattern=r"^pub:catalog:new_audience:"),
                CallbackQueryHandler(cb_catalog_apply_audience, pattern=r"^pub:catalog:apply_audience:"),
                CallbackQueryHandler(cb_page_view,              pattern=r"^pub:page:view:"),
                CallbackQueryHandler(cb_pages_list,             pattern=r"^pub:pages:list:"),
                CallbackQueryHandler(cb_main,                   pattern=r"^pub:main$"),
            ],
            _S_PAGE_RELINK_CATALOG: [
                CallbackQueryHandler(cb_page_apply_relink, pattern=r"^pub:catalog:apply_relink:"),
                CallbackQueryHandler(cb_page_view,         pattern=r"^pub:page:view:"),
                CallbackQueryHandler(cb_pages_list,        pattern=r"^pub:pages:list:"),
                CallbackQueryHandler(cb_main,              pattern=r"^pub:main$"),
            ],
            S_PAGE_WAIT_IMAGE: [
                MessageHandler(media_msg, msg_page_image),
                CallbackQueryHandler(cb_page_view,  pattern=r"^pub:page:view:"),
            ],
            S_PAGE_WAIT_TEXT: [
                MessageHandler(text_msg, msg_page_text),
                CallbackQueryHandler(cb_page_view,  pattern=r"^pub:page:view:"),
            ],
            S_BTN_LIST: [
                CallbackQueryHandler(cb_btn_view,  pattern=r"^pub:btn:view:"),
                CallbackQueryHandler(cb_btn_new,   pattern=r"^pub:btn:new:"),
                CallbackQueryHandler(cb_btn_list,  pattern=r"^pub:btn:list:"),
                CallbackQueryHandler(cb_home_menu, pattern=r"^pub:home:menu$"),
                CallbackQueryHandler(cb_page_view, pattern=r"^pub:page:view:"),
            ],
            S_BTN_SELECT_TYPE: [
                CallbackQueryHandler(cb_btn_set_type,   pattern=r"^pub:btn:set_type:"),
                CallbackQueryHandler(cb_btn_apply_type, pattern=r"^pub:btn:apply_type:"),
                CallbackQueryHandler(cb_btn_list,       pattern=r"^pub:btn:list:"),
            ],
            S_BTN_SELECT_PAGE: [
                CallbackQueryHandler(cb_btn_set_target, pattern=r"^pub:btn:set_target:"),
                CallbackQueryHandler(cb_btn_view,       pattern=r"^pub:btn:view:"),
                CallbackQueryHandler(cb_btn_list,       pattern=r"^pub:btn:list:"),
            ],
            S_BTN_VIEW: [
                CallbackQueryHandler(cb_btn_edit_label, pattern=r"^pub:btn:edit_label:"),
                CallbackQueryHandler(cb_btn_edit_value, pattern=r"^pub:btn:edit_value:"),
                CallbackQueryHandler(cb_btn_edit_type,  pattern=r"^pub:btn:edit_type:"),
                CallbackQueryHandler(cb_btn_toggle,     pattern=r"^pub:btn:toggle:"),
                CallbackQueryHandler(cb_btn_duplicate,  pattern=r"^pub:btn:duplicate:"),
                CallbackQueryHandler(cb_btn_add_to_row, pattern=r"^pub:btn:add_to_row:"),
                CallbackQueryHandler(cb_btn_move,       pattern=r"^pub:btn:(up|down|left|right):"),
                CallbackQueryHandler(cb_btn_delete,     pattern=r"^pub:btn:delete:"),
                CallbackQueryHandler(cb_btn_list,       pattern=r"^pub:btn:list:"),
            ],
            S_BTN_WAIT_LABEL: [
                MessageHandler(text_msg, msg_btn_label),
                CallbackQueryHandler(cb_btn_view, pattern=r"^pub:btn:view:"),
                CallbackQueryHandler(cb_btn_list, pattern=r"^pub:btn:list:"),
            ],
            S_BTN_WAIT_VALUE: [
                MessageHandler(text_msg, msg_btn_value),
                CallbackQueryHandler(cb_btn_view, pattern=r"^pub:btn:view:"),
            ],
            S_CONFIRM_DELETE: [
                CallbackQueryHandler(cb_confirm_delete_handler, pattern=r"^pub:confirm_delete$"),
                CallbackQueryHandler(cb_page_view,              pattern=r"^pub:page:view:"),
                CallbackQueryHandler(cb_btn_view,               pattern=r"^pub:btn:view:"),
            ],
        },
        fallbacks=[
            CommandHandler(command, cmd_entry),
            CallbackQueryHandler(cb_main, pattern=r"^pub:main$"),
        ],
        per_message=False,
        per_chat=True,
        per_user=True,
        allow_reentry=True,
        name="publishing_admin",
        persistent=False,
    )


# ---------------------------------------------------------------------------
# text builders -- פנימיים
# ---------------------------------------------------------------------------

def _home_text(home) -> str:
    status = "פעיל" if home["is_active"] else "כבוי"
    return (
        f"<b>דף הבית</b>\n"
        f"סטטוס: {status}\n"
        f"תמונה: {'יש' if home['image_file_id'] else 'אין'}\n"
        f"טקסט: {'יש' if home['text'] else 'אין'}"
    )


def _page_text(page, children_count: int) -> str:
    icon   = "קטלוג" if page["page_type"] == "catalog" else "עמוד"
    status = "פעיל" if page["is_active"] else "כבוי"
    lines  = [
        f"<b>{page['title']}</b> ({icon})",
        f"סטטוס: {status}",
        f"תמונה: {'יש' if page['image_file_id'] else 'אין'}",
        f"טקסט: {'יש' if page['text'] else 'אין'}",
        f"עמודי-בן: {children_count}",
    ]
    if page["page_type"] == "catalog":
        try:
            slug = page["catalog_slug"] or "(לא מוגדר)"
        except (IndexError, KeyError):
            slug = "(לא מוגדר)"
        lines.append(f"קטלוג מקושר: <code>{slug}</code>")
    return "\n".join(lines)


def _btn_text(btn) -> str:
    status = "פעיל" if btn["is_active"] else "כבוי"
    return (
        f"<b>{btn['label']}</b>\n"
        f"סוג: {BUTTON_TYPES.get(btn['button_type'], btn['button_type'])}\n"
        f"ערך: <code>{btn['value'] or 'אין'}</code>\n"
        f"סטטוס: {status}"
    )

