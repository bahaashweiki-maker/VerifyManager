"""
app/engine/publishing_renderer.py

פונקציות render למשתמש — דף הבית ועמודים.

רישום ב-app/bot.py:
    from app.engine.publishing_renderer import handle_user_nav, render_home
    # ניתוב pub:user: מתבצע בתוך button_click — ראה bot.py
"""

from __future__ import annotations

import logging
from typing import Optional

from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from repositories.home_repository import get_home
from repositories.pub_page_repository import pub_get_page_by_id, pub_get_pages_by_parent
from repositories.pub_button_repository import (
    pub_get_buttons_for_home,
    pub_get_buttons_for_page,
    pub_get_button_by_id,
)
from services.verified_users_service import (
    get_auto_catalogs_for_user,
    get_user_catalog_slugs,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# מעקב הודעת בית — מניעת הצפה בעת לחיצות חוזרות על /start
# ---------------------------------------------------------------------------
# מפתח: chat_id, ערך: message_id של הודעת הבית האחרונה.
# לפני כל שליחת בית — מוחקים את הקודמת אם קיימת.
_last_home_msg: dict[int, int] = {}


# ---------------------------------------------------------------------------
# כפתורי מערכת — חלק מליבת הבוט, לא ניתנים לניהול דרך מודול הפרסום.
# מוצגים תמיד בתחתית דף הבית, גם אם המנהל מחק את כל שאר הכפתורים.
#
# כדי להוסיף את כפתור הפרופיל בעתיד:
#   הוסף שורה: [InlineKeyboardButton("👤 הפרופיל שלי", callback_data="<callback_data_קיים>")]
# ---------------------------------------------------------------------------

_SYSTEM_BUTTONS: list[list[InlineKeyboardButton]] = [
    [InlineKeyboardButton("🪪 שלח אימות", callback_data="START_VERIFY")],
]


# ---------------------------------------------------------------------------
# המרת כפתור DB → InlineKeyboardButton
# ---------------------------------------------------------------------------

def _db_btn_to_tg(btn) -> Optional[InlineKeyboardButton]:
    """
    ממיר שורת publishing_buttons ל-InlineKeyboardButton.
    מחזיר None אם הסוג לא מוכר או חסר ערך הכרחי.
    """
    btype = btn["button_type"]
    label = btn["label"]
    value = btn["value"] or ""

    try:
        if btype == "text":
            return InlineKeyboardButton(label, callback_data=f"pub:user:msg:{btn['id']}")

        elif btype == "url":
            if not value.startswith(("http://", "https://", "tg://")):
                logger.warning("Button %d has invalid URL: %s", btn["id"], value)
                return None
            return InlineKeyboardButton(label, url=value)

        elif btype == "page_link":
            target = btn["target_page_id"] or value
            return InlineKeyboardButton(label, callback_data=f"pub:user:page:{target}")

        elif btype in ("phone", "email"):
            return InlineKeyboardButton(label, callback_data=f"pub:user:msg:{btn['id']}")

        elif btype == "location":
            return InlineKeyboardButton(label, callback_data=f"pub:user:loc:{btn['id']}")

        elif btype == "share":
            return InlineKeyboardButton(label, switch_inline_query="")

        else:
            logger.warning("Unknown button type '%s' for btn id=%d", btype, btn["id"])
            return None

    except Exception as exc:
        logger.error("_db_btn_to_tg failed for btn %d: %s", btn["id"], exc, exc_info=True)
        return None


# כפתור עם עד _SHORT_LABEL_MAX תווים נחשב "קצר" ומוזווג עם קצר אחר.
# כפתור ארוך יותר מקבל שורה מלאה לעצמו.
_SHORT_LABEL_MAX = 11


def _row_sort_key(btn) -> tuple:
    """מפתח מיון תואם sqlite3.Row — ללא שימוש ב-.get()."""
    row_index = btn["row_index"] or 0
    try:
        sort_order = btn["sort_order"]
        sort_order = sort_order if sort_order is not None else 0
    except IndexError:
        sort_order = 0
    return (row_index, sort_order)


def _build_keyboard(
    buttons: list,
    include_system: bool = False,
) -> InlineKeyboardMarkup:
    """
    בונה InlineKeyboardMarkup בפריסה מקצועית — greedy packing.

    כפתורים קצרים (label <= _SHORT_LABEL_MAX) מוזווגים לשורה אחת.
    כפתורים ארוכים מקבלים שורה מלאה לעצמם.
    כפתורים כבויים (is_active=0) מושמטים.
    כפתורי המערכת (_SYSTEM_BUTTONS) מוצמדים תמיד לתחתית כש-include_system=True.
    """
    active = [b for b in buttons if b["is_active"]]
    active.sort(key=_row_sort_key)

    rows: list[list[InlineKeyboardButton]] = []
    pending: Optional[InlineKeyboardButton] = None

    for btn in active:
        tg = _db_btn_to_tg(btn)
        if tg is None:
            continue
        is_short = len(tg.text) <= _SHORT_LABEL_MAX
        if is_short:
            if pending is not None:
                rows.append([pending, tg])
                pending = None
            else:
                pending = tg
        else:
            if pending is not None:
                rows.append([pending])
                pending = None
            rows.append([tg])

    if pending is not None:
        rows.append([pending])

    if include_system:
        rows.extend(_SYSTEM_BUTTONS)
    return InlineKeyboardMarkup(rows)


def _back_keyboard(btn) -> InlineKeyboardMarkup:
    """מקלדת עם כפתור חזור לעמוד המקור של כפתור התוכן."""
    page_id = btn["page_id"]
    back_cb = f"pub:user:page:{page_id}" if page_id else "pub:user:home"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("חזור", callback_data=back_cb)]
    ])


