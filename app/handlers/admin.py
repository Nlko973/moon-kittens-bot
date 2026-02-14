import re
from datetime import datetime, time

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.runtime import bot
from app.keyboards import (
    BTN_ADM_ADMINS,
    BTN_ADM_CLEANUP_OFF,
    BTN_ADM_CLEANUP_ON,
    BTN_ADM_CLEANUP_SKIP,
    BTN_ADM_COMPLAINTS,
    BTN_ADM_COMPLAINT_DEL,
    BTN_ADM_NORM_STATS,
    BTN_ADM_PROMPT_BAN,
    BTN_ADM_PROMPT_KICK,
    BTN_ADM_PROMPT_MUTE,
    BTN_ADM_PROMPT_REST,
    BTN_ADM_PROMPT_SAY,
    BTN_ADM_PROMPT_SET_PARAM,
    BTN_ADM_PROMPT_UNBAN,
    BTN_ADM_PROMPT_UNMUTE,
    BTN_ADM_PROMPT_UNREST,
    BTN_ADM_PROMPT_UNWARN,
    BTN_ADM_PROMPT_WARN,
    BTN_ADM_RESTS,
    BTN_ADM_ROLE_DEL,
    BTN_ADM_ROLE_SET,
    BTN_ADM_SHOW_CONFIG,
    BTN_ADM_WARNS_ALL,
)
from app.services.access import require_owner, require_private_admin
from app.services.bot_config import PARAM_DEFAULTS, get_all_params, set_int_param
from app.services.chat_settings import get_group_id, set_group_id
from app.services.moderation import issue_warn, mute_user, unmute_user
from app.services.roles import apply_role_signature, remove_role_signature
from app.services.targets import parse_target
from app.texts import USER_NOT_FOUND, format_user, week_period
from config import OWNER_ID
from db import (
    add_admin,
    delete_complaint,
    get_admins,
    get_all_complaints,
    get_all_rests,
    get_all_warns,
    get_all_week_stats,
    get_user_warns,
    get_weekly_norm,
    is_cleanup_enabled,
    remove_admin,
    remove_rest,
    remove_warn,
    set_cleanup_enabled,
    set_cleanup_skip_once,
    set_rest,
    set_rest_until,
    set_weekly_norm,
)

router = Router()


@router.message(Command("norm_stats"))
async def cmd_norm_stats(message: Message):
    if not await require_private_admin(message):
        return

    norm = get_weekly_norm()
    rows = get_all_week_stats(members_only=True)
    if not rows:
        await message.answer("ℹ️ Нет данных по текущей неделе.")
        return

    lines = [f"📊 Недельная норма: {norm}.", f"Период: {week_period(message.date)}."]
    for row in rows[:200]:
        mark = "✅" if row["count"] >= norm else "❌"
        lines.append(f"{format_user(row['username'], row['display_name'])} - {row['count']}/{norm} {mark}")
    await message.answer("\n".join(lines))


@router.message(Command("set_norm"))
async def cmd_set_norm(message: Message, command: CommandObject):
    if not await require_private_admin(message):
        return
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Формат: /set_norm <число>")
        return
    value = int(command.args.strip())
    if value <= 0:
        await message.answer("⚠️ Норма должна быть больше 0.")
        return
    set_weekly_norm(value)
    await message.answer(f"✅ Недельная норма обновлена: {value}.")


@router.message(Command("cleanup_off"))
async def cmd_cleanup_off(message: Message):
    if not await require_private_admin(message):
        return
    set_cleanup_enabled(False)
    await message.answer("✅ Авточистка отключена.")


@router.message(Command("cleanup_on"))
async def cmd_cleanup_on(message: Message):
    if not await require_private_admin(message):
        return
    set_cleanup_enabled(True)
    await message.answer("✅ Авточистка включена.")


@router.message(Command("cleanup_skip_once"))
async def cmd_cleanup_skip_once(message: Message):
    if not await require_private_admin(message):
        return
    set_cleanup_skip_once(True)
    await message.answer("✅ Следующая чистка будет пропущена.")


