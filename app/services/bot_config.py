from config import (
    INACTIVITY_NOTICE_DAYS,
    INACTIVITY_WARN_DAYS,
    RAID_JOIN_LIMIT,
    RAID_MODE_MINUTES,
    RAID_WINDOW_SECONDS,
    SPAM_LIMIT_COUNT,
    SPAM_MUTE_MINUTES,
    SPAM_WINDOW_SECONDS,
)
from db import get_setting, set_setting

PARAM_DEFAULTS = {
    "inactivity_notice_days": INACTIVITY_NOTICE_DAYS,
    "inactivity_warn_days": INACTIVITY_WARN_DAYS,
    "spam_limit_count": SPAM_LIMIT_COUNT,
    "spam_window_seconds": SPAM_WINDOW_SECONDS,
    "spam_mute_minutes": SPAM_MUTE_MINUTES,
    "raid_join_limit": RAID_JOIN_LIMIT,
    "raid_window_seconds": RAID_WINDOW_SECONDS,
    "raid_mode_minutes": RAID_MODE_MINUTES,
    "third_warn_mute_minutes": 60 * 24 * 30,
}


def _key(name: str) -> str:
    return f"cfg_{name}"


def get_int_param(name: str) -> int:
    default = PARAM_DEFAULTS[name]
    raw = get_setting(_key(name))
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def set_int_param(name: str, value: int):
    set_setting(_key(name), str(value))


def get_all_params() -> dict[str, int]:
    return {name: get_int_param(name) for name in PARAM_DEFAULTS}
