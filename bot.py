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
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, OWNER_ID, MONTHLY_NORMA, GROUP_ID
from db import (
    init_db,
    add_message,
    get_all,
    get_user_count,
    add_admin,
    remove_admin,
    get_admins,
    is_admin
)

# ================= INIT =================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ================= FSM =================

class AdminStates(StatesGroup):
    waiting_add_id = State()
    waiting_add_name = State()
    waiting_del_id = State()
    waiting_bot_message = State()

# ================= KEYBOARDS =================

main_kb = ReplyKeyboardMarkup(
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
            [InlineKeyboardButton(text="➖ Удалить админа", callback_data="admin_del")],
            [InlineKeyboardButton(text="✉️ Написать от имени бота", callback_data="bot_say")]
        ]
    )

# ================= START =================

@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "Moon Kittens Bot 🌙🐾",
        reply_markup=main_kb
    )

# ================= COUNT MESSAGES =================

@dp.message(
    F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}),
    F.from_user.is_not(None),
    F.text
)
async def count_messages(message: Message):
    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else message.from_user.full_name
    )
    add_message(message.from_user.id, username)

# ================= МОЯ НОРМА =================

@dp.message(
    F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}),
    F.text.lower() == "моя норма"
)
async def my_norma(message: Message):
    user = message.from_user

    username = (
        f"@{user.username}"
        if user.username
        else user.full_name
    )

    count = get_user_count(user.id)

    if count >= MONTHLY_NORMA:
        text = f"{username}, у вас есть норма за месяц ✅"
    else:
        text = f"{username}, у вас нет нормы за месяц ❌"

    await message.answer(text)

# ================= STATS =================

@dp.message(F.text == "📊 Статистика")
@dp.message(Command("stats"))
async def stats(message: Message):
    if not is_admin(message.from_user.id, OWNER_ID):
        await message.answer("⛔ Нет доступа")
        return

    data = get_all()
    if not data:
        await message.answer("Нет данных за этот месяц")
        return

    lines = []
    for username, count in data:
        mark = "✅" if count >= MONTHLY_NORMA else "❌"
        lines.append(f"{username} — {count} {mark}")

    await message.answer("\n".join(lines))

# ================= ADMINS =================

@dp.message(F.text == "👑 Админы")
@dp.message(Command("admins"))
async def admins(message: Message):
    if not is_admin(message.from_user.id, OWNER_ID):
        await message.answer("⛔ Нет доступа")
        return

    admins_list = get_admins()

    if not admins_list:
        text = "👑 Админы:\n—"
    else:
        text = "👑 Админы:\n" + "\n".join(
            f"{user_id} — {name}" for user_id, name in admins_list
        )

    await message.answer(
        text,
        reply_markup=admins_inline_kb(message.from_user.id == OWNER_ID)
    )

# ================= INLINE =================

@dp.callback_query(F.data == "bot_say")
async def bot_say_cb(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_bot_message)
    await callback.message.answer("✏️ Напиши сообщение для группы")
    await callback.answer()


@dp.callback_query(F.data == "admin_add")
async def admin_add_cb(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_add_id)
    await callback.message.answer("🆔 Введи ID пользователя")
    await callback.answer()


@dp.callback_query(F.data == "admin_del")
async def admin_del_cb(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_del_id)
    await callback.message.answer("🆔 Введи ID админа")
    await callback.answer()

# ================= FSM =================

@dp.message(AdminStates.waiting_bot_message)
async def process_bot_message(message: Message, state: FSMContext):
    await bot.send_message(GROUP_ID, message.text)
    await message.answer("✅ Отправлено")
    await state.clear()


@dp.message(AdminStates.waiting_add_id)
async def process_add_admin_id(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ ID должен быть числом")
        return

    await state.update_data(user_id=int(message.text))
    await state.set_state(AdminStates.waiting_add_name)
    await message.answer("✏️ Введи имя админа")


@dp.message(AdminStates.waiting_add_name)
async def process_add_admin_name(message: Message, state: FSMContext):
    data = await state.get_data()
    add_admin(data["user_id"], message.text.strip())
    await message.answer("✅ Админ добавлен")
    await state.clear()


@dp.message(AdminStates.waiting_del_id)
async def process_del_admin(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ ID должен быть числом")
        return

    remove_admin(int(message.text))
    await message.answer("❌ Админ удалён")
    await state.clear()

# ================= MAIN =================

async def main():
    init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
