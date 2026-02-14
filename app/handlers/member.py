from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.keyboards import BTN_MY_NORM, BTN_MY_REST, BTN_MY_WARNS
from app.services.access import is_bot_admin, is_private
from app.texts import norm_status_text, rest_status_infinite, rest_status_none, rest_status_with_days
from db import get_rest, get_user_warns, get_user_week_count, get_weekly_norm

router = Router()


@router.message(Command("mynorm"))
@router.message(F.text.regexp(r"(?i)^моя\s+норма$"))
@router.message(F.text == BTN_MY_NORM)
async def cmd_mynorm(message: Message):
    if is_private(message) and not is_bot_admin(message.from_user.id):
        return
    norm = get_weekly_norm()
    count = get_user_week_count(message.from_user.id)
    await message.answer(norm_status_text(message.from_user.username, message.from_user.full_name, count, norm))


@router.message(Command("myrest"))
@router.message(F.text == BTN_MY_REST)
async def cmd_myrest(message: Message):
    if is_private(message) and not is_bot_admin(message.from_user.id):
        return
    rest = get_rest(message.from_user.id)
    if not rest:
        await message.answer(rest_status_none(message.from_user.username, message.from_user.full_name))
        return

    expires_at = rest["expires_at"]
    if not expires_at:
        await message.answer(
            rest_status_infinite(message.from_user.username, message.from_user.full_name, rest["role_name"])
        )
        return

    remain = datetime.fromisoformat(expires_at) - datetime.now()
    days = max(0, remain.days)
    await message.answer(
        rest_status_with_days(message.from_user.username, message.from_user.full_name, rest["role_name"], days)
    )


@router.message(Command("mywarns"))
@router.message(F.text == BTN_MY_WARNS)
async def cmd_mywarns(message: Message):
    if is_private(message) and not is_bot_admin(message.from_user.id):
        return
    warns = get_user_warns(message.from_user.id, active_only=True)
    if not warns:
        await message.answer("✅ У вас нет активных варнов.")
        return

    lines = [f"⚠️ Ваши активные варны: {len(warns)}."]
    for row in warns[:20]:
        lines.append(f"#{row['id']} [{row['warn_type']}] {row['reason']}")
    await message.answer("\n".join(lines))
