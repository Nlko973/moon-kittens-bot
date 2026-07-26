import base64
import hashlib
import hmac
import json
import secrets
import ssl
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from aiohttp import web
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile

from app.runtime import bot
from app.services.bot_config import PARAM_DEFAULTS, get_all_params, set_int_param
from app.services.chat_settings import get_group_id, set_group_id
from app.services.duration_parser import parse_deadline, parse_ru_duration_to_minutes
from app.services.moderation import issue_warn, mute_user, unmute_user
from app.services.roles import apply_role_signature, remove_role_signature
from app.services.targets import parse_target
from config import (
    OWNER_ID,
    WEB_HOST,
    WEB_OWNER_LOGIN,
    WEB_OWNER_PASSWORD,
    WEB_PORT,
    WEB_REQUIRE_HTTPS,
    WEB_SSL_CERT,
    WEB_SSL_KEY,
)
from db import (
    add_admin,
    count_users_in_db,
    delete_complaint,
    delete_owner_message,
    get_admins,
    get_all_complaints,
    get_all_owner_messages,
    get_all_rests,
    get_all_warns,
    get_cleanup_candidates,
    get_conn,
    get_users_from_db,
    get_web_user,
    get_web_users,
    get_weekly_norm,
    is_cleanup_enabled,
    is_cleanup_skip_once_enabled,
    is_tg_links_block_enabled,
    purge_user_from_db,
    remove_admin,
    remove_latest_warn_by_user,
    remove_rest,
    remove_warn,
    remove_web_user,
    set_cleanup_enabled,
    set_cleanup_skip_once,
    set_rest_until,
    set_tg_links_block_enabled,
    set_weekly_norm,
    upsert_web_user,
)


ALL_PERMISSIONS = [
    "view",
    "moderation",
    "rests",
    "settings",
    "broadcast",
    "messages",
    "cleanup",
    "users",
    "admins",
    "web_users",
]
PERMISSION_LABELS = {
    "view": "Обзор",
    "moderation": "Модерация",
    "rests": "Ресты",
    "settings": "Конфиги",
    "broadcast": "Публикации",
    "messages": "Сообщения",
    "cleanup": "Чистка",
    "users": "Участники",
    "admins": "Telegram-админы",
    "web_users": "Веб-доступы",
}

OWNER_PERMISSIONS = set(ALL_PERMISSIONS)
SESSIONS: dict[str, dict[str, Any]] = {}


def _hash_password(password: str, salt: Optional[str] = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), 240_000)
    return f"pbkdf2_sha256${salt}${base64.b64encode(digest).decode('ascii')}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, salt, digest = stored.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    expected = _hash_password(password, salt).split("$", 2)[2]
    return hmac.compare_digest(expected, digest)


def _json_permissions(raw: str) -> set[str]:
    try:
        values = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return set()
    return {value for value in values if value in ALL_PERMISSIONS}


def _rows_to_dicts(rows) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _current_user(request: web.Request) -> Optional[dict[str, Any]]:
    token = request.cookies.get("mk_session", "")
    session = SESSIONS.get(token)
    if not session:
        return None
    db_user = get_web_user(session["username"])
    if not db_user:
        SESSIONS.pop(token, None)
        return None
    perms = OWNER_PERMISSIONS if db_user["role"] == "owner" else _json_permissions(db_user["permissions"])
    return {
        "username": db_user["username"],
        "role": db_user["role"],
        "display_name": db_user["display_name"] or db_user["username"],
        "telegram_admin_id": db_user["telegram_admin_id"],
        "permissions": sorted(perms),
    }


def _require(permission: str) -> Callable:
    def decorator(handler: Callable) -> Callable:
        async def wrapped(request: web.Request):
            user = _current_user(request)
            if not user:
                raise web.HTTPUnauthorized(text="Нужна авторизация")
            if user["role"] != "owner" and permission not in user["permissions"]:
                raise web.HTTPForbidden(text="Недостаточно прав")
            request["web_user"] = user
            return await handler(request)

        return wrapped

    return decorator


def _require_any(*permissions: str) -> Callable:
    def decorator(handler: Callable) -> Callable:
        async def wrapped(request: web.Request):
            user = _current_user(request)
            if not user:
                raise web.HTTPUnauthorized(text="Нужна авторизация")
            if user["role"] != "owner" and not any(permission in user["permissions"] for permission in permissions):
                raise web.HTTPForbidden(text="Недостаточно прав")
            request["web_user"] = user
            return await handler(request)

        return wrapped

    return decorator


async def _payload(request: web.Request) -> dict[str, Any]:
    try:
        return await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(text="Некорректный JSON")


def _issued_by(user: dict[str, Any]) -> int:
    if user["role"] == "owner":
        return OWNER_ID
    return int(user.get("telegram_admin_id") or 0)


def _ensure_owner_account():
    upsert_web_user(
        username=WEB_OWNER_LOGIN,
        password_hash=_hash_password(WEB_OWNER_PASSWORD),
        role="owner",
        display_name="Владелец",
        telegram_admin_id=OWNER_ID,
        permissions=json.dumps(sorted(OWNER_PERMISSIONS), ensure_ascii=False),
        active=True,
    )


