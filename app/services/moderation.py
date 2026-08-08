from datetime import datetime, timedelta
from typing import Optional

from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import ChatPermissions

from app.keyboards import owner_third_warn_actions
from app.runtime import bot
from app.services.bot_config import get_int_param
from app.services.chat_settings import get_group_id
from app.services.owner_notifications import notify_owner
from app.texts import owner_third_warn_notice
from db import create_warn, get_active_warn_count, get_mute, get_user_brief, remove_mute, set_mute


async def mute_user(user_id: int, minutes: int, issued_by: int, reason: str) -> str:
    group_id = get_group_id()
    until_dt = datetime.now() + timedelta(minutes=minutes)

    try:
        member = await bot.get_chat_member(group_id, user_id)
    except TelegramBadRequest as exc:
        return f"⚠️ Не удалось проверить пользователя для мута: {exc.message}"

    if member.status == ChatMemberStatus.OWNER:
        return "⚠️ Нельзя выдать мут владельцу чата."

    was_admin = member.status == ChatMemberStatus.ADMINISTRATOR
    old_title = getattr(member, "custom_title", None)

    try:
        if was_admin:
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

        await bot.restrict_chat_member(
            group_id,
            user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until_dt,
        )
    except TelegramBadRequest as exc:
        return f"⚠️ Не удалось выдать мут: {exc.message}"

    set_mute(
        user_id=user_id,
        until_at=until_dt.isoformat(timespec="seconds"),
        old_title=old_title,
        was_admin=was_admin,
        issued_by=issued_by,
        reason=reason,
    )

    return f"✅ Мут выдан до {until_dt.strftime('%Y-%m-%d %H:%M:%S')}."


async def unmute_user(user_id: int, silent: bool = False) -> str:
    group_id = get_group_id()
    mute = get_mute(user_id)
    if not mute:
        return "⚠️ Мут не найден."

    try:
        await bot.restrict_chat_member(
            group_id,
            user_id,
            permissions=ChatPermissions(can_send_messages=True),
        )
    except TelegramBadRequest as exc:
        return f"⚠️ Не удалось снять мут: {exc.message}"

    if mute["was_admin"]:
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
        except TelegramBadRequest:
            pass
        if mute["old_title"]:
            try:
                await bot.set_chat_administrator_custom_title(group_id, user_id, mute["old_title"])
            except TelegramBadRequest:
                pass

    remove_mute(user_id)
    return "" if silent else "✅ Мут снят."


async def issue_warn(
    user_id: int,
    admin_id: int,
    reason: str,
    warn_type: str = "manual",
    expires_at: Optional[str] = None,
    duration_minutes: int = 60 * 24 * 30,
) -> tuple[int, int, bool, str]:
    warn_id, expires_at = create_warn(
        user_id,
        admin_id,
        reason,
        warn_type,
        expires_at=expires_at,
        duration_minutes=duration_minutes,
    )
    total = get_active_warn_count(user_id)
    third_triggered = total == 3

    if third_triggered:
        mute_result = await mute_user(user_id, get_int_param("third_warn_mute_minutes"), admin_id, "3 активных варна")
        user = get_user_brief(user_id)
        username = user["username"] if user else None
        display_name = user["display_name"] if user else str(user_id)
        await notify_owner(
            owner_third_warn_notice(user_id, username, display_name, warn_id) + f"\nСтатус авто-мута: {mute_result}",
            reply_markup=owner_third_warn_actions(user_id),
        )

    return warn_id, total, third_triggered, expires_at
