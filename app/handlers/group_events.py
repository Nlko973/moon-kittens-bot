import re

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import ChatMemberUpdated, Message

from app.runtime import bot
from app.services.access import is_bot_admin
from app.services.automation import add_message_and_guard, register_join_event
from app.services.duration_parser import parse_ru_duration_to_minutes
from app.services.moderation import issue_warn, mute_user
from app.services.chat_settings import get_group_id
from app.services.roles import apply_role_signature, remove_role_signature
from app.services.targets import parse_target
from db import mark_user_left

router = Router()


@router.chat_member()
async def on_chat_member(event: ChatMemberUpdated):
    if event.chat.id != get_group_id():
        return

    new_status = event.new_chat_member.status
    old_status = event.old_chat_member.status
    user = event.new_chat_member.user
    if not user:
        return

    if new_status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}:
        mark_user_left(user.id)
        return

    joined = (
        old_status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}
        and new_status in {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.RESTRICTED}
    )

    if joined and register_join_event():
        try:
            await bot.send_message(
                get_group_id(),
                "🛡 Антирейд: зафиксирован массовый вход пользователей, включен усиленный контроль.",
            )
        except TelegramBadRequest:
            pass


@router.message(F.text.regexp(r"^\+роль\s+.+$"))
async def cmd_role_plus_group(message: Message):
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return
    if message.chat.id != get_group_id():
        return
    if not is_bot_admin(message.from_user.id):
        return

    match = re.match(r"^\+роль\s+(@\w+|-?\d+)\s+(.+)$", message.text.strip(), flags=re.IGNORECASE)
    if not match:
        await message.answer("Формат: +роль @username роль")
        return

    user_id = parse_target(match.group(1).strip())
    if not user_id:
        await message.answer("⚠️ Пользователь не найден в базе.")
        return

    title = match.group(2).strip()
    await message.answer(await apply_role_signature(user_id, title))


@router.message(F.text.regexp(r"^-роль\s+.+$"))
async def cmd_role_minus_group(message: Message):
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return
    if message.chat.id != get_group_id():
        return
    if not is_bot_admin(message.from_user.id):
        return

    match = re.match(r"^-роль\s+(@\w+|-?\d+)$", message.text.strip(), flags=re.IGNORECASE)
    if not match:
        await message.answer("Формат: -роль @username")
        return

    user_id = parse_target(match.group(1).strip())
    if not user_id:
        await message.answer("⚠️ Пользователь не найден в базе.")
        return

    await message.answer(await remove_role_signature(user_id))


@router.message(F.from_user.is_not(None), ~F.from_user.is_bot)
async def on_group_message(message: Message):
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return
    if message.chat.id != get_group_id():
        return

    try:
        await add_message_and_guard(message)
    except TelegramBadRequest:
        pass


@router.message(F.text.regexp(r"^варн\s+.+$"))
async def cmd_warn_word(message: Message):
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP} or message.chat.id != get_group_id():
        return
    if not is_bot_admin(message.from_user.id):
        return
    match = re.match(r"^варн\s+(@\w+|-?\d+)(?:\s+(.+))?$", message.text.strip(), flags=re.IGNORECASE)
    if not match:
        await message.answer("Формат: варн @username причина")
        return
    user_id = parse_target(match.group(1).strip())
    if not user_id:
        await message.answer("⚠️ Пользователь не найден в базе.")
        return
    reason = (match.group(2) or "Без причины").strip()
    warn_id, total, third = await issue_warn(user_id, message.from_user.id, reason, "manual")
    suffix = " Пользователь автоматически получил мут (3-й варн)." if third else ""
    await message.answer(f"✅ Варн выдан: #{warn_id}. Активных варнов: {total}.{suffix}")


@router.message(F.text.regexp(r"^мут\s+.+$"))
async def cmd_mute_word(message: Message):
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP} or message.chat.id != get_group_id():
        return
    if not is_bot_admin(message.from_user.id):
        return
    match = re.match(r"^мут\s+(@\w+|-?\d+)\s+(.+)$", message.text.strip(), flags=re.IGNORECASE)
    if not match:
        await message.answer("Формат: мут @username 5 минут [причина]")
        return
    user_id = parse_target(match.group(1).strip())
    if not user_id:
        await message.answer("⚠️ Пользователь не найден в базе.")
        return
    rest = match.group(2).strip()
    minutes = parse_ru_duration_to_minutes(rest)
    if minutes is None:
        await message.answer("⚠️ Примеры: мут @user 5 минут | мут @user 2 часа | мут @user 1 день")
        return
    await message.answer(await mute_user(user_id, minutes, message.from_user.id, "Мут в чате"))


@router.message(F.text.regexp(r"^бан\s+.+$"))
async def cmd_ban_word(message: Message):
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP} or message.chat.id != get_group_id():
        return
    if not is_bot_admin(message.from_user.id):
        return
    match = re.match(r"^бан\s+(@\w+|-?\d+)(?:\s+(.+))?$", message.text.strip(), flags=re.IGNORECASE)
    if not match:
        await message.answer("Формат: бан @username [причина]")
        return
    user_id = parse_target(match.group(1).strip())
    if not user_id:
        await message.answer("⚠️ Пользователь не найден в базе.")
        return
    try:
        await bot.ban_chat_member(get_group_id(), user_id)
        await message.answer("✅ Пользователь забанен.")
    except TelegramBadRequest as exc:
        await message.answer(f"⚠️ Не удалось забанить пользователя: {exc.message}")


@router.message(F.text.regexp(r"^кик\s+.+$"))
async def cmd_kick_word(message: Message):
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP} or message.chat.id != get_group_id():
        return
    if not is_bot_admin(message.from_user.id):
        return
    match = re.match(r"^кик\s+(@\w+|-?\d+)(?:\s+(.+))?$", message.text.strip(), flags=re.IGNORECASE)
    if not match:
        await message.answer("Формат: кик @username [причина]")
        return
    user_id = parse_target(match.group(1).strip())
    if not user_id:
        await message.answer("⚠️ Пользователь не найден в базе.")
        return
    try:
        group_id = get_group_id()
        await bot.ban_chat_member(group_id, user_id)
        await bot.unban_chat_member(group_id, user_id, only_if_banned=True)
        await message.answer("✅ Пользователь кикнут.")
    except TelegramBadRequest as exc:
        await message.answer(f"⚠️ Не удалось кикнуть пользователя: {exc.message}")
