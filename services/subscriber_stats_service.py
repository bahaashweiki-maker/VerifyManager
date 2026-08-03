from __future__ import annotations

from repositories.subscriber_stats_repository import (
    get_subscriber_activity,
    get_global_stats_snapshots,
    get_live_subscription_system_stats,
    get_subscriber_personal_stats,
    reset_global_action_stats,
    reset_subscriber_personal_stats,
)


def get_subscriber_stats_activity(subscriber_id: int, limit: int = 50) -> list:
    return get_subscriber_activity(subscriber_id=subscriber_id, limit=limit)


def get_subscription_system_stats(limit: int = 30) -> list:
    return get_global_stats_snapshots(limit=limit)


def get_subscription_system_stats_live() -> dict:
    return get_live_subscription_system_stats()


def get_subscriber_personal_statistics(subscriber_id: int) -> dict:
    return get_subscriber_personal_stats(subscriber_id)


def reset_personal_stats(subscriber_id: int) -> bool:
    return reset_subscriber_personal_stats(subscriber_id)


def reset_global_stats_actions() -> bool:
    return reset_global_action_stats()