# ---------------------------------------------------------------------------
# _send_media — helper פנימי
# ---------------------------------------------------------------------------

async def _send_media(
    bot: Bot,
    chat_id: int,
    file_id: str,
    media_type: Optional[str],
    caption: str,
    keyboard: InlineKeyboardMarkup,
):
    """
    שולח מדיה לפי media_type ומחזיר את אובייקט ה-Message.

    media_type:
        "photo"      -> send_photo
        "animation"  -> send_animation
        "video"      -> send_video
        "audio"      -> send_audio
        "voice"      -> send_voice
        "document"   -> send_document
        "video_note" -> send_video_note  (ללא caption/parse_mode)
        "sticker"    -> send_sticker     (ללא caption/parse_mode)
        כל ערך אחר / None -> send_photo (ברירת מחדל)
    """
    kwargs = dict(
        chat_id=chat_id,
        caption=caption,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    kwargs_no_caption = dict(
        chat_id=chat_id,
        reply_markup=keyboard,
    )

    if media_type == "animation":
        return await bot.send_animation(animation=file_id, **kwargs)
    elif media_type == "video":
        return await bot.send_video(video=file_id, **kwargs)
    elif media_type == "audio":
        return await bot.send_audio(audio=file_id, **kwargs)
    elif media_type == "voice":
        return await bot.send_voice(voice=file_id, **kwargs)
    elif media_type == "document":
        return await bot.send_document(document=file_id, **kwargs)
    elif media_type == "video_note":
        return await bot.send_video_note(video_note=file_id, **kwargs_no_caption)
    elif media_type == "sticker":
        return await bot.send_sticker(sticker=file_id, **kwargs_no_caption)
    else:
        return await bot.send_photo(photo=file_id, **kwargs)


# ---------------------------------------------------------------------------
# render_home
# ---------------------------------------------------------------------------

async def render_home(
    bot: Bot,
    chat_id: int,
) -> None:
    """
    שולח את דף הבית למשתמש.

    לפני שליחה — מוחק את הודעת הבית הקודמת של אותו chat_id.
    אם דף הבית לא מוגדר או כבוי — שולח הודעת ברירת-מחדל עם כפתורי מערכת בלבד.
    """
    prev_msg_id = _last_home_msg.pop(chat_id, None)
    if prev_msg_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=prev_msg_id)
        except Exception:
            pass

    try:
        _raw  = get_home()
        home  = dict(_raw) if _raw is not None else None
        text  = "ברוך הבא!"
        image = None

        if home and home["is_active"]:
            text     = home["text"] or text
            image    = home["image_file_id"]
            buttons  = pub_get_buttons_for_home(1)
            keyboard = _build_keyboard(buttons, include_system=True)
        else:
            keyboard = InlineKeyboardMarkup(_SYSTEM_BUTTONS)

        if image:
            msg = await _send_media(
                bot, chat_id, image,
                media_type=home.get("media_type"),
                caption=text,
                keyboard=keyboard,
            )
        else:
            msg = await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )

        if msg:
            _last_home_msg[chat_id] = msg.message_id

    except TelegramError as exc:
        logger.error("render_home failed for chat_id=%d: %s", chat_id, exc, exc_info=True)


