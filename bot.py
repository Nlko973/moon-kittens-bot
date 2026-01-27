import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ChatMemberUpdated
from datetime import datetime
from config import BOT_TOKEN, OWNER_ID, MONTHLY_NORMA
from db import init_db, increment, add_user, get_all, clear_all

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
    if message.from_user.id not in ADMINS:
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
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
