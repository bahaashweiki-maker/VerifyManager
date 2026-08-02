from __future__ import annotations

from repositories.subscribers_repository import (
    get_all_subscribers,
    get_subscribers_page,
    get_subscribers_count,
    touch_subscriber,
    search_subscribers,
    search_subscribers_page,
    count_subscribers_search,
    get_subscriber_by_id,
    get_subscriber_by_telegram_id,
    set_subscriber_status,
    delete_subscriber,
    add_subscriber_activity_event,
)
from services.verified_users_service import suspend_user, lift_suspension


def list_subscribers(limit: int = 50) -> list:
    return get_all_subscribers(limit=limit)


def list_subscribers_page(page: int, per_page: int = 10) -> list:
    return get_subscribers_page(page=page, per_page=per_page)


def count_subscribers() -> int:
    return get_subscribers_count()


def register_or_touch_subscriber(telegram_user) -> dict:
    return touch_subscriber(
        telegram_id=telegram_user.id,
        full_name=telegram_user.full_name,
        username=telegram_user.username,
    )


def get_subscriber_card_by_telegram_id(telegram_id: int):
    return get_subscriber_by_telegram_id(telegram_id)


def find_subscribers(term: str, limit: int = 50) -> list:
    return search_subscribers(term=term, limit=limit)


def find_subscribers_page(term: str, page: int, per_page: int = 10) -> list:
    return search_subscribers_page(term=term, page=page, per_page=per_page)


def count_subscribers_by_search(term: str) -> int:
    return count_subscribers_search(term=term)


def get_subscriber_card(subscriber_id: int):
    return get_subscriber_by_id(subscriber_id)


def suspend_subscriber(subscriber_id: int, performed_by: int | None = None) -> bool:
    subscriber = get_subscriber_by_id(subscriber_id)
    if not subscriber:
        return False

    status_ok = set_subscriber_status(subscriber_id, "suspended")
    suspension_ok = suspend_user(
        telegram_id=int(subscriber["telegram_id"]),
        duration_key="perm",
        reason="subscriptions_module",
        created_by=performed_by,
    )
    return status_ok and suspension_ok


def unsuspend_subscriber(subscriber_id: int, performed_by: int | None = None) -> bool:
    _ = performed_by
    subscriber = get_subscriber_by_id(subscriber_id)
    if not subscriber:
        return False

    status_ok = set_subscriber_status(subscriber_id, "active")
    suspension_ok = lift_suspension(int(subscriber["telegram_id"]))
    return status_ok and suspension_ok


def block_subscriber(subscriber_id: int, performed_by: int | None = None) -> bool:
    subscriber = get_subscriber_by_id(subscriber_id)
    if not subscriber:
        return False

    status_ok = set_subscriber_status(subscriber_id, "blocked")
    suspension_ok = suspend_user(
        telegram_id=int(subscriber["telegram_id"]),
        duration_key="perm",
        reason="subscriptions_block",
        created_by=performed_by,
    )
    return status_ok and suspension_ok


def unblock_subscriber(subscriber_id: int, performed_by: int | None = None) -> bool:
    _ = performed_by
    subscriber = get_subscriber_by_id(subscriber_id)
    if not subscriber:
        return False

    status_ok = set_subscriber_status(subscriber_id, "active")
    suspension_ok = lift_suspension(int(subscriber["telegram_id"]))
    return status_ok and suspension_ok


def remove_subscriber(subscriber_id: int) -> bool:
    return delete_subscriber(subscriber_id)


def track_subscriber_activity(
    subscriber_id: int,
    event_key: str,
    payload: str | None = None,
    increment_basic_activity: bool = True,
) -> bool:
    return add_subscriber_activity_event(
        subscriber_id=subscriber_id,
        event_key=event_key,
        payload=payload,
        increment_basic_activity=increment_basic_activity,
    )
