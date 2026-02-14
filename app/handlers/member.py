from datetime import datetime

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message

from app.keyboards import BTN_COMPLAINT_CREATE, BTN_COMPLAINT_MINE, BTN_MY_NORM, BTN_MY_REST, BTN_MY_WARNS
from app.services.chat_settings import get_group_id
from app.services.access import is_private
from app.texts import norm_status_text, rest_status_infinite, rest_status_none, rest_status_with_days
from db import create_complaint, get_rest, get_user_complaints, get_user_warns, get_user_week_count, get_weekly_norm

router = Router()

AWAITING_COMPLAINT_USERS: set[int] = set()


def _is_target_group(message: Message) -> bool:
    return message.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP} and message.chat.id == get_group_id()


def _is_private(message: Message) -> bool:
    return is_private(message)


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_COMPLAINT_CREATE)
@router.message(Command("complaint"))
async def complaint_start(message: Message):
    if not _is_private(message):
        return
    AWAITING_COMPLAINT_USERS.add(message.from_user.id)
    await message.answer("Опишите жалобу одним сообщением. Отправьте текст следующим сообщением.")


@router.message(F.chat.type == ChatType.PRIVATE, F.from_user.is_not(None), F.text)
async def complaint_receive(message: Message):
    if message.from_user.id not in AWAITING_COMPLAINT_USERS:
        return

    text = message.text.strip()
    if not text:
        await message.answer("Текст жалобы пустой. Напишите жалобу сообщением.")
        return

    AWAITING_COMPLAINT_USERS.remove(message.from_user.id)
    complaint_id = create_complaint(message.from_user.id, message.from_user.username, message.from_user.full_name, text)
    await message.answer(f"✅ Жалоба принята. Номер: #{complaint_id}")


@router.message(F.text == BTN_MY_NORM)
@router.message(F.text.regexp(r"(?i)^моя\s+норма$"))
@router.message(F.text.regexp(r"(?i)^(?:📊\s*)?моя\s+норма$"))
@router.message(Command("mynorm"))
async def mynorm(message: Message):
    if not (_is_private(message) or _is_target_group(message)):
        return
    norm = get_weekly_norm()
    count = get_user_week_count(message.from_user.id)
    await message.answer(norm_status_text(message.from_user.username, message.from_user.full_name, count, norm))


@router.message(F.text == BTN_MY_REST)
@router.message(F.text.regexp(r"(?i)^мой\s+рест$"))
@router.message(F.text.regexp(r"(?i)^(?:🛌\s*)?мой\s+рест$"))
@router.message(Command("myrest"))
async def myrest(message: Message):
    if not (_is_private(message) or _is_target_group(message)):
        return

    rest = get_rest(message.from_user.id)
    if not rest:
        await message.answer(rest_status_none(message.from_user.username, message.from_user.full_name))
        return

    expires_at = rest["expires_at"]
    if not expires_at:
        await message.answer(rest_status_infinite(message.from_user.username, message.from_user.full_name, rest["role_name"]))
        return

    remain = datetime.fromisoformat(expires_at) - datetime.now()
    days = max(0, remain.days)
    await message.answer(rest_status_with_days(message.from_user.username, message.from_user.full_name, rest["role_name"], days))


@router.message(F.text == BTN_MY_WARNS)
@router.message(F.text.regexp(r"(?i)^мои\s+варны$"))
@router.message(F.text.regexp(r"(?i)^(?:⚠️\s*)?мои\s+варны$"))
@router.message(Command("mywarns"))
async def mywarns(message: Message):
    if not (_is_private(message) or _is_target_group(message)):
        return

    warns = get_user_warns(message.from_user.id, active_only=True)
    if not warns:
        await message.answer("✅ У вас нет активных варнов.")
        return

    lines = [f"⚠️ Ваши активные варны: {len(warns)}."]
    for row in warns[:20]:
        lines.append(f"#{row['id']} [{row['warn_type']}] {row['reason']}")
    await message.answer("\n".join(lines))


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_COMPLAINT_MINE)
@router.message(Command("my_complaints"))
async def my_complaints(message: Message):
    rows = get_user_complaints(message.from_user.id)
    if not rows:
        await message.answer("У вас пока нет жалоб.")
        return

    lines = ["Ваши жалобы:"]
    for row in rows[:20]:
        lines.append(f"#{row['id']} {row['created_at']}: {row['text']}")
    await message.answer("\n".join(lines))
