import re

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import ChatMemberUpdated, Message

from app.runtime import bot
from app.services.access import is_bot_admin
from app.services.automation import add_message_and_guard, register_join_event
from app.services.duration_parser import parse_deadline, parse_ru_duration_to_minutes
from app.services.moderation import issue_warn, mute_user
from app.services.chat_settings import get_group_id
from app.services.roles import apply_role_signature, remove_role_signature
from app.services.targets import parse_target
from app.services.user_identity import remember_user
from db import is_tg_links_block_enabled, mark_user_joined, mark_user_left

router = Router()
TG_LINK_RE = re.compile(r"(?i)(?:https?://)?(?:t|telegram)\.me/[^\s]+")


def _message_has_tg_link(message: Message) -> bool:
    text_chunks = []
    if message.text:
        text_chunks.append(message.text)
    if message.caption:
        text_chunks.append(message.caption)
    body = "\n".join(text_chunks)
    if body and TG_LINK_RE.search(body):
        return True

    entities = []
    if message.entities:
        entities.extend(message.entities)
    if message.caption_entities:
        entities.extend(message.caption_entities)

    for entity in entities:
        if entity.type == "text_link":
            url = (entity.url or "").lower()
            if "t.me/" in url or "telegram.me/" in url:
                return True
    return False


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
        remember_user(user)
        mark_user_joined(user.id, user.username, user.full_name)
        try:
            await bot.send_message(
                get_group_id(),
                "🛡 Антирейд: зафиксирован массовый вход пользователей, включен усиленный контроль.",
            )
        except TelegramBadRequest:
            pass
    elif joined:
        remember_user(user)
        mark_user_joined(user.id, user.username, user.full_name)


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

    user_id = await parse_target(match.group(1).strip())
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

    user_id = await parse_target(match.group(1).strip())
    if not user_id:
        await message.answer("⚠️ Пользователь не найден в базе.")
        return

    await message.answer(await remove_role_signature(user_id))


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
    user_id = await parse_target(match.group(1).strip())
    if not user_id:
        await message.answer("⚠️ Пользователь не найден в базе.")
        return
    reason_raw = (match.group(2) or "Без причины").strip()
    reason = reason_raw
    expires_at = None
    parts = reason_raw.split(maxsplit=2)
    if len(parts) >= 2 and parts[0].lower() == "до":
        maybe_deadline = parse_deadline(parts[1])
        if maybe_deadline:
            expires_at = maybe_deadline.isoformat(timespec="seconds")
            reason = parts[2].strip() if len(parts) > 2 else "Без причины"
    elif len(parts) >= 2:
        maybe_deadline = parse_deadline(f"{parts[0]} {parts[1]}")
        if maybe_deadline:
            expires_at = maybe_deadline.isoformat(timespec="seconds")
            reason = parts[2].strip() if len(parts) > 2 else "Без причины"
    elif len(parts) == 1:
        maybe_deadline = parse_deadline(parts[0])
        if maybe_deadline:
            expires_at = maybe_deadline.isoformat(timespec="seconds")
            reason = "Без причины"

    warn_id, total, third, expires_at = await issue_warn(
        user_id,
        message.from_user.id,
        reason,
        "manual",
        expires_at=expires_at,
    )
    expires_text = expires_at.replace("T", " ")
    suffix = " Пользователь автоматически получил мут (3-й варн)." if third else ""
    await message.answer(f"✅ Варн выдан: #{warn_id}. Активных варнов: {total}. Срок до: {expires_text}.{suffix}")


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
    user_id = await parse_target(match.group(1).strip())
    if not user_id:
        await message.answer("⚠️ Пользователь не найден в базе.")
        return
    rest = match.group(2).strip()
    minutes = parse_ru_duration_to_minutes(rest)
    if minutes is None:
        await message.answer("⚠️ Примеры: мут @user 5 минут | мут @user 2 часа | мут @user 1 день")
        return
    try:
        await message.answer(await mute_user(user_id, minutes, message.from_user.id, "Мут в чате"))
    except Exception as exc:
        await message.answer(f"⚠️ Ошибка мута: {exc}")


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
    user_id = await parse_target(match.group(1).strip())
    if not user_id:
        await message.answer("⚠️ Пользователь не найден в базе.")
        return
    try:
        await bot.ban_chat_member(get_group_id(), user_id)
        await message.answer("✅ Пользователь забанен.")
    except TelegramBadRequest as exc:
        await message.answer(f"⚠️ Не удалось забанить пользователя: {exc.message}")
    except Exception as exc:
        await message.answer(f"⚠️ Ошибка бана: {exc}")


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
    user_id = await parse_target(match.group(1).strip())
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
    except Exception as exc:
        await message.answer(f"⚠️ Ошибка кика: {exc}")


@router.message(F.from_user.is_not(None), ~F.from_user.is_bot)
async def on_group_message(message: Message):
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return
    if message.chat.id != get_group_id():
        return
    remember_user(message.from_user)

    if is_tg_links_block_enabled() and not is_bot_admin(message.from_user.id):
        if _message_has_tg_link(message):
            try:
                await bot.delete_message(message.chat.id, message.message_id)
            except TelegramBadRequest:
                pass

            warn_id, total, _third, _expires_at = await issue_warn(
                message.from_user.id,
                0,
                "Ссылка на Telegram-канал (запрещено)",
                "tg_link",
                duration_minutes=60 * 24 * 30,
            )
            await message.answer(f"⚠️ Ссылка запрещена. Выдан варн #{warn_id}. Активных варнов: {total}.")
            return

    try:
        await add_message_and_guard(message)
    except TelegramBadRequest:
        pass
