"""
repositories/merchant_channels_repository.py
-------------------------------------------
Repository for globally managed merchant publication channels.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from typing import Optional

from database.database import get_connection
from repositories.merchant_publication_repository import normalize_channel_key

logger = logging.getLogger(__name__)

_TME_URL_RE = re.compile(r"https?://t\.me/[^\s]+", re.IGNORECASE)
_HANDLE_RE = re.compile(r"@[A-Za-z0-9_]{4,}")
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{4,}$")
_PRIVATE_CHAT_ID_RE = re.compile(r"^-100\d{6,}$")


def _extract_channel_ref_token(raw_ref: str) -> str | None:
    text = (raw_ref or "").strip()
    if not text:
        return None

    m = _TME_URL_RE.search(text)
    if m:
        return m.group(0)

    m = _HANDLE_RE.search(text)
    if m:
        return m.group(0)

    if _PRIVATE_CHAT_ID_RE.match(text):
        return text

    return text


def _extract_display_name(raw_value: str, explicit_name: str, ref_token: str | None) -> str:
    if explicit_name:
        return explicit_name
    if not raw_value:
        return ""
    if ref_token and ref_token in raw_value:
        left = raw_value.replace(ref_token, " ").strip(" |\t-\n\r")
        if left:
            return left
    return ref_token or raw_value


def _clean_display_name(display_name: str, channel_ref: str) -> str:
    name = (display_name or "").strip()
    ref = (channel_ref or "").strip()
    if not name:
        return name

    if ref and ref in name:
        left = name.replace(ref, " ").strip(" |\t-\n\r")
        if left:
            return left

    m = _TME_URL_RE.search(name)
    if m:
        left = name.replace(m.group(0), " ").strip(" |\t-\n\r")
        if left:
            return left

    return name


def _normalize_row(channel: dict) -> dict:
    row = dict(channel)
    row["display_name"] = _clean_display_name(
        str(row.get("display_name") or ""),
        str(row.get("channel_ref") or ""),
    ) or str(row.get("display_name") or "")
    return row


def _invite_code_from_url(url: str) -> str | None:
    url = url.strip()
    plus_marker = "t.me/+"
    if plus_marker in url:
        code = url.split(plus_marker, 1)[1].split("?", 1)[0].split("#", 1)[0].strip("/")
        return code or None
    joinchat_marker = "t.me/joinchat/"
    if joinchat_marker in url:
        code = url.split(joinchat_marker, 1)[1].split("?", 1)[0].split("#", 1)[0].strip("/")
        return code or None
    return None


def _slug_from_tme_url(url: str) -> str | None:
    clean = url.strip().rstrip("/")
    marker = "t.me/"
    if marker not in clean:
        return None
    slug = clean.split(marker, 1)[1].split("?", 1)[0].split("#", 1)[0].strip("/")
    if not slug or slug.startswith("+") or slug.startswith("joinchat/") or slug.startswith("c/"):
        return None
    return slug


def _normalize_handle(token: str) -> str | None:
    raw = (token or "").strip()
    if not raw:
        return None
    if raw.startswith("@") and _USERNAME_RE.match(raw[1:]):
        return raw
    if _USERNAME_RE.match(raw):
        return f"@{raw}"
    return None


def _parse_channel_ref_targets(raw_ref: str) -> tuple[str | None, str | None, bool]:
    text = (raw_ref or "").strip()
    if not text:
        return None, None, False

    tokens = [part.strip() for part in text.split("|") if part.strip()]
    if not tokens:
        tokens = [text]

    join_ref: str | None = None
    membership_ref: str | None = None
    explicit_membership = False

    for token in tokens:
        if _PRIVATE_CHAT_ID_RE.match(token):
            membership_ref = token
            explicit_membership = True
            continue

        handle = _normalize_handle(token)
        if handle:
            if not join_ref:
                join_ref = handle
            if not membership_ref:
                membership_ref = handle
            explicit_membership = True
            continue

        if token.startswith("tg://"):
            if not join_ref:
                join_ref = token
            continue

        if token.startswith(("http://", "https://")):
            if not join_ref:
                join_ref = token
            slug = _slug_from_tme_url(token)
            if slug and not membership_ref:
                membership_ref = f"@{slug}"
            continue

        token_ref = _extract_channel_ref_token(token)
        if token_ref and token_ref != token:
            derived_join, derived_membership, derived_explicit = _parse_channel_ref_targets(token_ref)
            if not join_ref and derived_join:
                join_ref = derived_join
            if not membership_ref and derived_membership:
                membership_ref = derived_membership
            explicit_membership = explicit_membership or derived_explicit

    return join_ref, membership_ref, explicit_membership


def _row_factory(cursor, row):
    fields = [d[0] for d in cursor.description]
    return dict(zip(fields, row))


def create_channel(channel_ref: str, display_name: str | None = None) -> int:
    raw_value = (channel_ref or "").strip()
    custom_name = (display_name or "").strip()
    if not custom_name and "|" in raw_value:
        parts = [part.strip() for part in raw_value.split("|") if part.strip()]
        if len(parts) >= 2:
            custom_name = parts[0]
            raw_value = " | ".join(parts[1:])

    join_ref, membership_ref, explicit_membership = _parse_channel_ref_targets(raw_value)
    key_source = membership_ref or join_ref or (_extract_channel_ref_token(raw_value) or raw_value)
    channel_key = normalize_channel_key(key_source)
    if not channel_key:
        return 0

    if explicit_membership and join_ref and membership_ref and membership_ref != join_ref:
        normalized_ref = f"{join_ref} | {membership_ref}"
    else:
        normalized_ref = join_ref or membership_ref or (_extract_channel_ref_token(raw_value) or raw_value)

    first_token = _extract_channel_ref_token(raw_value) or join_ref or membership_ref
    channel_name = _extract_display_name(raw_value, custom_name, first_token) or channel_key

    try:
        with get_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO merchant_publication_channels (
                    display_name,
                    channel_key,
                    channel_ref,
                    is_active
                )
                VALUES (?, ?, ?, 1)
                ON CONFLICT(channel_key) DO UPDATE
                    SET display_name = excluded.display_name,
                        channel_ref = excluded.channel_ref,
                        is_active = 1
                """,
                (channel_name, channel_key, normalized_ref),
            )
            conn.commit()
            if cur.lastrowid:
                return int(cur.lastrowid)

            row = conn.execute(
                "SELECT id FROM merchant_publication_channels WHERE channel_key = ? LIMIT 1",
                (channel_key,),
            ).fetchone()
            return int(row[0]) if row else 0
    except sqlite3.Error as exc:
        logger.error("create_channel(%s) failed: %s", channel_ref, exc)
        return 0


