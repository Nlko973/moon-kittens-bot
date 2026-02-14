from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


BTN_MENU = "📋 Меню"
BTN_MY_NORM = "📊 Моя норма"
BTN_MY_REST = "🛌 Мой рест"
BTN_MY_WARNS = "⚠️ Мои варны"
BTN_ADMIN_HELP = "🛠 Админ-команды"


def private_menu_kb(is_admin: bool) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=BTN_MY_NORM), KeyboardButton(text=BTN_MY_WARNS)],
        [KeyboardButton(text=BTN_MY_REST), KeyboardButton(text=BTN_MENU)],
    ]
    if is_admin:
        rows.append([KeyboardButton(text=BTN_ADMIN_HELP)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def owner_third_warn_actions(user_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Снять мут", callback_data=f"owner_unmute:{user_id}")
    kb.button(text="🔨 Бан", callback_data=f"owner_ban:{user_id}")
    kb.adjust(2)
    return kb.as_markup()
