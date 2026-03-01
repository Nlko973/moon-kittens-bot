from __future__ import annotations

from typing import Optional

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import User

from app.runtime import bot
from app.services.chat_settings import get_group_id
from app.texts import format_user
from db import get_known_user_ids

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
        pass
    except Exception:
        pass

    # Fast fallback: scan current chat administrators by live username.
    try:
        admins = await bot.get_chat_administrators(get_group_id())
        for admin in admins:
            u = admin.user
            remember_user(u)
            if u and u.username and u.username.lower() == key:
                _USERNAME_TO_ID[key] = int(u.id)
                return int(u.id)
    except Exception:
        pass

    # Deep fallback: resolve by known Telegram IDs from DB and live profile lookup.
    # We only store IDs in DB, usernames are checked in real time.
    for user_id in get_known_user_ids(limit=1200, members_first=True):
        try:
            member = await bot.get_chat_member(get_group_id(), int(user_id))
            u = member.user
            remember_user(u)
            if u and u.username and u.username.lower() == key:
                _USERNAME_TO_ID[key] = int(u.id)
                return int(u.id)
        except TelegramBadRequest:
            continue
        except Exception:
            continue
    return None


async def resolve_user_label(user_id: int, fallback: Optional[str] = None) -> str:
    try:
        member = await bot.get_chat_member(get_group_id(), user_id)
        user = member.user
        remember_user(user)
        return format_user(user_id, user.username, user.full_name or fallback or str(user_id))
    except Exception:
        pass
    return format_user(user_id, None, fallback or str(user_id))