# ---------------------------------------------------------------------------
# _get_allowed_slugs
# ---------------------------------------------------------------------------

def _get_allowed_slugs(telegram_id: int) -> set:
    """
    מחזיר קבוצת catalog slugs שהמשתמש מורשה לגשת אליהם.

    מקורות:
      - get_auto_catalogs_for_user: קטלוגים לפי audience/סוג-משתמש
      - get_user_catalog_slugs: קטלוגים שהוקצו ידנית

    בכשל — מחזיר קבוצה ריקה (fail-closed).
    """
    try:
        auto_catalogs = get_auto_catalogs_for_user(telegram_id)
        manual_slugs  = get_user_catalog_slugs(telegram_id)
        auto_slugs    = {cat["slug"] for cat in auto_catalogs}
        combined      = auto_slugs | manual_slugs
        print(f"[AUTH-DEBUG] _get_allowed_slugs(telegram_id={telegram_id})")
        print(f"[AUTH-DEBUG]   auto_slugs={auto_slugs}")
        print(f"[AUTH-DEBUG]   manual_slugs={manual_slugs}")
        print(f"[AUTH-DEBUG]   combined allowed={combined}")
        return combined
    except Exception as exc:
        print(f"[AUTH-DEBUG] _get_allowed_slugs(telegram_id={telegram_id}) EXCEPTION: {exc}")
        logger.error(
            "_get_allowed_slugs failed for telegram_id=%s: %s", telegram_id, exc
        )
        return set()


# ---------------------------------------------------------------------------
# _filter_pages_for_user
# ---------------------------------------------------------------------------

def _filter_pages_for_user(
    pages: list,
    telegram_id: Optional[int],
    allowed_slugs: Optional[set] = None,
) -> list:
    """
    מסנן רשימת עמודים לפי הרשאות המשתמש.

    כללי סינון:
      - page_type != 'catalog'  -> תמיד מוצג
      - catalog_slug חסר/ריק   -> תמיד מוצג (תאימות לאחור)
      - catalog_slug קיים       -> מוצג אם ה-slug נמצא ב-allowed_slugs

    אם telegram_id הוא None — מחזיר את הרשימה ללא סינון.
    """
    if telegram_id is None:
        return pages

    catalog_pages_with_slug = [
        p for p in pages
        if p["page_type"] == "catalog" and p["catalog_slug"]
    ]
    if not catalog_pages_with_slug:
        return pages

    if allowed_slugs is None:
        try:
            allowed_slugs = _get_allowed_slugs(telegram_id)
        except Exception as exc:
            logger.error("_filter_pages_for_user failed for telegram_id=%s: %s", telegram_id, exc)
            return [p for p in pages if p["page_type"] != "catalog" or not p["catalog_slug"]]

    result = []
    for page in pages:
        if page["page_type"] != "catalog":
            result.append(page)
        elif not page["catalog_slug"]:
            result.append(page)
        elif page["catalog_slug"] in allowed_slugs:
            result.append(page)

    return result


