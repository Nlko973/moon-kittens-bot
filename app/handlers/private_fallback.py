from aiogram import Router
from aiogram.enums import ChatType
from aiogram.types import Message

from app.services.access import DENIED_TEXT, is_bot_admin

router = Router()


@router.message()
async def private_fallback(message: Message):
    if message.chat.type != ChatType.PRIVATE:
        return
    if is_bot_admin(message.from_user.id):
        await message.answer("Не понял команду. Нажмите кнопку в меню.")
        return
    await message.answer(DENIED_TEXT)
