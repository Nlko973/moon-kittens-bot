import asyncio
import logging
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
from app.services.user_identity import remember_user, resolve_user_label
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
last_friday_report: Optional[str] = None
logger = logging.getLogger(__name__)


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


def _is_newcomer(first_seen_at: Optional[str], min_days: int = 7) -> bool:
    if not first_seen_at:
        return False
    try:
        joined_at = datetime.fromisoformat(first_seen_at)
    except (TypeError, ValueError):
        return False
    return datetime.now() - joined_at < timedelta(days=min_days)


async def _send_friday_lacking_report():
    rows = get_cleanup_candidates()
    norm = get_weekly_norm()
    lacking = [row for row in rows if row["count"] < norm]
    total = len(rows)
    ok_count = total - len(lacking)
    period = week_period(datetime.now())

    if not lacking:
        await bot.send_message(
            get_group_id(),
            (
                "📊 <b>Пятничный отчет по норме</b>\n"
                f"Период: {period}\n"
                f"Норма: <b>{norm}</b>\n"
                f"Участников в учете: <b>{total}</b>\n"
                "🎉 У всех есть недельная норма."
            ),
        )
        return

    lines = [
        "📊 <b>Пятничный отчет по норме</b>",
        f"Период: {period}",
        f"Норма: <b>{norm}</b>",
        f"Участников в учете: <b>{total}</b>",
        f"С нормой: <b>{ok_count}</b>",
        f"Без нормы: <b>{len(lacking)}</b>",
        "",
        "<b>Без нормы:</b>",
    ]
    for idx, row in enumerate(lacking[:80], start=1):
        newcomer_mark = " · новичок (меньше 7 дней)" if _is_newcomer(row["first_seen_at"]) else ""
        fallback = row["display_name"] or str(row["user_id"])
        try:
            # Don't block whole report on slow Telegram profile lookup.
            user_label = await asyncio.wait_for(
                resolve_user_label(row["user_id"], row["display_name"]),
                timeout=0.35,
            )
        except Exception:
            user_label = format_user(row["user_id"], None, fallback)
        lines.append(f"{idx}. {user_label} - <b>{row['count']}/{norm}</b>{newcomer_mark}")

    await _send_chunked(get_group_id(), lines)

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
    remember_user(user)

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
        user_label = await resolve_user_label(user.id, user.full_name)
        await message.answer(f"{user_label} - {text}")
        bucket.clear()
        return

    if raid_mode_until and now < raid_mode_until:
        count = get_user_week_count(user.id)
        if count <= 2:
            text = await mute_user(user.id, 30, 0, "Антирейд")
            user_label = await resolve_user_label(user.id, user.full_name)
            await message.answer(f"{user_label} - {text}")


async def run_week_cleanup():
    group_id = get_group_id()
    norm = get_weekly_norm()
    rows = get_cleanup_candidates()

    punished = []
    skipped_newcomers = []
    auto_warn_minutes = 60 * 24 * 30

    for row in rows:
        if row["count"] >= norm:
            continue
        if _is_newcomer(row["first_seen_at"]):
            skipped_newcomers.append(row)
            continue

        warn_id, _total, _third, _expires_at = await issue_warn(
            row["user_id"],
            0,
            "Нет недельной нормы",
            "norma",
            duration_minutes=auto_warn_minutes,
        )
        punished.append((row, warn_id))

    if punished:
        lines = [f"?? Чистка за неделю {week_period(datetime.now())}. Выдано варнов: {len(punished)}."]
        for row, warn_id in punished[:60]:
            user_label = await resolve_user_label(row["user_id"], row["display_name"])
            lines.append(f"- #{warn_id} {user_label}: {row['count']}/{norm}")
        if skipped_newcomers:
            lines.append(f"Новички (меньше 7 дней) без варна: {len(skipped_newcomers)}.")
        await _send_chunked(group_id, lines)
    else:
        extra = ""
        if skipped_newcomers:
            extra = f" Новичков без варна: {len(skipped_newcomers)}."
        await bot.send_message(group_id, f"?? Чистка за неделю {week_period(datetime.now())}: нарушений нет.{extra}")

    owner_lines = [
        f"?? Статистика чистки за неделю {week_period(datetime.now())}:",
        f"Норма: {norm}",
        f"Всего участников в учете: {len(rows)}",
        f"Выдано варнов: {len(punished)}",
        f"Пропущено новичков (меньше 7 дней): {len(skipped_newcomers)}",
    ]
    if punished:
        owner_lines.append("Список с варнами:")
        for row, warn_id in punished[:200]:
            user_label = await resolve_user_label(row["user_id"], row["display_name"])
            owner_lines.append(f"- #{warn_id} {user_label} ({row['count']}/{norm})")

    try:
        await _send_chunked(OWNER_ID, owner_lines)
    except TelegramBadRequest:
        pass


