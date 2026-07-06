from repositories.button_repository import (
    get_buttons,
)


def load_buttons(page_key: str):
    return get_buttons(page_key)