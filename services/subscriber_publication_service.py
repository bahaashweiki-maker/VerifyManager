from __future__ import annotations

from repositories.subscriber_publications_repository import (
    get_all_publications,
    get_publication_buttons,
)


def list_publications(limit: int = 50) -> list:
    return get_all_publications(limit=limit)


def list_publication_buttons(publication_id: int) -> list:
    return get_publication_buttons(publication_id)
