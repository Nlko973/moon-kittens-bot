from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery

from app.runtime import bot
from app.services.access import is_bot_admin
from app.services.chat_settings import get_group_id
from app.services.moderation import unmute_user
from config import OWNER_ID
from db import remove_mute

router = Router()


@router.callback_query(F.data.startswith("owner_unmute:"))
async def cb_owner_unmute(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID and not is_bot_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    user_id = int(callback.data.split(":", maxsplit=1)[1])
    text = await unmute_user(user_id)
    await callback.message.answer(f"Действие владельца: {text}")
    await callback.answer("Готово")


@router.callback_query(F.data.startswith("owner_ban:"))
async def cb_owner_ban(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID and not is_bot_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    user_id = int(callback.data.split(":", maxsplit=1)[1])
    try:
        await bot.ban_chat_member(get_group_id(), user_id)
        remove_mute(user_id)
        await callback.message.answer("Действие владельца: пользователь забанен.")
    except TelegramBadRequest as exc:
        await callback.message.answer(f"Действие владельца: ошибка бана ({exc.message}).")
    await callback.answer("Готово")
