from __future__ import annotations

from repositories.subscriber_stats_repository import (
    get_subscriber_activity,
    get_global_stats_snapshots,
    get_subscriber_personal_stats,
)


def get_subscriber_stats_activity(subscriber_id: int, limit: int = 50) -> list:
    return get_subscriber_activity(subscriber_id=subscriber_id, limit=limit)


def get_subscription_system_stats(limit: int = 30) -> list:
    return get_global_stats_snapshots(limit=limit)


def get_subscriber_personal_statistics(subscriber_id: int) -> dict:
    return get_subscriber_personal_stats(subscriber_id)
