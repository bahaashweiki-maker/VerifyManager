from repositories.user_repository import (
    get_user_by_telegram_id,
    create_user,
)


def register_user(telegram_user):
    user = get_user_by_telegram_id(telegram_user.id)

    if user:
        return user

    create_user(
        telegram_id=telegram_user.id,
        full_name=telegram_user.full_name,
        username=telegram_user.username,
    )

    return get_user_by_telegram_id(telegram_user.id)