# ---------------------------------------------------------------------------
# _filter_buttons_for_user
# ---------------------------------------------------------------------------

def _filter_buttons_for_user(
    buttons: list,
    telegram_id: Optional[int],
    allowed_slugs: Optional[set] = None,
) -> list:
    """
    מסנן כפתורי page_link שמובילים לקטלוגים שהמשתמש אינו מורשה לגשת אליהם.

    כללי סינון:
      - כפתורים שאינם page_link              -> תמיד מוצגים
      - page_link ללא target_page_id          -> תמיד מוצגים
      - page_link שיעדו אינו קטלוג עם slug   -> תמיד מוצגים
      - page_link שיעדו קטלוג עם slug חסום  -> מושמטים

    אם telegram_id הוא None — מחזיר את הרשימה ללא סינון.
    """
    if telegram_id is None:
        return buttons

    link_buttons = [
        btn for btn in buttons
        if btn["button_type"] == "page_link" and btn["target_page_id"]
    ]
    if not link_buttons:
        return buttons

    if allowed_slugs is None:
        allowed_slugs = _get_allowed_slugs(telegram_id)

    blocked_target_ids: set = set()
    for btn in link_buttons:
        target_raw = pub_get_page_by_id(btn["target_page_id"])
        if target_raw is None:
            continue
        if target_raw["page_type"] == "catalog" and target_raw["catalog_slug"]:
            if target_raw["catalog_slug"] not in allowed_slugs:
                blocked_target_ids.add(btn["target_page_id"])

    if not blocked_target_ids:
        return buttons

    return [
        btn for btn in buttons
        if not (
            btn["button_type"] == "page_link"
            and btn["target_page_id"] in blocked_target_ids
        )
    ]


# ---------------------------------------------------------------------------
# render_page
# ---------------------------------------------------------------------------

