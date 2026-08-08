import os

from dotenv import load_dotenv

load_dotenv()


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Environment variable '{name}' is required.")
    return value


def _required_int_env(name: str) -> int:
    raw = _required_env(name)
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"Environment variable '{name}' must be integer, got: {raw!r}") from exc


BOT_TOKEN = _required_env("BOT_TOKEN")
OWNER_ID = _required_int_env("OWNER_ID")
GROUP_ID = int(os.getenv("GROUP_ID", "-1001608669127"))

WEB_ENABLED = os.getenv("WEB_ENABLED", "0") == "1"
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", "8443"))
WEB_SSL_CERT = os.getenv("WEB_SSL_CERT", "")
WEB_SSL_KEY = os.getenv("WEB_SSL_KEY", "")
WEB_REQUIRE_HTTPS = os.getenv("WEB_REQUIRE_HTTPS", "1") == "1"
WEB_PUBLIC_URL = os.getenv("WEB_PUBLIC_URL", "")
WEB_PUBLIC_HOST = os.getenv("WEB_PUBLIC_HOST", "")
WEB_OWNER_LOGIN = os.getenv("WEB_OWNER_LOGIN", "owner")
WEB_OWNER_PASSWORD = _required_env("WEB_OWNER_PASSWORD") if WEB_ENABLED else ""
WEB_SESSION_SECRET = os.getenv("WEB_SESSION_SECRET", "")
FLOOD_INFO_CHANNEL_URL = os.getenv("FLOOD_INFO_CHANNEL_URL", "")

WEEKLY_NORM_DEFAULT = int(os.getenv("WEEKLY_NORM", "100"))
INACTIVITY_NOTICE_DAYS = int(os.getenv("INACTIVITY_NOTICE_DAYS", "3"))
INACTIVITY_WARN_DAYS = int(os.getenv("INACTIVITY_WARN_DAYS", "5"))
SPAM_LIMIT_COUNT = int(os.getenv("SPAM_LIMIT_COUNT", "6"))
SPAM_WINDOW_SECONDS = int(os.getenv("SPAM_WINDOW_SECONDS", "10"))
SPAM_MUTE_MINUTES = int(os.getenv("SPAM_MUTE_MINUTES", "10"))
RAID_JOIN_LIMIT = int(os.getenv("RAID_JOIN_LIMIT", "8"))
RAID_WINDOW_SECONDS = int(os.getenv("RAID_WINDOW_SECONDS", "60"))
RAID_MODE_MINUTES = int(os.getenv("RAID_MODE_MINUTES", "10"))
