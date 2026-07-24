import re
from datetime import datetime, timedelta
from typing import Optional

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.runtime import bot
from app.keyboards import (
    BTN_ADM_ADD_ADMIN,
    BTN_ADM_ADMINS,
    BTN_ADM_DEL_ADMIN,
    BTN_ADM_DB_USERS,
    BTN_ADM_DB_USER_DEL,
    BTN_ADM_CLEANUP_OFF,
    BTN_ADM_CLEANUP_ON,
    BTN_ADM_CLEANUP_SKIP,
    BTN_ADM_CLEANUP_WHEN,
    BTN_ADM_TG_LINKS_OFF,
    BTN_ADM_TG_LINKS_ON,
    BTN_ADM_TG_LINKS_STATUS,
    BTN_ADM_COMPLAINTS,
    BTN_ADM_COMPLAINT_DEL,
    BTN_ADM_OWNER_MSGS,
    BTN_ADM_OWNER_MSG_DEL,
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
from app.services.duration_parser import parse_deadline, parse_ru_duration_to_minutes
from app.services.moderation import issue_warn, mute_user, unmute_user
from app.services.roles import apply_role_signature, remove_role_signature
from app.services.targets import parse_target
from app.services.user_identity import resolve_user_label
from app.texts import USER_NOT_FOUND, cleanup_period
from config import OWNER_ID
from db import (
    CLEANUP_INTERVAL_DAYS,
    CLEANUP_PERIOD_WEEKS,
    add_admin,
    count_users_in_db,
    delete_complaint,
    delete_owner_message,
    extend_rest,
    get_admins,
    get_all_complaints,
    get_all_owner_messages,
    get_all_rests,
    get_all_warns,
    get_cleanup_candidates,
    get_users_from_db,
    get_user_warns,
    get_weekly_norm,
    get_last_cleanup_date,
    is_cleanup_enabled,
    is_cleanup_skip_once_enabled,
    is_tg_links_block_enabled,
    remove_admin,
    remove_rest,
    remove_warn,
    remove_latest_warn_by_user,
    purge_user_from_db,
    set_cleanup_enabled,
    set_cleanup_skip_once,
    set_tg_links_block_enabled,
    set_rest_until,
    set_weekly_norm,
)

router = Router()


def _next_cleanup_dt(now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now()
    # Sunday 23:55 local server time
    days_ahead = (6 - now.weekday()) % 7
    candidate = (now + timedelta(days=days_ahead)).replace(hour=23, minute=55, second=0, microsecond=0)
    if candidate <= now:
        candidate = (candidate + timedelta(days=7)).replace(hour=23, minute=55, second=0, microsecond=0)

    last_cleanup_date = get_last_cleanup_date()
    if not last_cleanup_date:
        return candidate

    try:
        last_dt = datetime.fromisoformat(last_cleanup_date)
    except ValueError:
        return candidate

    earliest = (last_dt + timedelta(days=CLEANUP_INTERVAL_DAYS)).replace(hour=23, minute=55, second=0, microsecond=0)
    while candidate.date() < earliest.date():
        candidate = (candidate + timedelta(days=7)).replace(hour=23, minute=55, second=0, microsecond=0)
    return candidate


def _cleanup_status_text() -> str:
    enabled = is_cleanup_enabled()
    next_dt = _next_cleanup_dt()
    skip_once = is_cleanup_skip_once_enabled(next_dt)
    base = f"Ближайшая чистка: {next_dt.strftime('%Y-%m-%d %H:%M:%S')}"
    if not enabled:
        return f"{base} (авточистка отключена)"
    if skip_once:
        return f"{base} (текущая будет пропущена)"
    return f"{base} (включена)"


@router.message(Command("norm_stats"))
async def cmd_norm_stats(message: Message):
    if not await require_private_admin(message):
        return

    weekly_norm = get_weekly_norm()
    norm = weekly_norm * CLEANUP_PERIOD_WEEKS
    rows = get_cleanup_candidates()
    if not rows:
        await message.answer("ℹ️ Нет данных по текущему периоду.")
        return

    lines = [
        f"\U0001f4ca \u041d\u043e\u0440\u043c\u0430: {weekly_norm} \u0432 \u043d\u0435\u0434\u0435\u043b\u044e / {norm} \u0437\u0430 2 \u043d\u0435\u0434\u0435\u043b\u0438.",
        f"\u041f\u0435\u0440\u0438\u043e\u0434: {cleanup_period(message.date)}.",
        f"🧹 {_cleanup_status_text()}",
    ]
    for row in rows[:200]:
        mark = "✅" if row["count"] >= norm else "❌"
        user_label = await resolve_user_label(row["user_id"], row["display_name"])
        lines.append(f"{user_label} - {row['count']}/{norm} {mark}")
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
    await message.answer(f"✅ Норма обновлена: {value} в неделю / {value * CLEANUP_PERIOD_WEEKS} за 2 недели.")


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
    set_cleanup_skip_once(True, at=_next_cleanup_dt())
    await message.answer("✅ Текущая чистка будет пропущена.")


@router.message(Command("cleanup_when"))
async def cmd_cleanup_when(message: Message):
    if not await require_private_admin(message):
        return
    await message.answer(f"🧹 {_cleanup_status_text()}")


@router.message(Command("tg_links_on"))
async def cmd_tg_links_on(message: Message):
    if not await require_private_admin(message):
        return
    set_tg_links_block_enabled(True)
    await message.answer("✅ Запрет TG-ссылок включен.")


@router.message(Command("tg_links_off"))
async def cmd_tg_links_off(message: Message):
    if not await require_private_admin(message):
        return
    set_tg_links_block_enabled(False)
    await message.answer("✅ Запрет TG-ссылок отключен.")


@router.message(Command("tg_links_status"))
async def cmd_tg_links_status(message: Message):
    if not await require_private_admin(message):
        return
    status = "включен" if is_tg_links_block_enabled() else "выключен"
    await message.answer(f"ℹ️ Запрет TG-ссылок сейчас: {status}.")


@router.message(Command("rest_add"))
async def cmd_rest_add(message: Message, command: CommandObject):
    if not await require_private_admin(message):
        return
    if not command.args:
        await message.answer("Формат: /rest_add <user_id|@username> <срок|0|YYYY-MM-DD> <роль>")
        return

    tokens = command.args.split()
    if len(tokens) < 3:
        await message.answer("Формат: /rest_add <user_id|@username> <срок|0|YYYY-MM-DD> <роль>")
        return

    user_id = await parse_target(tokens[0])
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return

    rest_tokens = tokens[1:]
    for i in (1, 2):
        if len(rest_tokens) <= i:
            continue
        period_raw = " ".join(rest_tokens[:i]).strip().lower()
        role_name = " ".join(rest_tokens[i:]).strip()
        if not role_name:
            continue

        if period_raw in {"0", "бессрочно", "навсегда"}:
            set_rest_until(user_id, role_name, None, message.from_user.id)
            await message.answer("✅ Рест сохранен (бессрочно).")
            return

        deadline = parse_deadline(period_raw)
        if deadline and deadline > datetime.now():
            expires_at = deadline.isoformat(timespec="seconds")
            set_rest_until(user_id, role_name, expires_at, message.from_user.id)
            await message.answer(f"✅ Рест сохранен до {deadline.strftime('%Y-%m-%d %H:%M:%S')}.")
            return

    await message.answer("⚠️ Не удалось распознать срок. Пример: 2 дня, 5 часов, месяц, YYYY-MM-DD.")


@router.message(Command("rest_del"))
async def cmd_rest_del(message: Message, command: CommandObject):
    if not await require_private_admin(message):
        return
    if not command.args:
        await message.answer("Формат: /rest_del <user_id|@username>")
        return

    user_id = await parse_target(command.args.strip())
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return
    remove_rest(user_id)
    await message.answer("✅ Рест удален.")


@router.message(Command("rest_extend"))
async def cmd_rest_extend(message: Message, command: CommandObject):
    if not await require_private_admin(message):
        return
    if not command.args:
        await message.answer("Формат: /rest_extend <user_id|@username> <срок>")
        return

    parts = command.args.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Формат: /rest_extend <user_id|@username> <срок>")
        return

    user_id = await parse_target(parts[0].strip())
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return

    minutes = parse_ru_duration_to_minutes(parts[1].strip())
    if not minutes or minutes <= 0:
        await message.answer("⚠️ Не удалось распознать срок. Пример: 5 часов, 2 дня, 1 месяц.")
        return

    changed = extend_rest(user_id, int(minutes))
    if not changed:
        await message.answer("⚠️ У пользователя нет активного реста.")
        return

    await message.answer("✅ Рест продлен.")


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
        user_label = await resolve_user_label(row["user_id"], row["display_name"] or str(row["user_id"]))
        lines.append(f"{user_label} - {row['role_name']} ({exp})")
    await message.answer("\n".join(lines))


@router.message(Command("warn"))
async def cmd_warn(message: Message, command: CommandObject):
    if not await require_private_admin(message):
        return
    if not command.args:
        await message.answer("Формат: /warn <user_id|@username> <срок> <причина>")
        return

    parts = command.args.split()
    if len(parts) < 2:
        await message.answer("Формат: /warn <user_id|@username> <срок> <причина>")
        return

    user_id = await parse_target(parts[0])
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return

    expires_at = None
    reason = "Без причины"

    tail = parts[1:]
    parsed = False
    for i in (2, 1):
        if len(tail) < i:
            continue
        maybe_deadline = parse_deadline(" ".join(tail[:i]))
        if maybe_deadline and maybe_deadline > datetime.now():
            expires_at = maybe_deadline.isoformat(timespec="seconds")
            reason = " ".join(tail[i:]).strip() or "Без причины"
            parsed = True
            break
    if not parsed:
        reason = " ".join(tail).strip() or "Без причины"

    warn_id, total, third, expires_at = await issue_warn(
        user_id,
        message.from_user.id,
        reason,
        "manual",
        expires_at=expires_at,
    )
    expires_text = datetime.fromisoformat(expires_at).strftime("%Y-%m-%d %H:%M:%S")
    suffix = " Пользователь автоматически получил мут (3-й варн)." if third else ""
    await message.answer(f"✅ Варн выдан: #{warn_id}. Активных варнов: {total}. Срок до: {expires_text}.{suffix}")


@router.message(Command("unwarn"))
async def cmd_unwarn(message: Message, command: CommandObject):
    if not await require_private_admin(message):
        return
    if not command.args:
        await message.answer("Формат: /unwarn <warn_id|user_id|@username>")
        return

    raw = command.args.strip()
    if raw.isdigit():
        if remove_warn(int(raw)):
            await message.answer("✅ Варн снят.")
        else:
            await message.answer("⚠️ Активный варн с таким ID не найден.")
        return

    user_id = await parse_target(raw)
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return

    removed_warn_id = remove_latest_warn_by_user(user_id)
    if removed_warn_id is None:
        await message.answer("⚠️ У пользователя нет активных варнов.")
        return

    await message.answer(f"✅ Снят последний активный варн пользователя: #{removed_warn_id}.")


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
        user_label = await resolve_user_label(row["user_id"], row["display_name"] or str(row["user_id"]))
        lines.append(
            f"#{row['id']} {user_label} - "
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
    user_id = await parse_target(command.args.strip())
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
        author = f"{await resolve_user_label(row['user_id'], row['display_name'])} ({row['user_id']})"
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


@router.message(Command("owner_msgs"))
async def cmd_owner_msgs(message: Message):
    if not await require_private_admin(message):
        return
    rows = get_all_owner_messages()
    if not rows:
        await message.answer("Сообщений влд нет.")
        return
    lines = ["Сообщения влд:"]
    for row in rows[:200]:
        author = f"{await resolve_user_label(row['user_id'], row['display_name'])} ({row['user_id']})"
        lines.append(f"#{row['id']} {row['created_at']} {author}: {row['text']}")
    await message.answer("\n".join(lines))


@router.message(Command("del_owner_msg"))
async def cmd_del_owner_msg(message: Message, command: CommandObject):
    if not await require_owner(message):
        return
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Формат: /del_owner_msg <id>")
        return
    owner_message_id = int(command.args.strip())
    if delete_owner_message(owner_message_id):
        await message.answer("✅ Сообщение влд удалено.")
    else:
        await message.answer("⚠️ Сообщение влд с таким номером не найдено.")


@router.message(Command("kick"))
async def cmd_kick(message: Message, command: CommandObject):
    if not await require_private_admin(message):
        return
    if not command.args:
        await message.answer("Формат: /kick <user_id|@username> [причина]")
        return
    parts = command.args.split(maxsplit=1)
    user_id = await parse_target(parts[0])
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return
    reason = parts[1] if len(parts) > 1 else "No reason"
    try:
        group_id = get_group_id()
        await bot.ban_chat_member(group_id, user_id)
        await bot.unban_chat_member(group_id, user_id, only_if_banned=True)
        await message.answer(f"✅ Пользователь кикнут. Причина: {reason}.")
    except TelegramBadRequest as exc:
        await message.answer(f"⚠️ Не удалось кикнуть пользователя: {exc.message}")
    except Exception as exc:
        await message.answer(f"⚠️ Ошибка кика: {exc}")


@router.message(Command("ban"))
async def cmd_ban(message: Message, command: CommandObject):
    if not await require_private_admin(message):
        return
    if not command.args:
        await message.answer("Формат: /ban <user_id|@username> [причина]")
        return
    parts = command.args.split(maxsplit=1)
    user_id = await parse_target(parts[0])
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return
    reason = parts[1] if len(parts) > 1 else "No reason"
    try:
        await bot.ban_chat_member(get_group_id(), user_id)
        await message.answer(f"✅ Пользователь забанен. Причина: {reason}.")
    except TelegramBadRequest as exc:
        await message.answer(f"⚠️ Не удалось забанить пользователя: {exc.message}")
    except Exception as exc:
        await message.answer(f"⚠️ Ошибка бана: {exc}")


@router.message(Command("unban"))
async def cmd_unban(message: Message, command: CommandObject):
    if not await require_private_admin(message):
        return
    if not command.args:
        await message.answer("Формат: /unban <user_id|@username>")
        return
    user_id = await parse_target(command.args.strip())
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return
    try:
        await bot.unban_chat_member(get_group_id(), user_id, only_if_banned=True)
        await message.answer("✅ Пользователь разбанен.")
    except TelegramBadRequest as exc:
        await message.answer(f"⚠️ Не удалось разбанить пользователя: {exc.message}")
    except Exception as exc:
        await message.answer(f"⚠️ Ошибка разбана: {exc}")


@router.message(Command("mute"))
async def cmd_mute(message: Message, command: CommandObject):
    if not await require_private_admin(message):
        return
    if not command.args:
        await message.answer("Формат: /mute <user_id|@username> <минуты|5 минут|2 часа|1 день> [причина]")
        return
    parts = command.args.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Формат: /mute <user_id|@username> <минуты|5 минут|2 часа|1 день> [причина]")
        return
    user_id = await parse_target(parts[0].strip())
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return

    rest = parts[1].strip()
    minutes = None
    reason = "Без причины"

    simple = rest.split(maxsplit=1)
    if simple and simple[0].isdigit():
        minutes = int(simple[0])
        if len(simple) > 1:
            reason = simple[1].strip()
    else:
        match = re.match(r"^(?P<num>\d+)\s*(?P<unit>\S+)(?:\s+(?P<reason>.*))?$", rest)
        if match:
            duration_raw = f"{match.group('num')} {match.group('unit')}"
            minutes = parse_ru_duration_to_minutes(duration_raw)
            parsed_reason = (match.group("reason") or "").strip()
            if parsed_reason:
                reason = parsed_reason

    if not minutes or minutes <= 0:
        await message.answer("⚠️ Не удалось распознать время мута. Пример: /mute @user 5 минут флуд")
        return

    try:
        await message.answer(await mute_user(user_id, int(minutes), message.from_user.id, reason))
    except Exception as exc:
        await message.answer(f"⚠️ Ошибка мута: {exc}")


@router.message(Command("unmute"))
async def cmd_unmute(message: Message, command: CommandObject):
    if not await require_private_admin(message):
        return
    if not command.args:
        await message.answer("Формат: /unmute <user_id|@username>")
        return
    user_id = await parse_target(command.args.strip())
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
    user_id = await parse_target(parts[0])
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
    user_id = await parse_target(command.args.strip())
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return
    await message.answer(await remove_role_signature(user_id))


@router.message(Command("add_admin"))
async def cmd_add_admin(message: Message, command: CommandObject):
    if not await require_owner(message):
        return
    if not command.args:
        await message.answer("Формат: /add_admin <user_id|@username> [имя]")
        return
    parts = command.args.split(maxsplit=1)
    user_id = await parse_target(parts[0].strip())
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return
    name = parts[1].strip() if len(parts) > 1 else str(user_id)
    add_admin(int(user_id), name)
    await message.answer("✅ Админ добавлен.")


@router.message(Command("del_admin"))
async def cmd_del_admin(message: Message, command: CommandObject):
    if not await require_owner(message):
        return
    if not command.args:
        await message.answer("Формат: /del_admin <user_id|@username>")
        return
    user_id = await parse_target(command.args.strip())
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return
    remove_admin(int(user_id))
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
        await bot.send_message(get_group_id(), command.args, parse_mode=None)
        await message.answer("✅ Отправлено.")
    except TelegramBadRequest as exc:
        await message.answer(f"⚠️ Не удалось отправить сообщение: {exc.message}")


@router.message(Command("say_photo"))
async def cmd_say_photo(message: Message, command: CommandObject):
    if not await require_owner(message):
        return

    file_id = None
    caption = (command.args or "").strip() or None

    reply = message.reply_to_message
    if reply and reply.photo:
        file_id = reply.photo[-1].file_id

    if not file_id and command.args:
        parts = command.args.split(maxsplit=1)
        file_id = parts[0]
        caption = parts[1].strip() if len(parts) > 1 else None

    if not file_id:
        await message.answer("Формат: /say_photo <file_id> [подпись] или reply на фото с /say_photo [подпись]")
        return

    try:
        await bot.send_photo(get_group_id(), photo=file_id, caption=caption, parse_mode=None)
        await message.answer("✅ Фото отправлено.")
    except TelegramBadRequest as exc:
        await message.answer(f"⚠️ Не удалось отправить фото: {exc.message}")


@router.message(Command("say_gif"))
async def cmd_say_gif(message: Message, command: CommandObject):
    if not await require_owner(message):
        return

    file_id = None
    caption = (command.args or "").strip() or None

    reply = message.reply_to_message
    if reply and reply.animation:
        file_id = reply.animation.file_id
    elif reply and reply.document and reply.document.mime_type and "gif" in reply.document.mime_type.lower():
        file_id = reply.document.file_id

    if not file_id and command.args:
        parts = command.args.split(maxsplit=1)
        file_id = parts[0]
        caption = parts[1].strip() if len(parts) > 1 else None

    if not file_id:
        await message.answer("Формат: /say_gif <file_id> [подпись] или reply на GIF с /say_gif [подпись]")
        return

    try:
        await bot.send_animation(get_group_id(), animation=file_id, caption=caption, parse_mode=None)
        await message.answer("✅ GIF отправлен.")
    except TelegramBadRequest as exc:
        await message.answer(f"⚠️ Не удалось отправить GIF: {exc.message}")


@router.message(Command("say_video"))
async def cmd_say_video(message: Message, command: CommandObject):
    if not await require_owner(message):
        return

    file_id = None
    caption = (command.args or "").strip() or None

    reply = message.reply_to_message
    if reply and reply.video:
        file_id = reply.video.file_id

    if not file_id and command.args:
        parts = command.args.split(maxsplit=1)
        file_id = parts[0]
        caption = parts[1].strip() if len(parts) > 1 else None

    if not file_id:
        await message.answer("Формат: /say_video <file_id> [подпись] или reply на видео с /say_video [подпись]")
        return

    try:
        await bot.send_video(get_group_id(), video=file_id, caption=caption, parse_mode=None)
        await message.answer("✅ Видео отправлено.")
    except TelegramBadRequest as exc:
        await message.answer(f"⚠️ Не удалось отправить видео: {exc.message}")


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
        f"TG_LINKS_BLOCK: {'1' if is_tg_links_block_enabled() else '0'}",
        f"inactivity_notice_days: {params['inactivity_notice_days']}",
        f"inactivity_warn_days: {params['inactivity_warn_days']}",
        f"spam_limit_count: {params['spam_limit_count']}",
        f"spam_window_seconds: {params['spam_window_seconds']}",
        f"spam_mute_minutes: {params['spam_mute_minutes']}",
        f"raid_join_limit: {params['raid_join_limit']}",
        f"raid_window_seconds: {params['raid_window_seconds']}",
        f"raid_mode_minutes: {params['raid_mode_minutes']}",
        f"third_warn_mute_minutes: {params['third_warn_mute_minutes']}",
        f"cleanup_warn_duration_minutes: {params['cleanup_warn_duration_minutes']}",
    ]
    await message.answer("\n".join(lines))


@router.message(Command("db_users"))
async def cmd_db_users(message: Message):
    if not await require_owner(message):
        return
    rows = get_users_from_db(limit=300)
    total = count_users_in_db()
    if not rows:
        await message.answer("ℹ️ В базе нет участников.")
        return

    lines = [f"👥 Участники в БД: {total}. Показаны первые {len(rows)}."]
    for row in rows:
        user_id = int(row["user_id"])
        fallback = row["display_name"] or str(user_id)
        user_label = await resolve_user_label(user_id, fallback)
        status = "member=1" if int(row["is_member"] or 0) == 1 else "member=0"
        lines.append(f"{user_label} ({user_id}) • {status}")
    await message.answer("\n".join(lines))


@router.message(Command("db_user_del"))
async def cmd_db_user_del(message: Message, command: CommandObject):
    if not await require_owner(message):
        return
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Формат: /db_user_del <user_id>")
        return
    user_id = int(command.args.strip())
    removed = purge_user_from_db(user_id)
    if removed:
        await message.answer(f"✅ Пользователь {user_id} удален из БД.")
    else:
        await message.answer("⚠️ Пользователь не найден в users. Связанные записи очищены.")


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
    user_id = await parse_target(match.group(1).strip())
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
    user_id = await parse_target(match.group(1).strip())
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


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_OWNER_MSGS)
async def btn_owner_msgs(message: Message):
    await cmd_owner_msgs(message)


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_OWNER_MSG_DEL)
async def btn_owner_msgs_del(message: Message):
    if not await require_owner(message):
        return
    await message.answer("Формат: /del_owner_msg <id>")


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


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_CLEANUP_WHEN)
async def btn_cleanup_when(message: Message):
    await cmd_cleanup_when(message)


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_TG_LINKS_ON)
async def btn_tg_links_on(message: Message):
    await cmd_tg_links_on(message)


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_TG_LINKS_OFF)
async def btn_tg_links_off(message: Message):
    await cmd_tg_links_off(message)


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_TG_LINKS_STATUS)
async def btn_tg_links_status(message: Message):
    await cmd_tg_links_status(message)


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
    await message.answer("Формат: /warn <user_id|@username> <срок> <причина>\nИли просто /warn для пошагового ввода.")


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_PROMPT_UNWARN)
async def btn_prompt_unwarn(message: Message):
    if not await require_private_admin(message):
        return
    await message.answer("Формат: /unwarn <warn_id|user_id|@username>")


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_PROMPT_REST)
async def btn_prompt_rest(message: Message):
    if not await require_private_admin(message):
        return
    await message.answer(
        "Формат: /rest_add <user_id|@username> <срок|0|YYYY-MM-DD> <роль>\n"
        "Продление: /rest_extend <user_id|@username> <срок>\n"
        "Или просто /rest_add, /rest_extend для пошагового ввода."
    )


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
    await message.answer(
        "Форматы:\n"
        "/say <текст>\n"
        "/say_photo <file_id> [подпись] или reply на фото\n"
        "/say_gif <file_id> [подпись] или reply на GIF\n"
        "/say_video <file_id> [подпись] или reply на видео"
    )


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_PROMPT_SET_PARAM)
@router.message(F.chat.type == ChatType.PRIVATE, F.text == "Параметр")
async def btn_prompt_set_param(message: Message):
    if not await require_owner(message):
        return
    names = ", ".join(PARAM_DEFAULTS.keys())
    await message.answer(f"Формат: /set_param <name> <value>\nДоступные name: {names}")


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_ADD_ADMIN)
async def btn_prompt_add_admin(message: Message):
    if not await require_owner(message):
        return
    await message.answer("Формат: /add_admin <user_id> <имя>")


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_DEL_ADMIN)
async def btn_prompt_del_admin(message: Message):
    if not await require_owner(message):
        return
    await message.answer("Формат: /del_admin <user_id>")

@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_DB_USERS)
async def btn_db_users(message: Message):
    await cmd_db_users(message)



