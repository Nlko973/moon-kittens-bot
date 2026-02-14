from aiogram.enums import ChatType
from aiogram.types import Message

from config import OWNER_ID
from db import is_admin


def is_private(message: Message) -> bool:
    return message.chat.type == ChatType.PRIVATE


def is_bot_admin(user_id: int) -> bool:
    return is_admin(user_id, OWNER_ID)


async def require_private_admin(message: Message) -> bool:
    if not is_private(message):
        return False
    if not is_bot_admin(message.from_user.id):
        return False
    return True


async def require_owner(message: Message) -> bool:
    if not is_private(message):
        return False
    if message.from_user.id != OWNER_ID:
        return False
    return True