def list_channels(active_only: bool = True) -> list[dict]:
    where_sql = "WHERE is_active = 1" if active_only else ""
    try:
        with get_connection() as conn:
            conn.row_factory = _row_factory
            rows = conn.execute(
                f"""
                SELECT *
                FROM merchant_publication_channels
                {where_sql}
                ORDER BY display_name COLLATE NOCASE ASC, id ASC
                """
            ).fetchall()
        return [_normalize_row(row) for row in rows]
    except sqlite3.Error as exc:
        logger.error("list_channels failed: %s", exc)
        return []


def get_channel_by_id(channel_id: int) -> Optional[dict]:
    try:
        with get_connection() as conn:
            conn.row_factory = _row_factory
            row = conn.execute(
                "SELECT * FROM merchant_publication_channels WHERE id = ? LIMIT 1",
                (channel_id,),
            ).fetchone()
        return _normalize_row(row) if row else None
    except sqlite3.Error as exc:
        logger.error("get_channel_by_id(%s) failed: %s", channel_id, exc)
        return None


def get_channel_by_key(channel_key: str) -> Optional[dict]:
    try:
        with get_connection() as conn:
            conn.row_factory = _row_factory
            row = conn.execute(
                "SELECT * FROM merchant_publication_channels WHERE channel_key = ? LIMIT 1",
                (normalize_channel_key(channel_key),),
            ).fetchone()
        return _normalize_row(row) if row else None
    except sqlite3.Error as exc:
        logger.error("get_channel_by_key(%s) failed: %s", channel_key, exc)
        return None


def list_channels_by_keys(channel_keys: list[str]) -> list[dict]:
    if not channel_keys:
        return []

    normalized_keys: list[str] = []
    for key in channel_keys:
        normalized = normalize_channel_key(key)
        if normalized and normalized not in normalized_keys:
            normalized_keys.append(normalized)
    if not normalized_keys:
        return []

    placeholders = ",".join("?" for _ in normalized_keys)
    try:
        with get_connection() as conn:
            conn.row_factory = _row_factory
            rows = conn.execute(
                f"""
                SELECT *
                FROM merchant_publication_channels
                WHERE channel_key IN ({placeholders})
                  AND is_active = 1
                """,
                tuple(normalized_keys),
            ).fetchall()
        by_key = {row["channel_key"]: _normalize_row(row) for row in rows}
        return [by_key[key] for key in normalized_keys if key in by_key]
    except sqlite3.Error as exc:
        logger.error("list_channels_by_keys failed: %s", exc)
        return []


def get_channel_join_url(channel: dict) -> str | None:
    raw_ref = str(channel.get("channel_ref") or "")
    join_ref, membership_ref, _ = _parse_channel_ref_targets(raw_ref)
    ref = join_ref or membership_ref
    if not ref:
        return None
    if ref.startswith("tg://"):
        return ref
    if ref.startswith(("http://", "https://")):
        invite_code = _invite_code_from_url(ref)
        if invite_code:
            return f"tg://join?invite={invite_code}"
        slug = _slug_from_tme_url(ref)
        if slug:
            return f"tg://resolve?domain={slug}"
        return ref
    if ref.startswith("@"):
        return f"tg://resolve?domain={ref[1:]}"
    if ref.startswith("-100"):
        return None
    return f"tg://resolve?domain={ref}"


def get_channel_membership_chat_ref(channel: dict) -> str | None:
    raw_ref = str(channel.get("channel_ref") or "")
    join_ref, membership_ref, _ = _parse_channel_ref_targets(raw_ref)
    ref = membership_ref or join_ref
    if not ref:
        return None
    if ref.startswith("@") or ref.startswith("-100"):
        return ref
    if ref.startswith(("http://", "https://")):
        slug = _slug_from_tme_url(ref)
        if not slug:
            return None
        return f"@{slug}"
    if _USERNAME_RE.match(ref):
        return f"@{ref}"
    return None


def deactivate_channel(channel_id: int) -> bool:
    try:
        with get_connection() as conn:
            cur = conn.execute(
                """
                UPDATE merchant_publication_channels
                SET is_active = 0
                WHERE id = ?
                """,
                (channel_id,),
            )
            conn.commit()
        return cur.rowcount > 0
    except sqlite3.Error as exc:
        logger.error("deactivate_channel(%s) failed: %s", channel_id, exc)
        return False
