from datetime import datetime, timedelta
from typing import Optional


APP_NAME = "Moon Kittens Bot"


def format_user(username: Optional[str], display_name: str) -> str:
    return f"@{username}" if username else display_name


def week_period(now: datetime) -> str:
    monday = now.date() - timedelta(days=now.weekday())
    sunday = monday + timedelta(days=6)
    return f"{monday.isoformat()} - {sunday.isoformat()}"


ACCESS_DENIED = "⛔ Нет доступа."
OWNER_ONLY = "⛔ Команда доступна только владельцу бота."
USER_NOT_FOUND = "⚠️ Не удалось определить пользователя. Используйте `id` или `@username` из базы."

START_TEXT = (
    f"🤖 {APP_NAME}\n"
    "Выберите действие в меню ниже."
)

MEMBER_HELP = (
    "📌 Команды участника:\n"
    "/mynorm — моя норма за неделю\n"
    "/myrest — мой рест\n"
    "/mywarns — мои варны"
)

ADMIN_HELP = (
    "🛠 Команды админа (в ЛС):\n"
    "/norm_stats\n"
    "/set_norm <число>\n"
    "/cleanup_off | /cleanup_on | /cleanup_skip_once\n"
    "/rest_add <user> <дней|0|YYYY-MM-DD> <роль>\n"
    "/rest_del <user>\n"
    "/rests\n"
    "/warn <user> <причина>\n"
    "/unwarn <warn_id>\n"
    "/warns_all\n"
    "/warns_user <user>\n"
    "/kick <user> [причина]\n"
    "/ban <user> [причина]\n"
    "/unban <user>\n"
    "/mute <user> <минут> [причина]\n"
    "/unmute <user>\n"
    "/role <user> <подпись>\n"
    "/unrole <user>\n"
    "Только владелец: /add_admin, /del_admin, /say, /set_group_id, /show_config, /set_param"
)


def norm_status_text(username: Optional[str], display_name: str, count: int, norm: int) -> str:
    has_norm = count >= norm
    status = "есть норма" if has_norm else "нет нормы"
    mark = "✅" if has_norm else "❌"
    return f"{format_user(username, display_name)} - у вас {status} ({count}/{norm}) {mark}"


def rest_status_none(username: Optional[str], display_name: str) -> str:
    return f"{format_user(username, display_name)} - у вас нет реста."


def rest_status_infinite(username: Optional[str], display_name: str, role_name: str) -> str:
    return f"{format_user(username, display_name)} - рест активен бессрочно ({role_name})."


def rest_status_with_days(username: Optional[str], display_name: str, role_name: str, days: int) -> str:
    return f"{format_user(username, display_name)} - рест активен ({role_name}), осталось ~{days} дн."


def owner_third_warn_notice(user_id: int, username: Optional[str], display_name: str, warn_id: int) -> str:
    return (
        "🚨 Пользователь получил 3-й активный варн.\n"
        f"Пользователь: {format_user(username, display_name)} ({user_id})\n"
        f"Последний варн: #{warn_id}\n"
        "Действие: автоматически выдан мут на 30 дней."
    )
