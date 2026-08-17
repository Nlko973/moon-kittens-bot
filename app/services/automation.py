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
from app.services.owner_notifications import owner_notification_recipients
from app.services.user_identity import remember_user, resolve_user_label
from app.texts import cleanup_period, format_user
from db import (
    CLEANUP_INTERVAL_DAYS,
    CLEANUP_PERIOD_WEEKS,
    add_message,
    consume_cleanup_skip_once,
    delete_absent_over_30_days,
    get_cleanup_candidates,
    get_expired_mutes,
    get_biweekly_norm,
    get_inactive_candidates,
    get_last_cleanup_date,
    get_user_brief,
    get_user_week_count,
    is_cleanup_enabled,
    is_inactive_checks_enabled,
    is_on_rest,
    mark_inactive_notice,
    mark_inactive_warned,
    mark_users_seen_first_cleanup,
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


def _is_newcomer(row) -> bool:
    return not row["first_cleanup_at"]


async def _send_friday_lacking_report():
    rows = get_cleanup_candidates()
    norm = get_biweekly_norm()
    lacking = [row for row in rows if row["count"] < norm]
    total = len(rows)
    ok_count = total - len(lacking)
    period = cleanup_period(datetime.now())

    if not lacking:
        await bot.send_message(
            get_group_id(),
            (
                "📊 <b>Пятничный отчет по норме</b>\n"
                f"Период: {period}\n"
                f"Норма: <b>{norm}</b> за 2 недели\n"
                f"Участников в учете: <b>{total}</b>\n"
                "🎉 У всех есть норма за 2 недели."
            ),
        )
        return

    lines = [
        "📊 <b>Пятничный отчет по норме</b>",
        f"Период: {period}",
        f"Норма: <b>{norm}</b> за 2 недели",
        f"Участников в учете: <b>{total}</b>",
        f"С нормой: <b>{ok_count}</b>",
        f"Без нормы: <b>{len(lacking)}</b>",
        "",
        "<b>Без нормы:</b>",
    ]
    for idx, row in enumerate(lacking[:80], start=1):
        newcomer_mark = (
            " · 🆕 нью"
            if _is_newcomer(row)
            else ""
        )
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
    norm = get_biweekly_norm()
    rows = get_cleanup_candidates()

    punished = []
    skipped_newcomers = []
    auto_warn_minutes = 60 * 24 * 30

    for row in rows:
        if row["count"] >= norm:
            continue
        if _is_newcomer(row):
            skipped_newcomers.append(row)
            continue

        warn_id, _total, _third, _expires_at = await issue_warn(
            row["user_id"],
            0,
            "Нет нормы за 2 недели",
            "norma",
            duration_minutes=auto_warn_minutes,
        )
        punished.append((row, warn_id))

    if punished:
        lines = [f"?? Чистка за 2 недели {cleanup_period(datetime.now())}. Выдано варнов: {len(punished)}."]
        for row, warn_id in punished[:60]:
            user_label = await resolve_user_label(row["user_id"], row["display_name"])
            lines.append(f"- #{warn_id} {user_label}: {row['count']}/{norm}")
        if skipped_newcomers:
            lines.append(f"🆕 нью без варна: {len(skipped_newcomers)}.")
        await _send_chunked(group_id, lines)
    else:
        extra = ""
        if skipped_newcomers:
            extra = f" Новичков без варна: {len(skipped_newcomers)}."
        await bot.send_message(group_id, f"?? Чистка за 2 недели {cleanup_period(datetime.now())}: нарушений нет.{extra}")

    owner_lines = [
        f"?? Статистика чистки за 2 недели {cleanup_period(datetime.now())}:",
        f"Норма: {norm} за период",
        f"Всего участников в учете: {len(rows)}",
        f"Выдано варнов: {len(punished)}",
        f"Пропущено 🆕 нью: {len(skipped_newcomers)}",
    ]
    if punished:
        owner_lines.append("Список с варнами:")
        for row, warn_id in punished[:200]:
            user_label = await resolve_user_label(row["user_id"], row["display_name"])
            owner_lines.append(f"- #{warn_id} {user_label} ({row['count']}/{norm})")

    try:
        for chat_id in owner_notification_recipients():
            await _send_chunked(chat_id, owner_lines)
    except TelegramBadRequest:
        pass


async def run_inactivity_checks():
    if not is_inactive_checks_enabled():
        return

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


def _next_due_sunday(now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now()
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


def _is_cleanup_friday(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now()
    return now.weekday() == 4 and _next_due_sunday(now).date() == (now.date() + timedelta(days=2))


async def background_jobs():
    global last_daily_run, last_friday_report

    while True:
        now = datetime.now()

        # Time-sensitive reports first, so long daily checks don't delay them.
        if _is_cleanup_friday(now) and now.hour >= 18:
            today = now.date().isoformat()
            if last_friday_report != today:
                ok = await _run_job_with_timeout(
                    _send_friday_lacking_report(),
                    timeout_seconds=120,
                    label="friday lacking report",
                )
                if ok:
                    last_friday_report = today

        if now.weekday() == 6 and (now.hour, now.minute) >= (23, 55):
            today = now.date().isoformat()
            last_cleanup_date = get_last_cleanup_date()
            cleanup_due = last_cleanup_date != today
            if cleanup_due and last_cleanup_date:
                try:
                    last_dt = datetime.fromisoformat(last_cleanup_date)
                    cleanup_due = (now.date() - last_dt.date()).days >= CLEANUP_INTERVAL_DAYS
                except ValueError:
                    cleanup_due = True

            if cleanup_due:

                async def _sunday_cleanup_once():
                    group_id = get_group_id()
                    rows = get_cleanup_candidates()
                    if consume_cleanup_skip_once():
                        await bot.send_message(group_id, "?? Чистка за 2 недели пропущена (одноразовый пропуск).")
                    elif not is_cleanup_enabled():
                        pass
                    else:
                        await run_week_cleanup()
                    mark_users_seen_first_cleanup([int(row["user_id"]) for row in rows], at=now)
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





