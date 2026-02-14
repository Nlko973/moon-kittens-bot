import re

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import ChatMemberUpdated, Message

from app.runtime import bot
from app.services.access import is_bot_admin
from app.services.automation import add_message_and_guard, register_join_event
from app.services.chat_settings import get_group_id
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
async def cmd_role_shortcut(message: Message):
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return
    if message.chat.id != get_group_id():
        return
    if not is_bot_admin(message.from_user.id):
        return

    match = re.match(r"^\+роль\s+(.+?)\s+(@\w+|-?\d+)$", message.text.strip(), flags=re.IGNORECASE)
    if not match:
        await message.answer("Формат: +роль <Название роли> <@username|id>")
        return

    title = match.group(1).strip()
    user_id = parse_target(match.group(2).strip())
    if not user_id:
        await message.answer("⚠️ Пользователь не найден в базе.")
        return

    group_id = get_group_id()
    try:
        await bot.promote_chat_member(
            group_id,
            user_id,
            can_change_info=False,
            can_delete_messages=False,
            can_invite_users=False,
            can_restrict_members=False,
            can_pin_messages=False,
            can_promote_members=False,
            can_manage_video_chats=False,
            can_manage_chat=False,
            can_post_stories=False,
            can_edit_stories=False,
            can_delete_stories=False,
            is_anonymous=False,
        )
        await bot.set_chat_administrator_custom_title(group_id, user_id, title)
        await message.answer("✅ Подпись установлена.")
    except TelegramBadRequest as exc:
        await message.answer(f"⚠️ Ошибка выдачи роли: {exc.message}")


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
