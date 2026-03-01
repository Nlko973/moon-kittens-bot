from datetime import datetime, timedelta
from html import escape
from typing import Optional

APP_NAME = "Moon Kittens Bot"

ACCESS_DENIED = "нет доступа"
OWNER_ONLY = "нет доступа"
USER_NOT_FOUND = "⚠️ Не удалось определить пользователя. Используйте telegram id или @username."

START_TEXT = (
    f"🤖 {APP_NAME}\n"
    "Через кнопки ниже можно посмотреть свою норму, рест, варны и отправить жалобу."
)

ADMIN_HELP = (
    "Команды админа (ЛС):\n"
    "/norm_stats\n"
    "/set_norm <число>\n"
    "/cleanup_off | /cleanup_on | /cleanup_skip_once\n"
    "/tg_links_on | /tg_links_off | /tg_links_status\n"
    "/rest_add <user> <срок|0|YYYY-MM-DD> <роль>\n"
    "/rest_extend <user> <срок>\n"
    "/rest_del <user>\n"
    "/rests\n"
    "/warn <user> <срок> <причина>\n"
    "/unwarn <warn_id>\n"
    "/warns_all\n"
    "/warns_user <user>\n"
    "/complaints\n"
    "/del_complaint <id> (владелец)\n"
    "/db_users (владелец)\n"
    "/db_user_del <user_id> (владелец)\n"
    "/kick <user> [причина]\n"
    "/ban <user> [причина]\n"
    "/unban <user>\n"
    "/mute <user> <минут> [причина]\n"
    "/unmute <user>\n"
    "/say_photo <file_id> [подпись] (владелец)\n"
    "/say_gif <file_id> [подпись] (владелец)\n"
    "/say_video <file_id> [подпись] (владелец)\n"
    "+роль @username роль\n"
    "-роль @username\n"
    "Команды в группе: варн/мут/бан/кик @username ...\n"
    "Только владелец: /add_admin, /del_admin, /say, /set_group_id, /show_config, /set_param"
)


def _trim_name(name: str, max_len: int = 25) -> str:
    name = (name or "").strip()
    if len(name) <= max_len:
        return name
    return name[:max_len]


def format_user(user_id: int, username: Optional[str], display_name: str) -> str:
    if username:
        return f"@{username}"
    short_name = escape(_trim_name(display_name or str(user_id)))
    return f'<a href="tg://user?id={user_id}">{short_name}</a>'


def week_period(now: datetime) -> str:
    monday = now.date() - timedelta(days=now.weekday())
    sunday = monday + timedelta(days=6)
    return f"{monday.isoformat()} - {sunday.isoformat()}"


def norm_status_text(user_id: int, username: Optional[str], display_name: str, count: int, norm: int) -> str:
    has_norm = count >= norm
    status = "есть норма" if has_norm else "нет нормы"
    mark = "✅" if has_norm else "❌"
    return f"{format_user(user_id, username, display_name)} - у вас {status} ({count}/{norm}) {mark}"


def rest_status_none(user_id: int, username: Optional[str], display_name: str) -> str:
    return f"{format_user(user_id, username, display_name)} - у вас нет реста."


def rest_status_infinite(user_id: int, username: Optional[str], display_name: str, role_name: str) -> str:
    return f"{format_user(user_id, username, display_name)} - рест активен бессрочно ({role_name})."


def rest_status_with_days(user_id: int, username: Optional[str], display_name: str, role_name: str, days: int) -> str:
    return f"{format_user(user_id, username, display_name)} - рест активен ({role_name}), осталось ~{days} дн."


def owner_third_warn_notice(user_id: int, username: Optional[str], display_name: str, warn_id: int) -> str:
    return (
        "🚨 Пользователь получил 3-й активный варн.\n"
        f"Пользователь: {format_user(user_id, username, display_name)} ({user_id})\n"
        f"Последний варн: #{warn_id}\n"
        "Действие: автоматически выдан мут на 30 дней."
    )