async def render_page(
    bot: Bot,
    chat_id: int,
    page_id: int,
    telegram_id: Optional[int] = None,
) -> bool:
    """
    שולח עמוד פרסום למשתמש כהודעה חדשה.

    Returns:
        True אם הצליח, False בכשל.
    """
    try:
        _raw = pub_get_page_by_id(page_id)
        if _raw is None or not _raw["is_active"]:
            return False
        page = dict(_raw)

        allowed_slugs: Optional[set] = None
        if telegram_id is not None:
            allowed_slugs = _get_allowed_slugs(telegram_id)

        page_slug = page.get("catalog_slug")
        if page_slug and telegram_id is not None:
            if allowed_slugs is not None and page_slug not in allowed_slugs:
                logger.info(
                    "render_page: access denied telegram_id=%s page_id=%d slug=%s",
                    telegram_id, page_id, page_slug,
                )
                return False

        active_sub = [dict(p) for p in pub_get_pages_by_parent(page_id) if p["is_active"]]
        sub_pages  = _filter_pages_for_user(active_sub, telegram_id, allowed_slugs)
        nav_rows: list[list[InlineKeyboardButton]] = [
            [InlineKeyboardButton(
                f"{'📂' if sp['page_type'] == 'catalog' else '📄'} {sp['title']}",
                callback_data=f"pub:user:page:{sp['id']}",
            )]
            for sp in sub_pages
        ]

        buttons = pub_get_buttons_for_page(page_id)
        buttons = _filter_buttons_for_user(buttons, telegram_id, allowed_slugs)
        db_kb   = _build_keyboard(buttons, include_system=False)

        back_cb = (
            f"pub:user:page:{page['parent_id']}"
            if page["parent_id"]
            else "pub:user:home"
        )
        all_rows = (
            nav_rows
            + list(db_kb.inline_keyboard)
            + [[InlineKeyboardButton("חזור", callback_data=back_cb)]]
        )
        keyboard = InlineKeyboardMarkup(all_rows)

        caption = f"<b>{page['title']}</b>"
        if page["text"]:
            caption += f"\n\n{page['text']}"
        image = page["image_file_id"]

        if image:
            await _send_media(
                bot, chat_id, image,
                media_type=page.get("media_type"),
                caption=caption,
                keyboard=keyboard,
            )
        else:
            await bot.send_message(
                chat_id=chat_id,
                text=caption,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        return True

    except TelegramError as exc:
        logger.error(
            "render_page failed for chat_id=%d page_id=%d: %s",
            chat_id, page_id, exc, exc_info=True,
        )
        return False


# ---------------------------------------------------------------------------
# handle_user_nav — callback handler לניווט משתמש
# ---------------------------------------------------------------------------

async def handle_user_nav(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    מטפל בכל callback_data שמתחיל ב-pub:user:.

    Patterns:
        pub:user:home         — דף הבית
        pub:user:page:<id>    — ניווט לעמוד
        pub:user:msg:<btn_id> — שליחת הודעה (text / phone / email)
        pub:user:loc:<btn_id> — שליחת מיקום

    עקבי עם PageEngine: מוחק את ההודעה הקיימת ושולח הודעה חדשה.
    """
    query = update.callback_query
    parts   = query.data.split(":")
    action  = parts[2] if len(parts) > 2 else ""
    bot     = context.bot
    chat_id = query.message.chat_id

    if action == "page" and len(parts) > 3:
        page_id = int(parts[3])
        _raw    = pub_get_page_by_id(page_id)
        if _raw is not None and _raw["is_active"]:
            page_slug = _raw["catalog_slug"]
            print(f"[AUTH-DEBUG] handle_user_nav page action")
            print(f"[AUTH-DEBUG]   telegram_id={query.from_user.id!r}, page_id={page_id}")
            print(f"[AUTH-DEBUG]   page_slug from DB={page_slug!r}  (type={type(page_slug).__name__})")
            if page_slug:
                allowed = _get_allowed_slugs(query.from_user.id)
                print(f"[AUTH-DEBUG]   COMPARISON: page_slug={page_slug!r}  in allowed={allowed}  result={page_slug in allowed}")
                if page_slug not in allowed:
                    print(f"[AUTH-DEBUG]   ACCESS DENIED returning lock")
                    await query.answer(
                        "אין לך הרשאה לצפות בתוכן זה.",
                        show_alert=True,
                    )
                    return
            else:
                print(f"[AUTH-DEBUG]   page_slug is empty/None — no access check needed")
        await query.answer()
        try:
            await query.message.delete()
        except TelegramError:
            pass
        await render_page(bot, chat_id, page_id, telegram_id=query.from_user.id)
        return

    await query.answer()
    try:
        await query.message.delete()
    except TelegramError:
        pass

    if action == "home":
        await render_home(bot, chat_id)

    elif action == "page" and len(parts) > 3:
        await render_page(bot, chat_id, int(parts[3]), telegram_id=query.from_user.id)

    elif action == "msg" and len(parts) > 3:
        btn = pub_get_button_by_id(int(parts[3]))
        if btn and btn["value"]:
            btype   = btn["button_type"]
            val     = btn["value"]
            back_kb = _back_keyboard(btn)
            if btype == "text":
                await bot.send_message(chat_id, val, parse_mode="HTML", reply_markup=back_kb)
            elif btype == "phone":
                await bot.send_message(chat_id, f"📞 {val}", reply_markup=back_kb)
            elif btype == "email":
                await bot.send_message(chat_id, f"📧 {val}", reply_markup=back_kb)

    elif action == "loc" and len(parts) > 3:
        btn = pub_get_button_by_id(int(parts[3]))
        if btn and btn["value"]:
            back_kb = _back_keyboard(btn)
            try:
                lat_s, lon_s = btn["value"].split(",")
                await bot.send_location(
                    chat_id,
                    latitude=float(lat_s.strip()),
                    longitude=float(lon_s.strip()),
                    reply_markup=back_kb,
                )
            except (ValueError, TelegramError) as exc:
                logger.error("handle_user_nav loc failed for btn %s: %s", parts[3], exc)