def _list_mutes() -> list[dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT m.user_id, m.until_at, m.issued_by, m.reason, m.created_at, u.display_name
        FROM mutes m
        LEFT JOIN users u ON u.user_id = m.user_id
        ORDER BY m.until_at ASC
        """
    )
    rows = cur.fetchall()
    conn.close()
    return _rows_to_dicts(rows)


async def login_page(request: web.Request):
    if _current_user(request):
        raise web.HTTPFound("/")
    return web.Response(text=LOGIN_HTML, content_type="text/html")


async def app_page(request: web.Request):
    if not _current_user(request):
        raise web.HTTPFound("/login")
    return web.Response(text=APP_HTML, content_type="text/html")


async def api_login(request: web.Request):
    data = await _payload(request)
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    row = get_web_user(username)
    if not row or not _verify_password(password, row["password_hash"]):
        raise web.HTTPUnauthorized(text="Неверный логин или пароль")
    token = secrets.token_urlsafe(36)
    SESSIONS[token] = {"username": username, "created_at": datetime.now().isoformat(timespec="seconds")}
    response = web.json_response({"ok": True})
    response.set_cookie(
        "mk_session",
        token,
        httponly=True,
        secure=bool(WEB_SSL_CERT and WEB_SSL_KEY),
        samesite="Strict",
        max_age=60 * 60 * 12,
    )
    return response


async def api_logout(request: web.Request):
    token = request.cookies.get("mk_session", "")
    SESSIONS.pop(token, None)
    response = web.json_response({"ok": True})
    response.del_cookie("mk_session")
    return response


@_require("view")
async def api_me(request: web.Request):
    return web.json_response(request["web_user"])


@_require("view")
async def api_state(request: web.Request):
    weekly_norm = get_weekly_norm()
    cleanup_rows = get_cleanup_candidates()
    norm = weekly_norm * 2
    lacking = sum(1 for row in cleanup_rows if int(row["count"] or 0) < norm)
    return web.json_response(
        {
            "summary": {
                "users": count_users_in_db(),
                "active_warns": len(get_all_warns(active_only=True)),
                "rests": len(get_all_rests()),
                "mutes": len(_list_mutes()),
                "complaints": len(get_all_complaints(active_only=True)),
                "owner_messages": len(get_all_owner_messages(active_only=True)),
                "lacking_norm": lacking,
            },
            "config": {
                "owner_id": OWNER_ID,
                "group_id": get_group_id(),
                "weekly_norm": weekly_norm,
                "cleanup_enabled": is_cleanup_enabled(),
                "cleanup_skip_once": is_cleanup_skip_once_enabled(),
                "tg_links_block": is_tg_links_block_enabled(),
                "params": get_all_params(),
            },
            "lists": {
                "warns": _rows_to_dicts(get_all_warns(active_only=True)[:250]),
                "rests": _rows_to_dicts(get_all_rests()[:250]),
                "mutes": _list_mutes()[:250],
                "complaints": _rows_to_dicts(get_all_complaints(active_only=True)[:250]),
                "owner_messages": _rows_to_dicts(get_all_owner_messages(active_only=True)[:250]),
                "cleanup_candidates": _rows_to_dicts(cleanup_rows[:250]),
                "telegram_admins": _rows_to_dicts(get_admins()),
                "users": _rows_to_dicts(get_users_from_db(limit=400)),
                "web_users": [
                    {**dict(row), "permissions": sorted(_json_permissions(row["permissions"]))}
                    for row in get_web_users()
                ],
            },
            "permissions": ALL_PERMISSIONS,
            "permission_labels": PERMISSION_LABELS,
        }
    )


@_require("settings")
async def api_config(request: web.Request):
    data = await _payload(request)
    if "group_id" in data:
        set_group_id(int(data["group_id"]))
    if "weekly_norm" in data:
        weekly_norm = int(data["weekly_norm"])
        if weekly_norm <= 0:
            raise web.HTTPBadRequest(text="Норма должна быть больше 0")
        set_weekly_norm(weekly_norm)
    if "cleanup_enabled" in data:
        set_cleanup_enabled(bool(data["cleanup_enabled"]))
    if data.get("cleanup_skip_once"):
        set_cleanup_skip_once(True)
    if "tg_links_block" in data:
        set_tg_links_block_enabled(bool(data["tg_links_block"]))
    for name, value in (data.get("params") or {}).items():
        if name not in PARAM_DEFAULTS:
            raise web.HTTPBadRequest(text=f"Неизвестный параметр: {name}")
        value = int(value)
        if value <= 0:
            raise web.HTTPBadRequest(text=f"{name} должен быть больше 0")
        set_int_param(name, value)
    return web.json_response({"ok": True})


@_require("admins")
async def api_telegram_admins(request: web.Request):
    data = await _payload(request)
    action = data.get("action")
    user_id = int(data.get("user_id"))
    if action == "add":
        add_admin(user_id, str(data.get("name") or user_id))
    elif action == "remove":
        remove_admin(user_id)
    else:
        raise web.HTTPBadRequest(text="Неизвестное действие")
    return web.json_response({"ok": True})


@_require("web_users")
async def api_web_users(request: web.Request):
    data = await _payload(request)
    action = data.get("action")
    username = str(data.get("username", "")).strip()
    if not username:
        raise web.HTTPBadRequest(text="Нужен логин")
    if action == "delete":
        if username == WEB_OWNER_LOGIN:
            raise web.HTTPBadRequest(text="Владельца нельзя удалить")
        remove_web_user(username)
        return web.json_response({"ok": True})

    password = str(data.get("password", ""))
    if action != "save" or not password:
        raise web.HTTPBadRequest(text="Нужен пароль")
    permissions = [p for p in data.get("permissions", []) if p in ALL_PERMISSIONS]
    telegram_admin_id = data.get("telegram_admin_id")
    upsert_web_user(
        username=username,
        password_hash=_hash_password(password),
        role="admin",
        display_name=str(data.get("display_name") or username),
        telegram_admin_id=int(telegram_admin_id) if telegram_admin_id else None,
        permissions=json.dumps(sorted(set(permissions)), ensure_ascii=False),
    )
    return web.json_response({"ok": True})


@_require("moderation")
async def api_moderation(request: web.Request):
    data = await _payload(request)
    action = data.get("action")
    web_user = request["web_user"]
    user_id = await parse_target(str(data.get("target", "")).strip())
    if action in {"warn", "mute", "unmute", "ban", "unban", "kick", "role_set", "role_remove"} and not user_id:
        raise web.HTTPBadRequest(text="Пользователь не найден")

    if action == "warn":
        expires_at = None
        duration = str(data.get("duration") or "").strip()
        if duration:
            deadline = parse_deadline(duration)
            if not deadline or deadline <= datetime.now():
                raise web.HTTPBadRequest(text="Не удалось распознать срок варна")
            expires_at = deadline.isoformat(timespec="seconds")
        warn_id, total, third, _ = await issue_warn(
            user_id,
            _issued_by(web_user),
            str(data.get("reason") or "Без причины"),
            "manual",
            expires_at=expires_at,
        )
        return web.json_response({"ok": True, "message": f"Варн #{warn_id}. Активных: {total}", "third": third})

    if action == "unwarn":
        raw = str(data.get("warn_id") or data.get("target") or "").strip()
        if raw.isdigit() and remove_warn(int(raw)):
            return web.json_response({"ok": True, "message": "Варн снят"})
        if user_id:
            removed = remove_latest_warn_by_user(user_id)
            if removed:
                return web.json_response({"ok": True, "message": f"Снят варн #{removed}"})
        raise web.HTTPBadRequest(text="Активный варн не найден")

    if action == "mute":
        minutes = parse_ru_duration_to_minutes(str(data.get("duration") or ""))
        if not minutes:
            raise web.HTTPBadRequest(text="Не удалось распознать срок мута")
        message = await mute_user(user_id, int(minutes), _issued_by(web_user), str(data.get("reason") or "Мут из веб-панели"))
        return web.json_response({"ok": True, "message": message})

    if action == "unmute":
        return web.json_response({"ok": True, "message": await unmute_user(user_id)})

    if action == "ban":
        await bot.ban_chat_member(get_group_id(), user_id)
        return web.json_response({"ok": True, "message": "Пользователь забанен"})

    if action == "unban":
        await bot.unban_chat_member(get_group_id(), user_id, only_if_banned=True)
        return web.json_response({"ok": True, "message": "Пользователь разбанен"})

    if action == "kick":
        group_id = get_group_id()
        await bot.ban_chat_member(group_id, user_id)
        await bot.unban_chat_member(group_id, user_id, only_if_banned=True)
        return web.json_response({"ok": True, "message": "Пользователь кикнут"})

    if action == "role_set":
        title = str(data.get("title") or "").strip()
        if not title:
            raise web.HTTPBadRequest(text="Нужно название роли")
        return web.json_response({"ok": True, "message": await apply_role_signature(user_id, title)})

    if action == "role_remove":
        return web.json_response({"ok": True, "message": await remove_role_signature(user_id)})

    raise web.HTTPBadRequest(text="Неизвестное действие")


@_require("rests")
async def api_rests(request: web.Request):
    data = await _payload(request)
    action = data.get("action")
    user = request["web_user"]
    user_id = await parse_target(str(data.get("target", "")).strip())
    if not user_id:
        raise web.HTTPBadRequest(text="Пользователь не найден")
    if action == "save":
        duration = str(data.get("duration") or "").strip().lower()
        expires_at = None
        if duration not in {"", "0", "бессрочно", "навсегда"}:
            deadline = parse_deadline(duration)
            if not deadline or deadline <= datetime.now():
                raise web.HTTPBadRequest(text="Не удалось распознать срок реста")
            expires_at = deadline.isoformat(timespec="seconds")
        set_rest_until(user_id, str(data.get("role_name") or "Рест"), expires_at, _issued_by(user))
    elif action == "remove":
        remove_rest(user_id)
    else:
        raise web.HTTPBadRequest(text="Неизвестное действие")
    return web.json_response({"ok": True})


@_require("broadcast")
async def api_broadcast(request: web.Request):
    multipart = request.content_type.startswith("multipart/")
    data = await request.post() if multipart else await _payload(request)
    kind = str(data.get("kind") or "text")
    text = str(data.get("text") or "").strip()
    upload = data.get("media") if multipart else None
    group_id = get_group_id()
    if kind == "text":
        if not text:
            raise web.HTTPBadRequest(text="Нужен текст")
        await bot.send_message(group_id, text, parse_mode=None)
    elif kind == "photo":
        await bot.send_photo(group_id, photo=_uploaded_media(upload), caption=text or None, parse_mode=None)
    elif kind == "gif":
        await bot.send_animation(group_id, animation=_uploaded_media(upload), caption=text or None, parse_mode=None)
    elif kind == "video":
        await bot.send_video(group_id, video=_uploaded_media(upload), caption=text or None, parse_mode=None)
    else:
        raise web.HTTPBadRequest(text="Неизвестный тип публикации")
    return web.json_response({"ok": True, "message": "Публикация отправлена"})


def _uploaded_media(upload: Any) -> BufferedInputFile:
    if not upload or not getattr(upload, "file", None):
        raise web.HTTPBadRequest(text="Выберите файл для публикации")
    content = upload.file.read()
    if not content:
        raise web.HTTPBadRequest(text="Файл пустой")
    filename = getattr(upload, "filename", None) or "media"
    return BufferedInputFile(content, filename=filename)


@_require_any("users", "messages")
async def api_users(request: web.Request):
    data = await _payload(request)
    action = data.get("action")
    if action == "delete":
        web_user = request["web_user"]
        if web_user["role"] != "owner" and "users" not in web_user["permissions"]:
            raise web.HTTPForbidden(text="Недостаточно прав")
        purge_user_from_db(int(data.get("user_id")))
    elif action == "delete_complaint":
        delete_complaint(int(data.get("id")))
    elif action == "delete_owner_message":
        delete_owner_message(int(data.get("id")))
    else:
        raise web.HTTPBadRequest(text="Неизвестное действие")
    return web.json_response({"ok": True})


@web.middleware
async def api_error_middleware(request, handler):
    try:
        return await handler(request)
    except web.HTTPException as exc:
        if request.path.startswith("/api/"):
            return web.json_response({"ok": False, "error": exc.text or exc.reason}, status=exc.status)
        raise
    except TelegramBadRequest as exc:
        return web.json_response({"ok": False, "error": exc.message}, status=400)
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


def create_web_app() -> web.Application:
    _ensure_owner_account()
    app = web.Application(middlewares=[api_error_middleware])
    app.router.add_get("/", app_page)
    app.router.add_get("/login", login_page)
    app.router.add_post("/api/login", api_login)
    app.router.add_post("/api/logout", api_logout)
    app.router.add_get("/api/me", api_me)
    app.router.add_get("/api/state", api_state)
    app.router.add_post("/api/config", api_config)
    app.router.add_post("/api/telegram-admins", api_telegram_admins)
    app.router.add_post("/api/web-users", api_web_users)
    app.router.add_post("/api/moderation", api_moderation)
    app.router.add_post("/api/rests", api_rests)
    app.router.add_post("/api/broadcast", api_broadcast)
    app.router.add_post("/api/users", api_users)
    return app


async def start_web_app() -> web.AppRunner:
    app = create_web_app()
    runner = web.AppRunner(app)
    await runner.setup()

    ssl_context = None
    if WEB_SSL_CERT and WEB_SSL_KEY:
        cert = Path(WEB_SSL_CERT)
        key = Path(WEB_SSL_KEY)
        if not cert.exists() or not key.exists():
            raise RuntimeError(f"WEB_SSL_CERT или WEB_SSL_KEY не найдены: {cert}, {key}")
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.load_cert_chain(str(cert), str(key))
    elif WEB_REQUIRE_HTTPS:
        raise RuntimeError("Для веб-панели нужен HTTPS: задайте WEB_SSL_CERT и WEB_SSL_KEY или WEB_REQUIRE_HTTPS=0.")

    site = web.TCPSite(runner, WEB_HOST, WEB_PORT, ssl_context=ssl_context)
    await site.start()
    scheme = "https" if ssl_context else "http"
    print(f"Web panel: {scheme}://{WEB_HOST}:{WEB_PORT}")
    return runner


LOGIN_HTML = """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Moon Kittens Bot</title>
  <link rel="icon" href="https://cdn-icons-png.flaticon.com/512/16222/16222075.png">
  <style>
    :root { color-scheme: dark; --bg:#101318; --panel:#1a2029; --line:#303947; --text:#f5f7fa; --muted:#aab4c2; --accent:#f3b35d; --cyan:#7ed8cf; --danger:#ff6b76; }
    * { box-sizing:border-box; }
    body { margin:0; min-height:100vh; display:grid; place-items:center; font-family:Inter,Segoe UI,Arial,sans-serif; background:radial-gradient(circle at 20% 0%, #263643 0, transparent 34%), linear-gradient(135deg,#101318,#182020 55%,#251f1a); color:var(--text); }
    .login { width:min(420px, calc(100vw - 32px)); background:rgba(26,32,41,.94); border:1px solid var(--line); border-radius:8px; padding:28px; box-shadow:0 24px 80px rgba(0,0,0,.38); }
    h1 { margin:0 0 8px; font-size:28px; letter-spacing:0; }
    p { margin:0 0 22px; color:var(--muted); line-height:1.5; }
    label { display:block; margin:14px 0 7px; color:#d9e0ea; font-size:14px; }
    input { width:100%; min-height:44px; border:1px solid var(--line); border-radius:8px; background:#111720; color:var(--text); padding:0 12px; font-size:16px; }
    button { width:100%; min-height:44px; margin-top:18px; border:0; border-radius:8px; background:var(--accent); color:#201406; font-weight:800; cursor:pointer; }
    .error { min-height:22px; margin-top:14px; color:var(--danger); }
  </style>
</head>
<body>
  <form class="login" id="loginForm">
    <h1>Moon Kittens Bot</h1>
    <p>Панель управления ботом. Войдите под аккаунтом владельца или администратора.</p>
    <label for="username">Логин</label>
    <input id="username" autocomplete="username" required>
    <label for="password">Пароль</label>
    <input id="password" type="password" autocomplete="current-password" required>
    <button>Войти</button>
    <div class="error" id="error"></div>
  </form>
  <script>
    loginForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      error.textContent = '';
      const res = await fetch('/api/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({username:username.value, password:password.value})});
      if (res.ok) location.href = '/';
      else error.textContent = 'Неверный логин или пароль';
    });
  </script>
</body>
</html>
"""


APP_HTML = """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Moon Kittens Bot Panel</title>
  <link rel="icon" href="https://cdn-icons-png.flaticon.com/512/16222/16222075.png">
  <style>
    :root { --bg:#101318; --side:#171c24; --panel:#1e2630; --panel2:#26313d; --line:#33404f; --text:#f5f7fa; --muted:#a9b4c3; --accent:#f3b35d; --cyan:#7ed8cf; --danger:#ff6b76; --ok:#93d37c; }
    * { box-sizing:border-box; }
    body { margin:0; min-height:100vh; font-family:Inter,Segoe UI,Arial,sans-serif; background:var(--bg); color:var(--text); }
    .shell { display:grid; grid-template-columns:260px 1fr; min-height:100vh; }
    aside { background:var(--side); border-right:1px solid var(--line); padding:20px; position:sticky; top:0; height:100vh; }
    .brand { display:flex; gap:10px; align-items:center; font-size:22px; font-weight:850; margin-bottom:4px; }
    .brand img { width:34px; height:34px; border-radius:8px; }
    .who { color:var(--muted); font-size:13px; margin-bottom:22px; overflow-wrap:anywhere; }
    nav button, .ghost { width:100%; min-height:38px; border:1px solid transparent; background:transparent; color:var(--muted); text-align:left; padding:0 10px; border-radius:8px; cursor:pointer; font-weight:700; }
    nav button.active, nav button:hover, .ghost:hover { background:var(--panel); color:var(--text); border-color:var(--line); }
    main { padding:24px; max-width:1440px; width:100%; }
    header { display:flex; justify-content:space-between; gap:16px; align-items:center; margin-bottom:20px; }
    h1 { margin:0; font-size:26px; letter-spacing:0; }
    h3 { margin:0 0 12px; font-size:17px; letter-spacing:0; }
    .grid { display:grid; gap:14px; }
    .stats { grid-template-columns:repeat(6, minmax(120px,1fr)); }
    .card { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; min-width:0; margin-bottom:14px; }
    .stat b { display:block; font-size:26px; margin-top:6px; }
    .muted { color:var(--muted); }
    .section { display:none; }
    .section.active { display:block; }
    .two { grid-template-columns:repeat(2,minmax(0,1fr)); }
    .three { grid-template-columns:repeat(3,minmax(0,1fr)); }
    label { display:block; color:#dce3ec; font-size:13px; margin:10px 0 6px; }
    input, textarea, select { width:100%; min-height:38px; border:1px solid var(--line); border-radius:8px; background:#121820; color:var(--text); padding:8px 10px; font-size:14px; }
    textarea { min-height:96px; resize:vertical; }
    button { min-height:38px; border:0; border-radius:8px; background:var(--accent); color:#211608; padding:0 12px; font-weight:800; cursor:pointer; white-space:nowrap; }
    button.secondary { background:var(--panel2); color:var(--text); border:1px solid var(--line); }
    button.danger { background:var(--danger); color:#270b0e; }
    .row { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
    .toolbar input { max-width:280px; }
    table { width:100%; border-collapse:collapse; table-layout:fixed; }
    th, td { padding:10px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; overflow-wrap:anywhere; }
    th { color:var(--muted); font-size:12px; text-transform:uppercase; }
    .perm-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:6px 12px; margin:10px 0; }
    .check { display:flex; gap:8px; align-items:center; margin:0; }
    .check input { width:auto; min-height:auto; }
    .pill { display:inline-flex; align-items:center; min-height:24px; border-radius:8px; padding:0 8px; background:#151b23; border:1px solid var(--line); color:var(--muted); margin:2px; font-size:12px; }
    .toast { position:fixed; right:18px; bottom:18px; max-width:min(420px,calc(100vw - 36px)); background:#111720; border:1px solid var(--line); border-radius:8px; padding:12px 14px; box-shadow:0 16px 60px rgba(0,0,0,.4); display:none; }
    @media (max-width:900px) { .shell { grid-template-columns:1fr; } aside { position:relative; height:auto; } .stats,.two,.three,.perm-grid { grid-template-columns:1fr; } header { align-items:flex-start; flex-direction:column; } }
  </style>
</head>
<body>
<div class="shell">
  <aside>
    <div class="brand"><img src="https://cdn-icons-png.flaticon.com/512/16222/16222075.png" alt="">Moon Kittens</div>
    <div class="who" id="who">Панель бота</div>
    <nav id="nav"></nav>
    <button class="ghost" onclick="logout()">Выйти</button>
  </aside>
  <main>
    <header><h1 id="title">Обзор</h1><button class="secondary" onclick="loadState()">Обновить</button></header>
    <section id="dashboard" class="section active"></section>
    <section id="moderation" class="section"></section>
    <section id="rests" class="section"></section>
    <section id="settings" class="section"></section>
    <section id="broadcast" class="section"></section>
    <section id="messages" class="section"></section>
    <section id="cleanup" class="section"></section>
    <section id="users" class="section"></section>
    <section id="admins" class="section"></section>
  </main>
</div>
<div class="toast" id="toast"></div>
<script>
const sections = [
  ['dashboard','Обзор','view'], ['moderation','Модерация','moderation'], ['rests','Ресты','rests'],
  ['settings','Конфиги','settings'], ['broadcast','Публикации','broadcast'], ['messages','Сообщения','messages'],
  ['cleanup','Чистка','cleanup'], ['users','Участники','users'], ['admins','Доступы','admins']
];
let me = null, state = null;
const can = (p) => me && (me.role === 'owner' || me.permissions.includes(p));
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[s]));
const toastMsg = (text) => { toast.textContent = text; toast.style.display = 'block'; setTimeout(() => toast.style.display = 'none', 4200); };
async function api(url, options={}) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) location.href = '/login';
  if (!res.ok || data.ok === false) throw new Error(data.error || res.statusText);
  return data;
}
async function post(url, body) { return api(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)}); }
async function init() {
  me = await api('/api/me');
  who.textContent = `${me.display_name} · ${me.role}`;
  nav.innerHTML = sections.filter(s => can(s[2])).map((s,i) => `<button class="${i===0?'active':''}" onclick="show('${s[0]}')">${s[1]}</button>`).join('');
  await loadState();
}
function show(id) {
  document.querySelectorAll('.section').forEach(el => el.classList.toggle('active', el.id === id));
  document.querySelectorAll('nav button').forEach(btn => btn.classList.toggle('active', btn.textContent === sections.find(s => s[0] === id)[1]));
  title.textContent = sections.find(s => s[0] === id)[1];
}
async function loadState() { state = await api('/api/state'); renderAll(); }
function renderAll() { renderDashboard(); renderModeration(); renderRests(); renderSettings(); renderBroadcast(); renderMessages(); renderCleanup(); renderUsers(); renderAdmins(); }
function stat(label, value) { return `<div class="card stat"><span class="muted">${label}</span><b>${esc(value)}</b></div>`; }
function tableCard(name, rows, cols) {
  const cell = (row, col) => col === 'action' ? (row[col] || '') : esc(row[col]);
  return `<div class="card"><h3>${esc(name)}</h3><table><thead><tr>${cols.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${rows.slice(0,60).map(r=>`<tr>${cols.map(c=>`<td>${cell(r,c)}</td>`).join('')}</tr>`).join('') || `<tr><td colspan="${cols.length}" class="muted">Пусто</td></tr>`}</tbody></table></div>`;
}
function renderDashboard() {
  const s = state.summary;
  dashboard.innerHTML = `<div class="grid stats">${stat('Участники',s.users)}${stat('Варны',s.active_warns)}${stat('Ресты',s.rests)}${stat('Муты',s.mutes)}${stat('Жалобы',s.complaints)}${stat('Без нормы',s.lacking_norm)}</div>
  <div class="grid two">${tableCard('Активные варны', state.lists.warns, ['id','user_id','display_name','reason','expires_at'])}${tableCard('Жалобы', state.lists.complaints, ['id','user_id','display_name','text','created_at'])}</div>`;
}
function renderModeration() {
  if (!can('moderation')) return;
  moderation.innerHTML = `<div class="grid three">
    ${modForm('Выдать варн','warnForm',[['target','ID или @username'],['duration','Срок: месяц, 7 дней, 2026-08-01'],['reason','Причина']],'warn')}
    ${modForm('Мут','muteForm',[['target','ID или @username'],['duration','Срок: 30 минут, 2 часа'],['reason','Причина']],'mute')}
    ${modForm('Роль','roleForm',[['target','ID или @username'],['title','Название роли']],'role_set')}
  </div>
  <div class="card"><h3>Быстрые действия</h3><div class="row toolbar">
    <input id="quickTarget" placeholder="ID или @username"><input id="quickWarn" placeholder="warn_id">
    <button onclick="quick('unwarn')">Снять варн</button><button onclick="quick('unmute')">Размут</button><button onclick="quick('ban')">Бан</button><button onclick="quick('unban')">Разбан</button><button onclick="quick('kick')">Кик</button><button onclick="quick('role_remove')">Снять роль</button>
  </div></div>${tableCard('Муты', state.lists.mutes, ['user_id','display_name','until_at','reason','issued_by'])}`;
}
function modForm(title, id, fields, action) {
  return `<form class="card" id="${id}" onsubmit="submitModeration(event,'${action}',this)"><h3>${title}</h3>${fields.map(f=>`<label>${f[1]}</label><input name="${f[0]}">`).join('')}<button>Выполнить</button></form>`;
}
async function submitModeration(event, action, form) {
  event.preventDefault();
  const body = Object.fromEntries(new FormData(form).entries());
  body.action = action;
  const data = await post('/api/moderation', body);
  toastMsg(data.message || 'Готово'); await loadState();
}
async function quick(action) {
  const data = await post('/api/moderation', {action, target: quickTarget.value, warn_id: quickWarn.value});
  toastMsg(data.message || 'Готово'); await loadState();
}
function renderRests() {
  if (!can('rests')) return;
  const rows = state.lists.rests.map(r => ({...r, action:`<button class="danger" onclick="removeRest('${esc(r.user_id)}')">Снять</button>`}));
  rests.innerHTML = `<form class="card" onsubmit="saveRest(event,this)"><h3>Выдать или обновить рест</h3><div class="grid three"><div><label>Пользователь</label><input name="target"></div><div><label>Срок</label><input name="duration" placeholder="0, месяц, 2026-08-01"></div><div><label>Роль</label><input name="role_name"></div></div><button>Сохранить</button></form>${tableCard('Активные ресты', rows, ['user_id','display_name','role_name','expires_at','action'])}`;
}
async function saveRest(event, form) { event.preventDefault(); await post('/api/rests', {...Object.fromEntries(new FormData(form).entries()), action:'save'}); toastMsg('Рест сохранён'); await loadState(); }
async function removeRest(userId) { await post('/api/rests', {action:'remove', target:userId}); toastMsg('Рест снят'); await loadState(); }
function renderSettings() {
  if (!can('settings')) return;
  const c = state.config, params = c.params;
  settings.innerHTML = `<form class="card" onsubmit="saveConfig(event,this)"><h3>Основные настройки</h3>
    <div class="grid three"><div><label>GROUP_ID</label><input name="group_id" value="${esc(c.group_id)}"></div><div><label>WEEKLY_NORM</label><input name="weekly_norm" value="${esc(c.weekly_norm)}"></div><div><label>TG-ссылки</label><select name="tg_links_block"><option value="0">Разрешены</option><option value="1" ${c.tg_links_block?'selected':''}>Запрещены</option></select></div></div>
    <div class="grid three">${Object.entries(params).map(([k,v])=>`<div><label>${esc(k)}</label><input name="param_${esc(k)}" value="${esc(v)}"></div>`).join('')}</div>
    <div class="row" style="margin-top:12px"><label class="check"><input type="checkbox" name="cleanup_enabled" ${c.cleanup_enabled?'checked':''}> Авточистка</label><label class="check"><input type="checkbox" name="cleanup_skip_once"> Пропустить ближайшую чистку</label></div><button>Сохранить</button></form>`;
}
async function saveConfig(event, form) {
  event.preventDefault();
  const fd = new FormData(form), params = {};
  for (const [k,v] of fd.entries()) if (k.startsWith('param_')) params[k.slice(6)] = v;
  await post('/api/config', {group_id:fd.get('group_id'), weekly_norm:fd.get('weekly_norm'), tg_links_block:fd.get('tg_links_block') === '1', cleanup_enabled:fd.has('cleanup_enabled'), cleanup_skip_once:fd.has('cleanup_skip_once'), params});
  toastMsg('Конфиг сохранён'); await loadState();
}
function renderBroadcast() {
  if (!can('broadcast')) return;
  broadcast.innerHTML = `<form class="card" onsubmit="sendBroadcast(event,this)"><h3>Публикация в группу</h3><div class="grid three"><div><label>Тип</label><select name="kind" onchange="toggleMediaInput(this.form)"><option value="text">Текст</option><option value="photo">Фото</option><option value="gif">GIF</option><option value="video">Видео</option></select></div><div><label>Файл на устройстве</label><input name="media" type="file" accept="image/*,video/*,.gif"></div></div><label>Текст или подпись</label><textarea name="text"></textarea><button>Отправить</button></form>`;
  toggleMediaInput(broadcast.querySelector('form'));
}
function toggleMediaInput(form) {
  const media = form.elements.media;
  media.disabled = form.elements.kind.value === 'text';
  media.required = !media.disabled;
}
async function sendBroadcast(event, form) {
  event.preventDefault();
  const data = await api('/api/broadcast', {method:'POST', body:new FormData(form)});
  toastMsg(data.message);
  form.reset();
  toggleMediaInput(form);
}
function renderUsers() {
  if (!can('users')) return;
  const dbUsers = state.lists.users.map(r => ({...r, action:`<button class="danger" onclick="deleteDbUser('${esc(r.user_id)}')">Удалить</button>`}));
  const complaints = state.lists.complaints.map(r => ({...r, action:`<button class="danger" onclick="deleteComplaint('${esc(r.id)}')">Закрыть</button>`}));
  const ownerMsgs = state.lists.owner_messages.map(r => ({...r, action:`<button class="danger" onclick="deleteOwnerMsg('${esc(r.id)}')">Закрыть</button>`}));
  users.innerHTML = `${tableCard('Участники в БД', dbUsers, ['user_id','display_name','is_member','first_seen_at','last_message_at','action'])}${tableCard('Жалобы', complaints, ['id','user_id','display_name','text','created_at','action'])}${tableCard('Сообщения владельцу', ownerMsgs, ['id','user_id','display_name','text','created_at','action'])}`;
}
async function deleteDbUser(userId) { await post('/api/users', {action:'delete', user_id:userId}); toastMsg('Пользователь удалён из БД'); await loadState(); }
async function deleteComplaint(id) { await post('/api/users', {action:'delete_complaint', id}); toastMsg('Жалоба закрыта'); await loadState(); }
async function deleteOwnerMsg(id) { await post('/api/users', {action:'delete_owner_message', id}); toastMsg('Сообщение закрыто'); await loadState(); }
function renderMessages() {
  if (!can('messages')) return;
  const complaints = state.lists.complaints.map(r => ({...r, action:`<button class="danger" onclick="deleteComplaint('${esc(r.id)}')">Закрыть</button>`}));
  const ownerMsgs = state.lists.owner_messages.map(r => ({...r, action:`<button class="danger" onclick="deleteOwnerMsg('${esc(r.id)}')">Закрыть</button>`}));
  messages.innerHTML = `<div class="grid two">${tableCard('Жалобы', complaints, ['id','user_id','display_name','text','created_at','action'])}${tableCard('Сообщения влд', ownerMsgs, ['id','user_id','display_name','text','created_at','action'])}</div>`;
}
function renderCleanup() {
  if (!can('cleanup')) return;
  const c = state.config;
  const rows = (state.lists.cleanup_candidates || []).map(r => ({...r, status:Number(r.count || 0) >= Number(c.weekly_norm || 0) * 2 ? 'ok' : 'ниже нормы'}));
  cleanup.innerHTML = `<form class="card" onsubmit="saveCleanup(event,this)"><h3>Чистка</h3><div class="row"><label class="check"><input type="checkbox" name="cleanup_enabled" ${c.cleanup_enabled?'checked':''}> Авточистка включена</label><label class="check"><input type="checkbox" name="cleanup_skip_once"> Пропустить ближайшую чистку</label><button>Сохранить</button></div></form>${tableCard('Кандидаты по норме', rows, ['user_id','display_name','first_seen_at','count','status'])}`;
}
async function saveCleanup(event, form) {
  event.preventDefault();
  const fd = new FormData(form);
  await post('/api/config', {cleanup_enabled:fd.has('cleanup_enabled'), cleanup_skip_once:fd.has('cleanup_skip_once')});
  toastMsg('Настройки чистки сохранены');
  await loadState();
}
function renderAdmins() {
  if (!can('admins')) return;
  const labels = state.permission_labels;
  const perms = state.permissions.map(p => `<label class="check"><input type="checkbox" name="permissions" value="${p}"> ${esc(labels[p] || p)}</label>`).join('');
  const tgAdmins = state.lists.telegram_admins.map(r => ({...r, action:`<button class="danger" onclick="removeTgAdmin('${esc(r.user_id)}')">Удалить</button>`}));
  const webUsers = state.lists.web_users.map(r => ({...r, permissions:(r.permissions || []).map(p => labels[p] || p).join(', '), action:r.role === 'owner' ? '' : `<button class="danger" onclick="removeWebUser('${esc(r.username)}')">Удалить</button>`}));
  admins.innerHTML = `<div class="grid two"><form class="card" onsubmit="saveTgAdmin(event,this)"><h3>Telegram-админ</h3><label>User ID</label><input name="user_id"><label>Имя</label><input name="name"><button>Добавить</button></form>
  <form class="card" onsubmit="saveWebUser(event,this)"><h3>Веб-доступ администратора</h3><label>Логин</label><input name="username"><label>Пароль</label><input name="password" type="password"><label>Имя</label><input name="display_name"><label>Telegram admin ID</label><input name="telegram_admin_id"><div class="perm-grid">${perms}</div><button>Сохранить</button></form></div>
  <div class="grid two">${tableCard('Telegram-админы', tgAdmins, ['user_id','name','action'])}${tableCard('Веб-пользователи', webUsers, ['username','role','display_name','telegram_admin_id','permissions','action'])}</div>`;
}
async function saveTgAdmin(event, form) { event.preventDefault(); await post('/api/telegram-admins', {...Object.fromEntries(new FormData(form).entries()), action:'add'}); toastMsg('Админ добавлен'); await loadState(); }
async function saveWebUser(event, form) { event.preventDefault(); const fd = new FormData(form); await post('/api/web-users', {action:'save', username:fd.get('username'), password:fd.get('password'), display_name:fd.get('display_name'), telegram_admin_id:fd.get('telegram_admin_id'), permissions:fd.getAll('permissions')}); toastMsg('Веб-доступ сохранён'); await loadState(); }
async function removeTgAdmin(userId) { await post('/api/telegram-admins', {action:'remove', user_id:userId}); toastMsg('Telegram-админ удалён'); await loadState(); }
async function removeWebUser(username) { await post('/api/web-users', {action:'delete', username}); toastMsg('Веб-доступ удалён'); await loadState(); }
async function logout() { await post('/api/logout', {}); location.href = '/login'; }
init().catch(err => toastMsg(err.message));
</script>
</body>
</html>
"""
