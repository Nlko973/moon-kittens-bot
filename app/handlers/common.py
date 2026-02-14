from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.keyboards import BTN_ADMIN_PANEL, BTN_MENU, private_admin_panel_kb, private_user_kb
from app.services.access import is_bot_admin, is_private, require_private_admin
from app.texts import ADMIN_HELP, START_TEXT
from config import OWNER_ID

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message):
    if not is_private(message):
        return
    await message.answer(
        START_TEXT,
        reply_markup=private_user_kb(is_admin=is_bot_admin(message.from_user.id)),
    )


@router.message(Command("menu"))
@router.message(F.text == BTN_MENU)
async def cmd_menu(message: Message):
    if not is_private(message):
        return
    await message.answer(
        "Главное меню",
        reply_markup=private_user_kb(is_admin=is_bot_admin(message.from_user.id)),
    )


@router.message(F.text == BTN_ADMIN_PANEL)
async def open_admin_panel(message: Message):
    if not await require_private_admin(message):
        return
    await message.answer(
        "Админ-панель",
        reply_markup=private_admin_panel_kb(is_owner=message.from_user.id == OWNER_ID),
    )


@router.message(Command("admin_help"))
async def cmd_admin_help(message: Message):
    if not await require_private_admin(message):
        return
    await message.answer(ADMIN_HELP)
