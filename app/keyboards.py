from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

BTN_MENU = "Меню"
BTN_ADMIN_PANEL = "Админ панель"

BTN_MY_NORM = "Моя норма"
BTN_MY_REST = "Мой рест"
BTN_MY_WARNS = "Мои варны"
BTN_COMPLAINT_CREATE = "Написать жалобу"
BTN_COMPLAINT_MINE = "Мои жалобы"

BTN_ADM_NORM_STATS = "Статистика нормы"
BTN_ADM_RESTS = "Список рестов"
BTN_ADM_WARNS_ALL = "Все варны"
BTN_ADM_ADMINS = "Список админов"
BTN_ADM_SHOW_CONFIG = "Конфиг"
BTN_ADM_CLEANUP_ON = "Чистка ON"
BTN_ADM_CLEANUP_OFF = "Чистка OFF"
BTN_ADM_CLEANUP_SKIP = "Пропуск чистки"
BTN_ADM_ROLE_SET = "Роль +"
BTN_ADM_ROLE_DEL = "Роль -"
BTN_ADM_COMPLAINTS = "Жалобы"
BTN_ADM_COMPLAINT_DEL = "Удалить жалобу"
BTN_ADM_PROMPT_WARN = "Выдать варн"
BTN_ADM_PROMPT_UNWARN = "Снять варн"
BTN_ADM_PROMPT_REST = "Выдать рест"
BTN_ADM_PROMPT_UNREST = "Снять рест"
BTN_ADM_PROMPT_MUTE = "Мут"
BTN_ADM_PROMPT_UNMUTE = "Размут"
BTN_ADM_PROMPT_BAN = "Бан"
BTN_ADM_PROMPT_UNBAN = "Разбан"
BTN_ADM_PROMPT_KICK = "Кик"
BTN_ADM_PROMPT_SAY = "Написать в чат"
BTN_ADM_PROMPT_SET_PARAM = "Параметр"


def private_user_kb(is_admin: bool) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=BTN_MY_NORM), KeyboardButton(text=BTN_MY_WARNS)],
        [KeyboardButton(text=BTN_MY_REST), KeyboardButton(text=BTN_COMPLAINT_CREATE)],
        [KeyboardButton(text=BTN_COMPLAINT_MINE), KeyboardButton(text=BTN_MENU)],
    ]
    if is_admin:
        rows.append([KeyboardButton(text=BTN_ADMIN_PANEL)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def private_admin_panel_kb() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=BTN_ADM_NORM_STATS), KeyboardButton(text=BTN_ADM_WARNS_ALL)],
        [KeyboardButton(text=BTN_ADM_RESTS), KeyboardButton(text=BTN_ADM_ADMINS)],
        [KeyboardButton(text=BTN_ADM_COMPLAINTS), KeyboardButton(text=BTN_ADM_COMPLAINT_DEL)],
        [KeyboardButton(text=BTN_ADM_CLEANUP_ON), KeyboardButton(text=BTN_ADM_CLEANUP_OFF), KeyboardButton(text=BTN_ADM_CLEANUP_SKIP)],
        [KeyboardButton(text=BTN_ADM_ROLE_SET), KeyboardButton(text=BTN_ADM_ROLE_DEL)],
        [KeyboardButton(text=BTN_ADM_PROMPT_WARN), KeyboardButton(text=BTN_ADM_PROMPT_UNWARN)],
        [KeyboardButton(text=BTN_ADM_PROMPT_REST), KeyboardButton(text=BTN_ADM_PROMPT_UNREST)],
        [KeyboardButton(text=BTN_ADM_PROMPT_MUTE), KeyboardButton(text=BTN_ADM_PROMPT_UNMUTE)],
        [KeyboardButton(text=BTN_ADM_PROMPT_BAN), KeyboardButton(text=BTN_ADM_PROMPT_UNBAN), KeyboardButton(text=BTN_ADM_PROMPT_KICK)],
        [KeyboardButton(text=BTN_ADM_PROMPT_SAY), KeyboardButton(text=BTN_ADM_PROMPT_SET_PARAM)],
        [KeyboardButton(text=BTN_ADM_SHOW_CONFIG), KeyboardButton(text=BTN_MENU)],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def owner_third_warn_actions(user_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Снять мут", callback_data=f"owner_unmute:{user_id}")
    kb.button(text="Бан", callback_data=f"owner_ban:{user_id}")
    kb.adjust(2)
    return kb.as_markup()