@router.message(Command("rest_add"))
async def cmd_rest_add(message: Message, command: CommandObject):
    if not await require_private_admin(message):
        return
    if not command.args:
        await message.answer("Формат: /rest_add <user_id|@username> <дней|0|YYYY-MM-DD> <роль>")
        return

    parts = command.args.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Формат: /rest_add <user_id|@username> <дней|0|YYYY-MM-DD> <роль>")
        return

    user_id = parse_target(parts[0])
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return

    period_raw = parts[1].strip()
    role_name = parts[2].strip()

    if re.fullmatch(r"\d+", period_raw):
        set_rest(user_id, role_name, int(period_raw), message.from_user.id)
        await message.answer("✅ Рест сохранен.")
        return

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", period_raw):
        try:
            until_date = datetime.strptime(period_raw, "%Y-%m-%d").date()
        except ValueError:
            await message.answer("⚠️ Неверная дата. Используйте YYYY-MM-DD.")
            return
        if until_date < datetime.now().date():
            await message.answer("⚠️ Дата окончания реста уже в прошлом.")
            return
        expires_at = datetime.combine(until_date, time(23, 59, 59)).isoformat(timespec="seconds")
        set_rest_until(user_id, role_name, expires_at, message.from_user.id)
        await message.answer(f"✅ Рест сохранен до {period_raw}.")
        return

    await message.answer("⚠️ Период должен быть числом дней, 0 или датой YYYY-MM-DD.")


@router.message(Command("rest_del"))
async def cmd_rest_del(message: Message, command: CommandObject):
    if not await require_private_admin(message):
        return
    if not command.args:
        await message.answer("Формат: /rest_del <user_id|@username>")
        return

    user_id = parse_target(command.args.strip())
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return
    remove_rest(user_id)
    await message.answer("✅ Рест удален.")


@router.message(Command("rests"))
async def cmd_rests(message: Message):
    if not await require_private_admin(message):
        return
    rows = get_all_rests()
    if not rows:
        await message.answer("ℹ️ Активных рестов нет.")
        return
    lines = ["🛌 Активные ресты:"]
    for row in rows[:200]:
        exp = row["expires_at"] or "без срока"
        lines.append(f"{format_user(row['username'], row['display_name'] or str(row['user_id']))} - {row['role_name']} ({exp})")
    await message.answer("\n".join(lines))


@router.message(Command("warn"))
async def cmd_warn(message: Message, command: CommandObject):
    if not await require_private_admin(message):
        return
    if not command.args:
        await message.answer("Формат: /warn <user_id|@username> <причина>")
        return

    parts = command.args.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Формат: /warn <user_id|@username> <причина>")
        return

    user_id = parse_target(parts[0])
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return

    warn_id, total, third = await issue_warn(user_id, message.from_user.id, parts[1].strip(), "manual")
    suffix = " Пользователь автоматически получил мут (3-й варн)." if third else ""
    await message.answer(f"✅ Варн выдан: #{warn_id}. Активных варнов: {total}.{suffix}")


@router.message(Command("unwarn"))
async def cmd_unwarn(message: Message, command: CommandObject):
    if not await require_private_admin(message):
        return
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Формат: /unwarn <warn_id>")
        return
    if remove_warn(int(command.args.strip())):
        await message.answer("✅ Варн снят.")
    else:
        await message.answer("⚠️ Активный варн с таким ID не найден.")


@router.message(Command("warns_all"))
async def cmd_warns_all(message: Message):
    if not await require_private_admin(message):
        return
    rows = get_all_warns(active_only=True)
    if not rows:
        await message.answer("ℹ️ Активных варнов нет.")
        return
    lines = ["⚠️ Активные варны:"]
    for row in rows[:250]:
        lines.append(
            f"#{row['id']} {format_user(row['username'], row['display_name'] or str(row['user_id']))} - "
            f"[{row['warn_type']}] {row['reason']}"
        )
    await message.answer("\n".join(lines))


@router.message(Command("warns_user"))
async def cmd_warns_user(message: Message, command: CommandObject):
    if not await require_private_admin(message):
        return
    if not command.args:
        await message.answer("Формат: /warns_user <user_id|@username>")
        return
    user_id = parse_target(command.args.strip())
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return
    rows = get_user_warns(user_id, active_only=True)
    if not rows:
        await message.answer("ℹ️ У пользователя нет активных варнов.")
        return
    lines = [f"⚠️ Активные варны пользователя {user_id}:"]
    for row in rows:
        lines.append(f"#{row['id']} [{row['warn_type']}] {row['reason']}")
    await message.answer("\n".join(lines))


@router.message(Command("complaints"))
async def cmd_complaints(message: Message):
    if not await require_private_admin(message):
        return
    rows = get_all_complaints()
    if not rows:
        await message.answer("Жалоб нет.")
        return
    lines = ["Жалобы:"]
    for row in rows[:200]:
        author = f"{format_user(row['username'], row['display_name'])} ({row['user_id']})"
        lines.append(f"#{row['id']} {row['created_at']} {author}: {row['text']}")
    await message.answer("\n".join(lines))


