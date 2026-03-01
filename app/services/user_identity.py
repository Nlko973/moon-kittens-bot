from __future__ import annotations

from typing import Optional

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import User

from app.runtime import bot
from app.services.chat_settings import get_group_id

_USERNAME_TO_ID: dict[str, int] = {}


def remember_user(user: Optional[User]):
    if not user:
        return
    if user.username:
        _USERNAME_TO_ID[user.username.lower()] = user.id


async def resolve_user_id_by_username(username: str) -> Optional[int]:
    key = username.lstrip("@").strip().lower()
    if not key:
        return None
    if key in _USERNAME_TO_ID:
        return _USERNAME_TO_ID[key]

    # Best-effort live lookup. For many users Telegram may not resolve here.
    try:
        chat = await bot.get_chat(f"@{key}")
        if chat and chat.id:
            _USERNAME_TO_ID[key] = int(chat.id)
            return int(chat.id)
    except TelegramBadRequest:
        return None
    except Exception:
        return None
    return None


async def resolve_user_label(user_id: int, fallback: Optional[str] = None) -> str:
    try:
        member = await bot.get_chat_member(get_group_id(), user_id)
        user = member.user
        remember_user(user)
        if user.username:
            return f"@{user.username}"
        if user.full_name:
            return user.full_name
    except Exception:
        pass
    return fallback or str(user_id)
