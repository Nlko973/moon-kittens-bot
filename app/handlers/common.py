from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.keyboards import BTN_ADMIN_HELP, BTN_MENU, private_menu_kb
from app.services.access import is_bot_admin, is_private, require_private_admin
from app.texts import ADMIN_HELP, MEMBER_HELP, START_TEXT

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message):
    if not is_private(message):
        return
    if not is_bot_admin(message.from_user.id):
        return
    await message.answer(
        START_TEXT,
        reply_markup=private_menu_kb(is_admin=is_bot_admin(message.from_user.id)),
    )


@router.message(Command("menu"))
@router.message(F.text == BTN_MENU)
async def cmd_menu(message: Message):
    if not is_private(message):
        return
    if not is_bot_admin(message.from_user.id):
        return
    await message.answer(
        MEMBER_HELP,
        reply_markup=private_menu_kb(is_admin=is_bot_admin(message.from_user.id)),
    )


@router.message(Command("admin_help"))
@router.message(F.text == BTN_ADMIN_HELP)
async def cmd_admin_help(message: Message):
    if not await require_private_admin(message):
        return
    await message.answer(ADMIN_HELP)