@router.message(Command("del_complaint"))
async def cmd_del_complaint(message: Message, command: CommandObject):
    if not await require_owner(message):
        return
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Формат: /del_complaint <id>")
        return
    complaint_id = int(command.args.strip())
    if delete_complaint(complaint_id):
        await message.answer("✅ Жалоба удалена.")
    else:
        await message.answer("⚠️ Жалоба с таким номером не найдена.")


@router.message(Command("kick"))
async def cmd_kick(message: Message, command: CommandObject):
    if not await require_private_admin(message):
        return
    if not command.args:
        await message.answer("Формат: /kick <user_id|@username> [причина]")
        return
    parts = command.args.split(maxsplit=1)
    user_id = parse_target(parts[0])
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return
    reason = parts[1] if len(parts) > 1 else "Без причины"
    try:
        group_id = get_group_id()
        await bot.ban_chat_member(group_id, user_id)
        await bot.unban_chat_member(group_id, user_id, only_if_banned=True)
        await message.answer(f"✅ Пользователь кикнут. Причина: {reason}.")
    except TelegramBadRequest as exc:
        await message.answer(f"⚠️ Не удалось кикнуть пользователя: {exc.message}")


@router.message(Command("ban"))
async def cmd_ban(message: Message, command: CommandObject):
    if not await require_private_admin(message):
        return
    if not command.args:
        await message.answer("Формат: /ban <user_id|@username> [причина]")
        return
    parts = command.args.split(maxsplit=1)
    user_id = parse_target(parts[0])
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return
    reason = parts[1] if len(parts) > 1 else "Без причины"
    try:
        await bot.ban_chat_member(get_group_id(), user_id)
        await message.answer(f"✅ Пользователь забанен. Причина: {reason}.")
    except TelegramBadRequest as exc:
        await message.answer(f"⚠️ Не удалось забанить пользователя: {exc.message}")


@router.message(Command("unban"))
async def cmd_unban(message: Message, command: CommandObject):
    if not await require_private_admin(message):
        return
    if not command.args:
        await message.answer("Формат: /unban <user_id|@username>")
        return
    user_id = parse_target(command.args.strip())
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return
    try:
        await bot.unban_chat_member(get_group_id(), user_id, only_if_banned=True)
        await message.answer("✅ Пользователь разбанен.")
    except TelegramBadRequest as exc:
        await message.answer(f"⚠️ Не удалось разбанить пользователя: {exc.message}")


@router.message(Command("mute"))
async def cmd_mute(message: Message, command: CommandObject):
    if not await require_private_admin(message):
        return
    if not command.args:
        await message.answer("Формат: /mute <user_id|@username> <минут> [причина]")
        return
    parts = command.args.split(maxsplit=2)
    if len(parts) < 2:
        await message.answer("Формат: /mute <user_id|@username> <минут> [причина]")
        return
    user_id = parse_target(parts[0])
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return
    if not parts[1].isdigit() or int(parts[1]) <= 0:
        await message.answer("⚠️ Время мута должно быть положительным числом.")
        return
    reason = parts[2] if len(parts) > 2 else "Без причины"
    await message.answer(await mute_user(user_id, int(parts[1]), message.from_user.id, reason))


@router.message(Command("unmute"))
async def cmd_unmute(message: Message, command: CommandObject):
    if not await require_private_admin(message):
        return
    if not command.args:
        await message.answer("Формат: /unmute <user_id|@username>")
        return
    user_id = parse_target(command.args.strip())
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return
    await message.answer(await unmute_user(user_id))


@router.message(Command("role"))
async def cmd_role(message: Message, command: CommandObject):
    if not await require_private_admin(message):
        return
    if not command.args:
        await message.answer("Формат: /role <user_id|@username> <подпись>")
        return
    parts = command.args.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Формат: /role <user_id|@username> <подпись>")
        return
    user_id = parse_target(parts[0])
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return

    await message.answer(await apply_role_signature(user_id, parts[1].strip()))


@router.message(Command("unrole"))
async def cmd_unrole(message: Message, command: CommandObject):
    if not await require_private_admin(message):
        return
    if not command.args:
        await message.answer("Формат: /unrole <user_id|@username>")
        return
    user_id = parse_target(command.args.strip())
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return
    await message.answer(await remove_role_signature(user_id))


@router.message(Command("add_admin"))
async def cmd_add_admin(message: Message, command: CommandObject):
    if not await require_owner(message):
        return
    if not command.args:
        await message.answer("Формат: /add_admin <user_id> <имя>")
        return
    parts = command.args.split(maxsplit=1)
    if len(parts) < 2 or not parts[0].isdigit():
        await message.answer("Формат: /add_admin <user_id> <имя>")
        return
    add_admin(int(parts[0]), parts[1].strip())
    await message.answer("✅ Админ добавлен.")


