from aiogram.exceptions import TelegramBadRequest

from app.runtime import bot
from app.services.chat_settings import get_group_id


async def apply_role_signature(user_id: int, title: str) -> str:
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
        return "✅ Подпись установлена."
    except TelegramBadRequest as exc:
        return f"⚠️ Ошибка выдачи роли: {exc.message}"


async def remove_role_signature(user_id: int) -> str:
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
        return "✅ Роль снята."
    except TelegramBadRequest as exc:
        return f"⚠️ Ошибка снятия роли: {exc.message}"
