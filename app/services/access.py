from aiogram.enums import ChatType
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import OWNER_ID
from db import get_flood_info_channel_url, is_admin, is_bot_access_blocked, user_exists_in_db


DENIED_TEXT = "нет доступа"
BOT_ACCESS_BLOCKED_TEXT = "вам ограничили доступ к боту"
NON_MEMBER_TEXT = (
    "напишите хотя бы одно сообщение во флуд если вы в нём уже находитесь , "
    "бот только для участников флуда"
)


def is_private(message: Message) -> bool:
    return message.chat.type == ChatType.PRIVATE


def is_bot_admin(user_id: int) -> bool:
    return is_admin(user_id, OWNER_ID)


def info_channel_keyboard() -> InlineKeyboardMarkup | None:
    url = get_flood_info_channel_url()
    if not url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="инфо канал флуда", url=url)],
        ]
    )


async def answer_non_member(message: Message):
    await message.answer(NON_MEMBER_TEXT, reply_markup=info_channel_keyboard())


async def ensure_private_user_access(message: Message) -> bool:
    if not is_private(message):
        return False
    user_id = message.from_user.id
    if is_bot_access_blocked(user_id):
        await message.answer(BOT_ACCESS_BLOCKED_TEXT)
        return False
    if is_bot_admin(user_id):
        return True
    if not user_exists_in_db(user_id, members_only=True):
        await answer_non_member(message)
        return False
    return True


async def require_private_admin(message: Message) -> bool:
    if not is_private(message):
        return False
    if is_bot_access_blocked(message.from_user.id):
        await message.answer(BOT_ACCESS_BLOCKED_TEXT)
        return False
    if not is_bot_admin(message.from_user.id):
        await message.answer(DENIED_TEXT)
        return False
    return True


async def require_owner(message: Message) -> bool:
    if not is_private(message):
        return False
    if is_bot_access_blocked(message.from_user.id):
        await message.answer(BOT_ACCESS_BLOCKED_TEXT)
        return False
    if message.from_user.id != OWNER_ID:
        await message.answer(DENIED_TEXT)
        return False
    return True