@router.message(Command("del_admin"))
async def cmd_del_admin(message: Message, command: CommandObject):
    if not await require_owner(message):
        return
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Формат: /del_admin <user_id>")
        return
    remove_admin(int(command.args.strip()))
    await message.answer("✅ Админ удален.")


@router.message(Command("admins"))
async def cmd_admins(message: Message):
    if not await require_private_admin(message):
        return
    rows = get_admins()
    if not rows:
        await message.answer("ℹ️ Список админов пуст.")
        return
    await message.answer("\n".join(f"{row['user_id']} - {row['name']}" for row in rows))


@router.message(Command("say"))
async def cmd_say(message: Message, command: CommandObject):
    if not await require_owner(message):
        return
    if not command.args:
        await message.answer("Формат: /say <текст>")
        return
    try:
        await bot.send_message(get_group_id(), command.args)
        await message.answer("✅ Отправлено.")
    except TelegramBadRequest as exc:
        await message.answer(f"⚠️ Не удалось отправить сообщение: {exc.message}")


@router.message(Command("set_group_id"))
async def cmd_set_group_id(message: Message, command: CommandObject):
    if not await require_owner(message):
        return
    if not command.args:
        await message.answer("Формат: /set_group_id <-100...>")
        return
    raw = command.args.strip()
    if not re.fullmatch(r"-?\d+", raw):
        await message.answer("⚠️ ID группы должен быть числом.")
        return
    set_group_id(int(raw))
    await message.answer(f"✅ Целевая группа обновлена: {int(raw)}")


@router.message(Command("show_config"))
async def cmd_show_config(message: Message):
    if not await require_owner(message):
        return

    params = get_all_params()
    lines = [
        "⚙️ Текущая конфигурация:",
        f"OWNER_ID: {OWNER_ID}",
        f"GROUP_ID: {get_group_id()}",
        f"WEEKLY_NORM: {get_weekly_norm()}",
        f"CLEANUP_ENABLED: {'1' if is_cleanup_enabled() else '0'}",
        f"inactivity_notice_days: {params['inactivity_notice_days']}",
        f"inactivity_warn_days: {params['inactivity_warn_days']}",
        f"spam_limit_count: {params['spam_limit_count']}",
        f"spam_window_seconds: {params['spam_window_seconds']}",
        f"spam_mute_minutes: {params['spam_mute_minutes']}",
        f"raid_join_limit: {params['raid_join_limit']}",
        f"raid_window_seconds: {params['raid_window_seconds']}",
        f"raid_mode_minutes: {params['raid_mode_minutes']}",
        f"third_warn_mute_minutes: {params['third_warn_mute_minutes']}",
    ]
    await message.answer("\n".join(lines))


@router.message(Command("set_param"))
async def cmd_set_param(message: Message, command: CommandObject):
    if not await require_owner(message):
        return
    if not command.args:
        names = ", ".join(PARAM_DEFAULTS.keys())
        await message.answer(f"Формат: /set_param <name> <value>\nДоступные name: {names}")
        return

    parts = command.args.split(maxsplit=1)
    if len(parts) < 2:
        names = ", ".join(PARAM_DEFAULTS.keys())
        await message.answer(f"Формат: /set_param <name> <value>\nДоступные name: {names}")
        return

    name = parts[0].strip()
    if name not in PARAM_DEFAULTS:
        names = ", ".join(PARAM_DEFAULTS.keys())
        await message.answer(f"⚠️ Неизвестный параметр.\nДоступные name: {names}")
        return

    raw_value = parts[1].strip()
    if not re.fullmatch(r"-?\d+", raw_value):
        await message.answer("⚠️ Значение должно быть целым числом.")
        return

    value = int(raw_value)
    if value <= 0:
        await message.answer("⚠️ Значение должно быть больше 0.")
        return

    params = get_all_params()
    if name == "inactivity_notice_days" and value >= params["inactivity_warn_days"]:
        await message.answer("⚠️ inactivity_notice_days должно быть меньше inactivity_warn_days.")
        return
    if name == "inactivity_warn_days" and value <= params["inactivity_notice_days"]:
        await message.answer("⚠️ inactivity_warn_days должно быть больше inactivity_notice_days.")
        return

    set_int_param(name, value)
    await message.answer(f"✅ Параметр обновлен: {name}={value}")


