import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ChatMemberUpdated
from datetime import datetime
from config import BOT_TOKEN, OWNER_ID, MONTHLY_NORMA
from db import init_db, increment, add_user, get_all, clear_all
from db import create_admins_table, add_admin, remove_admin, get_admins, is_admin
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


bot = Bot(BOT_TOKEN)
dp = Dispatcher()

ADMINS = {OWNER_ID}
current_month = datetime.utcnow().month

def check_month():
    global current_month
    now = datetime.utcnow()
    if now.month != current_month:
        clear_all()
        current_month = now.month

@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    if not is_admin(message.from_user.id, OWNER_ID):
        await message.answer("⛔ У тебя нет доступа к боту")
        return

    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(
        KeyboardButton("📊 Статистика"),
        KeyboardButton("👥 Админы")
    )

    await message.answer("Выбери действие:", reply_markup=keyboard)

@dp.message_handler(lambda m: m.text == "📊 Статистика")
async def btn_stats(message: types.Message):
    await cmd_stats(message)


@dp.message_handler(lambda m: m.text == "👥 Админы")
async def btn_admins(message: types.Message):
    await cmd_admins(message)


@dp.message_handler(commands=["add_admin"])
async def cmd_add_admin(message: types.Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("❌ Недостаточно прав")
        return

    try:
        user_id = int(message.text.split()[1])
    except (IndexError, ValueError):
        await message.answer("Использование: /add_admin USER_ID")
        return

    add_admin(user_id)
    await message.answer(f"✅ Админ добавлен: {user_id}")

@dp.message_handler(commands=["del_admin"])
async def cmd_del_admin(message: types.Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("❌ Недостаточно прав")
        return

    try:
        user_id = int(message.text.split()[1])
    except (IndexError, ValueError):
        await message.answer("Использование: /del_admin USER_ID")
        return

    remove_admin(user_id)
    await message.answer(f"❌ Админ удалён: {user_id}")

@dp.message_handler(commands=["admins"])
async def cmd_admins(message: types.Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("❌ Недостаточно прав")
        return

    admins = get_admins()
    if not admins:
        await message.answer("Админы не добавлены")
        return

    text = "👥 Админы:\n\n"
    for admin_id in admins:
        text += f"• {admin_id}\n"

    await message.answer(text)


@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def count_messages(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    check_month()
    username = message.from_user.username or message.from_user.full_name
    increment(message.from_user.id, username)

@dp.chat_member()
async def on_join(event: ChatMemberUpdated):
    if event.new_chat_member.status == "member":
        user = event.from_user
        username = user.username or user.full_name
        add_user(user.id, username)

@dp.message(F.chat.type == "private", F.text == "/stats")
async def stats(message: Message):
    if not is_admin(message.from_user.id, OWNER_ID):
        await message.answer("⛔ Нет доступа")
        return

    data = get_all()
    if not data:
        await message.answer("Нет данных за этот месяц")
        return

    text = []
    for username, count in data:
        mark = "✅" if count >= MONTHLY_NORMA else "❌"
        text.append(f"{username} — {count} {mark}")

    await message.answer("\n".join(text))

@dp.message(F.chat.type == "private", F.text == "/no_norma")
async def no_norma(message: Message):
    if message.from_user.id not in ADMINS:
        await message.answer("⛔ Нет доступа")
        return

    bad = [
        f"{u} — {c}"
        for u, c in get_all()
        if c < MONTHLY_NORMA
    ]

    if not bad:
        await message.answer("🎉 Все выполнили норму")
    else:
        await message.answer("❌ Без нормы:\n" + "\n".join(bad))

async def main():
    init_db()
    create_admins_table()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
