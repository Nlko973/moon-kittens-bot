import asyncio
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.enums import ChatType

from config import BOT_TOKEN, OWNER_ID, MONTHLY_NORMA
from db import (
    init_db, add_message, get_all_stats,
    add_admin, del_admin, get_admins, is_admin
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ---------- KEYBOARD ----------
kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="👑 Админы")]
    ],
    resize_keyboard=True
)


# ---------- START ----------
@dp.message(Command("start"))
async def start(message: Message):
    await message.answer("Moon Kittens Bot 🌙🐾", reply_markup=kb)


# ---------- COUNT MESSAGES ----------
@dp.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def count_messages(message: Message):
    if not message.from_user:
        return

    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else message.from_user.full_name
    )

    add_message(message.from_user.id, username)


# ---------- STATS ----------
@dp.message(F.text == "📊 Статистика")
@dp.message(Command("stats"))
async def stats(message: Message):
    if not is_admin(message.from_user.id, OWNER_ID):
        await message.answer("⛔ Нет доступа")
        return

    data = get_all_stats()
    if not data:
        await message.answer("Нет данных за этот месяц")
        return

    lines = []
    for username, count in data:
        mark = "✅" if count >= MONTHLY_NORMA else "❌"
        lines.append(f"{username} — {count} {mark}")

    await message.answer("\n".join(lines))


# ---------- ADMINS ----------
@dp.message(Command("add_admin"))
async def cmd_add_admin(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("⛔ Только владелец")
        return

    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Используй: /add_admin ID")
        return

    add_admin(int(parts[1]))
    await message.answer("✅ Админ добавлен")


@dp.message(Command("del_admin"))
async def cmd_del_admin(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("⛔ Только владелец")
        return

    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Используй: /del_admin ID")
        return

    del_admin(int(parts[1]))
    await message.answer("❌ Админ удалён")


@dp.message(F.text == "👑 Админы")
@dp.message(Command("admins"))
async def admins(message: Message):
    if not is_admin(message.from_user.id, OWNER_ID):
        await message.answer("⛔ Нет доступа")
        return

    admins = get_admins()
    text = "\n".join(str(a) for a in admins) or "Админов нет"
    await message.answer(f"👑 Админы:\n{text}")


# ---------- MAIN ----------
async def main():
    init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
