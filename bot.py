import asyncio

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)
from aiogram.filters import Command
from aiogram.enums import ChatType

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import BOT_TOKEN, OWNER_ID, MONTHLY_NORMA
from db import (
    init_db,
    add_message,
    get_all_stats,
    add_admin,
    del_admin,
    get_admins,
    is_admin
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================= FSM =================

class AdminStates(StatesGroup):
    waiting_add_id = State()
    waiting_del_id = State()

# ================= KEYBOARDS =================

kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="👑 Админы")]
    ],
    resize_keyboard=True
)


def admins_inline_kb(is_owner: bool):
    if not is_owner:
        return None

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить админа", callback_data="admin_add")],
            [InlineKeyboardButton(text="➖ Удалить админа", callback_data="admin_del")]
        ]
    )

# ================= START =================

@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "Moon Kittens Bot 🌙🐾",
        reply_markup=kb
    )

# ================= COUNT MESSAGES =================

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

# ================= STATS =================

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

# ================= ADMINS LIST =================

@dp.message(F.text == "👑 Админы")
@dp.message(Command("admins"))
async def admins(message: Message):
    if not is_admin(message.from_user.id, OWNER_ID):
        await message.answer("⛔ Нет доступа")
        return

    admins_list = get_admins()
    text = "👑 Админы:\n" + ("\n".join(str(a) for a in admins_list) or "—")

    await message.answer(
        text,
        reply_markup=admins_inline_kb(message.from_user.id == OWNER_ID)
    )

# ================= INLINE BUTTONS =================

@dp.callback_query(F.data == "admin_add")
async def admin_add_cb(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_add_id)
    await callback.message.answer("🆔 Отправь ID пользователя для добавления")
    await callback.answer()


@dp.callback_query(F.data == "admin_del")
async def admin_del_cb(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_del_id)
    await callback.message.answer("🆔 Отправь ID пользователя для удаления")
    await callback.answer()

# ================= FSM INPUT =================

@dp.message(AdminStates.waiting_add_id)
async def process_add_admin(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return

    if not message.text.isdigit():
        await message.answer("❌ ID должен быть числом")
        return

    add_admin(int(message.text))
    await message.answer("✅ Админ добавлен")
    await state.clear()


@dp.message(AdminStates.waiting_del_id)
async def process_del_admin(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return

    if not message.text.isdigit():
        await message.answer("❌ ID должен быть числом")
        return

    del_admin(int(message.text))
    await message.answer("❌ Админ удалён")
    await state.clear()

# ================= MAIN =================

async def main():
    init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
