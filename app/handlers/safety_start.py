from aiogram import Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message

from app.keyboards import private_user_kb
from app.services.access import is_bot_admin
from app.texts import START_TEXT

router = Router()


@router.message(Command("start"))
async def safety_start(message: Message):
    if message.chat.type != ChatType.PRIVATE:
        return
    await message.answer(
        START_TEXT,
        reply_markup=private_user_kb(is_admin=is_bot_admin(message.from_user.id)),
    )