async def run_inactivity_checks():
    group_id = get_group_id()
    inactivity_notice_days = get_int_param("inactivity_notice_days")
    inactivity_warn_days = get_int_param("inactivity_warn_days")

    to_notice = get_inactive_candidates(inactivity_notice_days)
    for row in to_notice:
        if row["inactive_notice_at"] or row["inactive_warned_at"]:
            continue
        user_tag = await resolve_user_label(row["user_id"], row["display_name"])
        await bot.send_message(
            group_id,
            (
                f"? {user_tag} — вы были неактивны {inactivity_notice_days} дней. "
                f"Если не напишете сообщение, через {inactivity_warn_days - inactivity_notice_days} дней "
                "будет выдан варн за неактив."
            ),
        )
        mark_inactive_notice(row["user_id"])

    to_warn = get_inactive_candidates(inactivity_warn_days)
    for row in to_warn:
        if row["inactive_warned_at"]:
            continue
        warn_id, _total, _third, _expires_at = await issue_warn(
            row["user_id"],
            0,
            f"\u041d\u0435\u0430\u043a\u0442\u0438\u0432 {inactivity_warn_days} \u0434\u043d\u0435\u0439",
            "inactive",
            duration_minutes=60 * 24 * 30,
        )
        mark_inactive_warned(row["user_id"])
        user_tag = await resolve_user_label(row["user_id"], row["display_name"])
        await bot.send_message(group_id, f"?? {user_tag} — выдан варн за неактив (#{warn_id}).")


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
                    f"✅ {await resolve_user_label(row['user_id'], brief['display_name'])} — мут автоматически снят.",
                )
        except TelegramBadRequest:
            remove_mute(row["user_id"])


async def _run_job_with_timeout(coro, timeout_seconds: int, label: str) -> bool:
    try:
        await asyncio.wait_for(coro, timeout=timeout_seconds)
        return True
    except asyncio.TimeoutError:
        logger.exception("Background job timed out: %s (%ss)", label, timeout_seconds)
    except Exception:
        logger.exception("Background job failed: %s", label)
    return False


async def background_jobs():
    global last_daily_run, last_friday_report

    while True:
        now = datetime.now()

        # Time-sensitive reports first, so long daily checks don't delay them.
        if now.weekday() == 4 and now.hour >= 18:
            today = now.date().isoformat()
            if last_friday_report != today:
                ok = await _run_job_with_timeout(
                    _send_friday_lacking_report(),
                    timeout_seconds=120,
                    label="friday lacking report",
                )
                if ok:
                    last_friday_report = today

        if now.weekday() == 6 and now.hour >= 20:
            today = now.date().isoformat()
            if get_last_cleanup_date() != today:

                async def _sunday_cleanup_once():
                    group_id = get_group_id()
                    if consume_cleanup_skip_once():
                        await bot.send_message(group_id, "?? Чистка недели пропущена (одноразовый пропуск).")
                        set_last_cleanup_date(today)
                    elif not is_cleanup_enabled():
                        set_last_cleanup_date(today)
                    else:
                        await run_week_cleanup()
                        set_last_cleanup_date(today)

                await _run_job_with_timeout(
                    _sunday_cleanup_once(),
                    timeout_seconds=300,
                    label="sunday cleanup",
                )

        await _run_job_with_timeout(
            run_unmute_checks(),
            timeout_seconds=60,
            label="run_unmute_checks",
        )

        if last_daily_run != now.date().isoformat():
            ok = await _run_job_with_timeout(
                run_inactivity_checks(),
                timeout_seconds=300,
                label="daily checks",
            )
            if ok:
                try:
                    delete_absent_over_30_days()
                except Exception:
                    logger.exception("Background job failed: delete_absent_over_30_days")
                last_daily_run = now.date().isoformat()

        await asyncio.sleep(30)