@router.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"^\+роль\s+.+$"))
async def private_role_plus(message: Message):
    if not await require_private_admin(message):
        return
    match = re.match(r"^\+роль\s+(@\w+|-?\d+)\s+(.+)$", message.text.strip(), flags=re.IGNORECASE)
    if not match:
        await message.answer("Формат: +роль @username роль")
        return
    user_id = parse_target(match.group(1).strip())
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return
    title = match.group(2).strip()
    await message.answer(await apply_role_signature(user_id, title))


@router.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"^-роль\s+.+$"))
async def private_role_minus(message: Message):
    if not await require_private_admin(message):
        return
    match = re.match(r"^-роль\s+(@\w+|-?\d+)$", message.text.strip(), flags=re.IGNORECASE)
    if not match:
        await message.answer("Формат: -роль @username")
        return
    user_id = parse_target(match.group(1).strip())
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return
    await message.answer(await remove_role_signature(user_id))


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_NORM_STATS)
async def btn_norm_stats(message: Message):
    await cmd_norm_stats(message)


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_RESTS)
async def btn_rests(message: Message):
    await cmd_rests(message)


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_WARNS_ALL)
async def btn_warns_all(message: Message):
    await cmd_warns_all(message)


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_ADMINS)
async def btn_admins(message: Message):
    await cmd_admins(message)


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_COMPLAINTS)
async def btn_complaints(message: Message):
    await cmd_complaints(message)


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_COMPLAINT_DEL)
async def btn_complaints_del(message: Message):
    if not await require_owner(message):
        return
    await message.answer("Формат: /del_complaint <id>")


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_SHOW_CONFIG)
async def btn_show_config(message: Message):
    await cmd_show_config(message)


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_CLEANUP_ON)
async def btn_cleanup_on(message: Message):
    await cmd_cleanup_on(message)


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_CLEANUP_OFF)
async def btn_cleanup_off(message: Message):
    await cmd_cleanup_off(message)


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_CLEANUP_SKIP)
async def btn_cleanup_skip(message: Message):
    await cmd_cleanup_skip_once(message)


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_ROLE_SET)
async def btn_role_set(message: Message):
    if not await require_private_admin(message):
        return
    await message.answer("Формат: +роль @username роль")


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_ROLE_DEL)
async def btn_role_del(message: Message):
    if not await require_private_admin(message):
        return
    await message.answer("Формат: -роль @username")


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_PROMPT_WARN)
async def btn_prompt_warn(message: Message):
    if not await require_private_admin(message):
        return
    await message.answer("Формат: /warn <user_id|@username> <причина>")


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_PROMPT_UNWARN)
async def btn_prompt_unwarn(message: Message):
    if not await require_private_admin(message):
        return
    await message.answer("Формат: /unwarn <warn_id>")


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_PROMPT_REST)
async def btn_prompt_rest(message: Message):
    if not await require_private_admin(message):
        return
    await message.answer("Формат: /rest_add <user_id|@username> <дней|0|YYYY-MM-DD> <роль>")


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_PROMPT_UNREST)
async def btn_prompt_unrest(message: Message):
    if not await require_private_admin(message):
        return
    await message.answer("Формат: /rest_del <user_id|@username>")


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_PROMPT_MUTE)
async def btn_prompt_mute(message: Message):
    if not await require_private_admin(message):
        return
    await message.answer("Формат: /mute <user_id|@username> <минут> [причина]")


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_PROMPT_UNMUTE)
async def btn_prompt_unmute(message: Message):
    if not await require_private_admin(message):
        return
    await message.answer("Формат: /unmute <user_id|@username>")


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_PROMPT_BAN)
async def btn_prompt_ban(message: Message):
    if not await require_private_admin(message):
        return
    await message.answer("Формат: /ban <user_id|@username> [причина]")


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_PROMPT_UNBAN)
async def btn_prompt_unban(message: Message):
    if not await require_private_admin(message):
        return
    await message.answer("Формат: /unban <user_id|@username>")


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_PROMPT_KICK)
async def btn_prompt_kick(message: Message):
    if not await require_private_admin(message):
        return
    await message.answer("Формат: /kick <user_id|@username> [причина]")


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_PROMPT_SAY)
async def btn_prompt_say(message: Message):
    if not await require_owner(message):
        return
    await message.answer("Формат: /say <текст>")


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_PROMPT_SET_PARAM)
async def btn_prompt_set_param(message: Message):
    if not await require_owner(message):
        return
    names = ", ".join(PARAM_DEFAULTS.keys())
    await message.answer(f"Формат: /set_param <name> <value>\nДоступные name: {names}")
