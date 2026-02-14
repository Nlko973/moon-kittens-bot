import asyncio
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Optional

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from app.runtime import bot
from app.services.access import is_bot_admin
from app.services.bot_config import get_int_param
from app.services.chat_settings import get_group_id
from app.services.moderation import issue_warn, mute_user, unmute_user
from app.texts import format_user, week_period
from config import OWNER_ID
from db import (
    add_message,
    consume_cleanup_skip_once,
    delete_absent_over_30_days,
    get_cleanup_candidates,
    get_expired_mutes,
    get_inactive_candidates,
    get_last_cleanup_date,
    get_user_brief,
    get_user_week_count,
    get_weekly_norm,
    is_cleanup_enabled,
    is_on_rest,
    mark_inactive_notice,
    mark_inactive_warned,
    remove_mute,
    set_last_cleanup_date,
)

spam_buckets = defaultdict(deque)
join_events = deque()
raid_mode_until: Optional[datetime] = None
last_daily_run: Optional[str] = None


async def _send_chunked(chat_id: int, lines: list[str], chunk_limit: int = 3500):
    chunk = ""
    for line in lines:
        candidate = f"{chunk}\n{line}" if chunk else line
        if len(candidate) > chunk_limit:
            if chunk:
                await bot.send_message(chat_id, chunk)
            chunk = line
        else:
            chunk = candidate
    if chunk:
        await bot.send_message(chat_id, chunk)


async def _send_pre_cleanup_report_to_owner(rows, norm: int):
    lacking = [row for row in rows if row["count"] < norm]
    ok = len(rows) - len(lacking)
    lines = [
        f"📈 Предчистка: {week_period(datetime.now())}",
        f"Норма: {norm}",
        f"Участников в учете: {len(rows)}",
        f"С нормой: {ok}",
        f"Без нормы: {len(lacking)}",
        "Список без нормы:",
    ]
    if lacking:
        for row in lacking[:200]:
            lines.append(f"- {format_user(row['username'], row['display_name'])}: {row['count']}/{norm}")
    else:
        lines.append("- Нет нарушителей")

    try:
        await _send_chunked(OWNER_ID, lines)
    except TelegramBadRequest:
        pass


def register_join_event() -> bool:
    global raid_mode_until
    raid_window_seconds = get_int_param("raid_window_seconds")
    raid_join_limit = get_int_param("raid_join_limit")
    raid_mode_minutes = get_int_param("raid_mode_minutes")

    now = datetime.now()
    join_events.append(now)
    while join_events and (now - join_events[0]).total_seconds() > raid_window_seconds:
        join_events.popleft()

    if len(join_events) >= raid_join_limit:
        raid_mode_until = now + timedelta(minutes=raid_mode_minutes)
        return True
    return False


async def add_message_and_guard(message: Message):
    global raid_mode_until
    spam_window_seconds = get_int_param("spam_window_seconds")
    spam_limit_count = get_int_param("spam_limit_count")
    spam_mute_minutes = get_int_param("spam_mute_minutes")

    user = message.from_user

    add_message(user_id=user.id, username=user.username, display_name=user.full_name)

    if is_bot_admin(user.id) or is_on_rest(user.id):
        return

    now = datetime.now()
    bucket = spam_buckets[user.id]
    bucket.append(now)
    while bucket and (now - bucket[0]).total_seconds() > spam_window_seconds:
        bucket.popleft()

    if len(bucket) >= spam_limit_count:
        text = await mute_user(user.id, spam_mute_minutes, 0, "Антиспам")
        await message.answer(f"{format_user(user.username, user.full_name)} - {text}")
        bucket.clear()
        return

    if raid_mode_until and now < raid_mode_until:
        count = get_user_week_count(user.id)
        if count <= 2:
            text = await mute_user(user.id, 30, 0, "Антирейд")
            await message.answer(f"{format_user(user.username, user.full_name)} - {text}")


async def run_week_cleanup():
    group_id = get_group_id()
    norm = get_weekly_norm()
    rows = get_cleanup_candidates()

    await _send_pre_cleanup_report_to_owner(rows, norm)

    punished = []
    for row in rows:
        if row["count"] >= norm:
            continue
        warn_id, _total, _third, _expires_at = await issue_warn(row["user_id"], 0, "Нет недельной нормы", "norma")
        punished.append((row, warn_id))

    if punished:
        lines = [f"🧹 Чистка за неделю {week_period(datetime.now())}. Выдано варнов: {len(punished)}."]
        for row, _warn_id in punished[:30]:
            lines.append(f"{format_user(row['username'], row['display_name'])} - {row['count']}/{norm}")
        await bot.send_message(group_id, "\n".join(lines))
    else:
        await bot.send_message(group_id, f"🧹 Чистка за неделю {week_period(datetime.now())}: нарушений нет.")


async def run_inactivity_checks():
    group_id = get_group_id()
    inactivity_notice_days = get_int_param("inactivity_notice_days")
    inactivity_warn_days = get_int_param("inactivity_warn_days")

    to_notice = get_inactive_candidates(inactivity_notice_days)
    for row in to_notice:
        if row["inactive_notice_at"]:
            continue
        user_tag = format_user(row["username"], row["display_name"])
        await bot.send_message(
            group_id,
            (
                f"⏳ {user_tag} — вы были неактивны {inactivity_notice_days} дней. "
                f"Если не напишете сообщение, через {inactivity_warn_days - inactivity_notice_days} дней "
                "будет выдан варн за неактив."
            ),
        )
        mark_inactive_notice(row["user_id"])

    to_warn = get_inactive_candidates(inactivity_warn_days)
    for row in to_warn:
        if row["inactive_warned_at"]:
            continue
        warn_id, _total, _third, _expires_at = await issue_warn(row["user_id"], 0, "Неактив 10 дней", "inactive")
        mark_inactive_warned(row["user_id"])
        user_tag = format_user(row["username"], row["display_name"])
        await bot.send_message(group_id, f"⚠️ {user_tag} — выдан варн за неактив (#{warn_id}).")


async def run_unmute_checks():
    group_id = get_group_id()
    rows = get_expired_mutes()
    for row in rows:
        try:
            await unmute_user(row["user_id"], silent=True)
            brief = get_user_brief(row["user_id"])
            if brief:
                await bot.send_message(
                    group_id,
                    f"✅ {format_user(brief['username'], brief['display_name'])} — мут автоматически снят.",
                )
        except TelegramBadRequest:
            remove_mute(row["user_id"])


async def background_jobs():
    global last_daily_run

    while True:
        try:
            now = datetime.now()
            await run_unmute_checks()

            if last_daily_run != now.date().isoformat():
                await run_inactivity_checks()
                delete_absent_over_30_days()
                last_daily_run = now.date().isoformat()

            if now.weekday() == 6 and now.hour >= 23 and now.minute >= 55:
                today = now.date().isoformat()
                if get_last_cleanup_date() != today:
                    group_id = get_group_id()
                    if consume_cleanup_skip_once():
                        await bot.send_message(group_id, "ℹ️ Чистка недели пропущена (одноразовый пропуск).")
                        set_last_cleanup_date(today)
                    elif not is_cleanup_enabled():
                        set_last_cleanup_date(today)
                    else:
                        await run_week_cleanup()
                        set_last_cleanup_date(today)
        except Exception:
            # Keep background scheduler alive even if a single task iteration fails.
            pass

        await asyncio.sleep(30)
