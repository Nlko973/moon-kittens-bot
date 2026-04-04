from datetime import datetime
from typing import Any, Dict, Optional

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from app.runtime import bot
from app.keyboards import (
    BTN_ADM_ADD_ADMIN,
    BTN_ADM_COMPLAINT_DEL,
    BTN_ADM_DB_USER_DEL,
    BTN_ADM_DEL_ADMIN,
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
)
from app.services.access import require_owner, require_private_admin
from app.services.bot_config import PARAM_DEFAULTS
from app.services.chat_settings import get_group_id
from app.services.duration_parser import parse_deadline, parse_ru_duration_to_minutes
from app.services.moderation import issue_warn, mute_user, unmute_user
from app.services.targets import parse_target
from app.texts import USER_NOT_FOUND
from db import add_admin, delete_complaint, extend_rest, purge_user_from_db, remove_admin, remove_latest_warn_by_user, remove_rest, remove_warn, set_rest_until

router = Router()

CANCEL_WORDS = {"стоп", "отмена", "cancel", "stop"}
DIALOGS: Dict[int, Dict[str, Any]] = {}


def _start_dialog(user_id: int, command: str):
    DIALOGS[user_id] = {"command": command, "step": 0, "data": {}}


def _stop_dialog(user_id: int):
    DIALOGS.pop(user_id, None)


async def _start_admin_dialog(message: Message, command: str, owner_only: bool = False) -> bool:
    allowed = await require_owner(message) if owner_only else await require_private_admin(message)
    if not allowed:
        return False

    _start_dialog(message.from_user.id, command)
    prompts = {
        "warn": "Команда: выдать варн.\nУкажите пользователя (id или @username).\nДля отмены: стоп/отмена.",
        "unwarn": "Команда: снять варн.\nУкажите warn_id или пользователя (id/@username).\nДля отмены: стоп/отмена.",
        "rest_add": "Команда: выдать рест.\nУкажите пользователя (id или @username).\nДля отмены: стоп/отмена.",
        "rest_del": "Команда: снять рест.\nУкажите пользователя (id или @username).\nДля отмены: стоп/отмена.",
        "rest_extend": "Команда: продлить рест.\nУкажите пользователя (id или @username).\nДля отмены: стоп/отмена.",
        "mute": "Команда: выдать мут.\nУкажите пользователя (id или @username).\nДля отмены: стоп/отмена.",
        "unmute": "Команда: снять мут.\nУкажите пользователя (id или @username).\nДля отмены: стоп/отмена.",
        "ban": "Команда: бан.\nУкажите пользователя (id или @username).\nДля отмены: стоп/отмена.",
        "unban": "Команда: разбан.\nУкажите пользователя (id или @username).\nДля отмены: стоп/отмена.",
        "kick": "Команда: кик.\nУкажите пользователя (id или @username).\nДля отмены: стоп/отмена.",
        "add_admin": "Команда: добавить админа.\nУкажите пользователя (id или @username).\nДля отмены: стоп/отмена.",
        "del_admin": "Команда: удалить админа.\nУкажите пользователя (id или @username).\nДля отмены: стоп/отмена.",
        "del_complaint": "Команда: удалить жалобу.\nУкажите номер жалобы (ID).\nДля отмены: стоп/отмена.",
        "db_user_del": "Команда: удалить участника из БД.\nУкажите user_id.\nДля отмены: стоп/отмена.",
        "say_any": (
            "Команда: написать в чат.\n"
            "Отправьте следующим сообщением текст, фото, видео, GIF, документ, аудио, голосовое, стикер.\n"
            "Подпись/текст будут сохранены.\nДля отмены: стоп/отмена."
        ),
    }
    await message.answer(prompts.get(command, "Введите данные. Для отмены: стоп/отмена."))
    return True


@router.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^/warn(?:@\w+)?\s*$"))
async def dialog_warn_start(message: Message):
    await _start_admin_dialog(message, "warn")


@router.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^/rest_add(?:@\w+)?\s*$"))
async def dialog_rest_add_start(message: Message):
    await _start_admin_dialog(message, "rest_add")


@router.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^/rest_extend(?:@\w+)?\s*$"))
async def dialog_rest_extend_start(message: Message):
    await _start_admin_dialog(message, "rest_extend")


@router.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^/rest_del(?:@\w+)?\s*$"))
async def dialog_rest_del_start(message: Message):
    await _start_admin_dialog(message, "rest_del")


@router.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^/mute(?:@\w+)?\s*$"))
async def dialog_mute_start(message: Message):
    await _start_admin_dialog(message, "mute")


@router.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^/unmute(?:@\w+)?\s*$"))
async def dialog_unmute_start(message: Message):
    await _start_admin_dialog(message, "unmute")


@router.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^/ban(?:@\w+)?\s*$"))
async def dialog_ban_start(message: Message):
    await _start_admin_dialog(message, "ban")


@router.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^/kick(?:@\w+)?\s*$"))
async def dialog_kick_start(message: Message):
    await _start_admin_dialog(message, "kick")


@router.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^/unban(?:@\w+)?\s*$"))
async def dialog_unban_start(message: Message):
    await _start_admin_dialog(message, "unban")


@router.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^/unwarn(?:@\w+)?\s*$"))
async def dialog_unwarn_start(message: Message):
    await _start_admin_dialog(message, "unwarn")


@router.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^/add_admin(?:@\w+)?\s*$"))
async def dialog_add_admin_start(message: Message):
    await _start_admin_dialog(message, "add_admin", owner_only=True)


@router.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^/del_admin(?:@\w+)?\s*$"))
async def dialog_del_admin_start(message: Message):
    await _start_admin_dialog(message, "del_admin", owner_only=True)


@router.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^/del_complaint(?:@\w+)?\s*$"))
async def dialog_del_complaint_start(message: Message):
    await _start_admin_dialog(message, "del_complaint", owner_only=True)


@router.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^/db_user_del(?:@\w+)?\s*$"))
async def dialog_db_user_del_start(message: Message):
    await _start_admin_dialog(message, "db_user_del", owner_only=True)


@router.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^/say(?:@\w+)?\s*$"))
async def dialog_say_start(message: Message):
    await _start_admin_dialog(message, "say_any", owner_only=True)


@router.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^/say_photo(?:@\w+)?\s*$"))
async def dialog_say_photo_start(message: Message):
    await _start_admin_dialog(message, "say_any", owner_only=True)


@router.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^/say_gif(?:@\w+)?\s*$"))
async def dialog_say_gif_start(message: Message):
    await _start_admin_dialog(message, "say_any", owner_only=True)


@router.message(F.chat.type == ChatType.PRIVATE, F.text.regexp(r"(?i)^/say_video(?:@\w+)?\s*$"))
async def dialog_say_video_start(message: Message):
    await _start_admin_dialog(message, "say_any", owner_only=True)


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_PROMPT_WARN)
async def btn_dialog_warn_start(message: Message):
    await _start_admin_dialog(message, "warn")


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_PROMPT_UNWARN)
async def btn_dialog_unwarn_start(message: Message):
    await _start_admin_dialog(message, "unwarn")


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_PROMPT_REST)
async def btn_dialog_rest_start(message: Message):
    await _start_admin_dialog(message, "rest_add")


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_PROMPT_UNREST)
async def btn_dialog_unrest_start(message: Message):
    await _start_admin_dialog(message, "rest_del")


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_PROMPT_MUTE)
async def btn_dialog_mute_start(message: Message):
    await _start_admin_dialog(message, "mute")


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_PROMPT_UNMUTE)
async def btn_dialog_unmute_start(message: Message):
    await _start_admin_dialog(message, "unmute")


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_PROMPT_BAN)
async def btn_dialog_ban_start(message: Message):
    await _start_admin_dialog(message, "ban")


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_PROMPT_UNBAN)
async def btn_dialog_unban_start(message: Message):
    await _start_admin_dialog(message, "unban")


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_PROMPT_KICK)
async def btn_dialog_kick_start(message: Message):
    await _start_admin_dialog(message, "kick")


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_PROMPT_SAY)
async def btn_dialog_say_start(message: Message):
    await _start_admin_dialog(message, "say_any", owner_only=True)


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_ADD_ADMIN)
async def btn_dialog_add_admin_start(message: Message):
    await _start_admin_dialog(message, "add_admin", owner_only=True)


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_DEL_ADMIN)
async def btn_dialog_del_admin_start(message: Message):
    await _start_admin_dialog(message, "del_admin", owner_only=True)


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_COMPLAINT_DEL)
async def btn_dialog_del_complaint_start(message: Message):
    await _start_admin_dialog(message, "del_complaint", owner_only=True)


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_DB_USER_DEL)
async def btn_dialog_db_user_del_start(message: Message):
    await _start_admin_dialog(message, "db_user_del", owner_only=True)


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_ADM_PROMPT_SET_PARAM)
@router.message(F.chat.type == ChatType.PRIVATE, F.text == "\u041f\u0430\u0440\u0430\u043c\u0435\u0442\u0440")
async def btn_prompt_set_param(message: Message):
    if not await require_owner(message):
        return
    _stop_dialog(message.from_user.id)
    names = ", ".join(PARAM_DEFAULTS.keys())
    await message.answer(f"??????: /set_param <name> <value>\n????????? name: {names}")


@router.message(
    F.chat.type == ChatType.PRIVATE,
    F.from_user.is_not(None),
    F.text,
    F.from_user.func(lambda u: u and u.id in DIALOGS),
)
async def dialog_input(message: Message):
    state = DIALOGS.get(message.from_user.id)
    if not state:
        return
    if not await require_private_admin(message):
        _stop_dialog(message.from_user.id)
        return

    text = (message.text or "").strip()
    if text.lower() in CANCEL_WORDS:
        _stop_dialog(message.from_user.id)
        await message.answer("Команда отменена.")
        return

    command = state["command"]
    step = state["step"]
    data = state["data"]

    if command == "warn":
        await _handle_warn_dialog(message, step, data, text)
    elif command == "rest_add":
        await _handle_rest_add_dialog(message, step, data, text)
    elif command == "rest_extend":
        await _handle_rest_extend_dialog(message, step, data, text)
    elif command == "rest_del":
        await _handle_rest_del_dialog(message, step, text)
    elif command == "mute":
        await _handle_mute_dialog(message, step, data, text)
    elif command == "unmute":
        await _handle_unmute_dialog(message, step, text)
    elif command == "ban":
        await _handle_ban_dialog(message, step, data, text)
    elif command == "kick":
        await _handle_kick_dialog(message, step, data, text)
    elif command == "unban":
        await _handle_unban_dialog(message, step, text)
    elif command == "unwarn":
        await _handle_unwarn_dialog(message, step, text)
    elif command == "add_admin":
        await _handle_add_admin_dialog(message, step, data, text)
    elif command == "del_admin":
        await _handle_del_admin_dialog(message, step, text)
    elif command == "del_complaint":
        await _handle_del_complaint_dialog(message, step, text)
    elif command == "db_user_del":
        await _handle_db_user_del_dialog(message, step, text)
    elif command == "say":
        await _handle_say_dialog(message, step, text)
    elif command == "say_any":
        await _handle_say_any_dialog(message, step, text)
    elif command == "say_photo":
        await message.answer("Ожидаю фото следующим сообщением. Для отмены: стоп/отмена.")
    elif command == "say_gif":
        await message.answer("Ожидаю GIF следующим сообщением. Для отмены: стоп/отмена.")
    elif command == "say_video":
        await message.answer("Ожидаю видео следующим сообщением. Для отмены: стоп/отмена.")


@router.message(
    F.chat.type == ChatType.PRIVATE,
    F.from_user.is_not(None),
    F.from_user.func(lambda u: u and DIALOGS.get(u.id, {}).get("command") == "say_photo"),
    F.photo,
)
async def dialog_photo_input(message: Message):
    state = DIALOGS.get(message.from_user.id)
    if not state or state["command"] != "say_photo":
        return
    if not await require_owner(message):
        _stop_dialog(message.from_user.id)
        return
    file_id = message.photo[-1].file_id
    await bot.send_photo(get_group_id(), photo=file_id, caption=message.caption, parse_mode=None)
    _stop_dialog(message.from_user.id)
    await message.answer("✅ Фото отправлено в группу.")


@router.message(
    F.chat.type == ChatType.PRIVATE,
    F.from_user.is_not(None),
    F.from_user.func(lambda u: u and DIALOGS.get(u.id, {}).get("command") == "say_gif"),
    (F.animation | F.document),
)
async def dialog_gif_input(message: Message):
    state = DIALOGS.get(message.from_user.id)
    if not state or state["command"] != "say_gif":
        return
    if not await require_owner(message):
        _stop_dialog(message.from_user.id)
        return

    gif_id = None
    if message.animation:
        gif_id = message.animation.file_id
    elif message.document and message.document.mime_type and "gif" in message.document.mime_type.lower():
        gif_id = message.document.file_id

    if not gif_id:
        await message.answer("Это не GIF. Отправьте GIF или напишите стоп/отмена.")
        return

    await bot.send_animation(get_group_id(), animation=gif_id, caption=message.caption, parse_mode=None)
    _stop_dialog(message.from_user.id)
    await message.answer("✅ GIF отправлен в группу.")


@router.message(
    F.chat.type == ChatType.PRIVATE,
    F.from_user.is_not(None),
    F.from_user.func(lambda u: u and DIALOGS.get(u.id, {}).get("command") == "say_video"),
    F.video,
)
async def dialog_video_input(message: Message):
    state = DIALOGS.get(message.from_user.id)
    if not state or state["command"] != "say_video":
        return
    if not await require_owner(message):
        _stop_dialog(message.from_user.id)
        return

    await bot.send_video(get_group_id(), video=message.video.file_id, caption=message.caption, parse_mode=None)
    _stop_dialog(message.from_user.id)
    await message.answer("✅ Видео отправлено в группу.")


async def _parse_user(raw: str) -> Optional[int]:
    return await parse_target(raw)


async def _handle_warn_dialog(message: Message, step: int, data: Dict[str, Any], text: str):
    if step == 0:
        user_id = await _parse_user(text)
        if not user_id:
            await message.answer(USER_NOT_FOUND)
            return
        data["user_id"] = user_id
        DIALOGS[message.from_user.id]["step"] = 1
        await message.answer("Укажите срок варна: например `месяц`, `5 часов`, `2 дня` или `2026-03-31`.")
        return

    if step == 1:
        deadline = parse_deadline(text)
        if not deadline or deadline <= datetime.now():
            await message.answer("Не удалось распознать срок. Пример: месяц, 2 дня, 5 часов, 2026-03-31")
            return
        data["expires_at"] = deadline.isoformat(timespec="seconds")
        DIALOGS[message.from_user.id]["step"] = 2
        await message.answer("Укажите причину варна.")
        return

    warn_id, total, third, expires_at = await issue_warn(
        data["user_id"],
        message.from_user.id,
        text,
        "manual",
        expires_at=data["expires_at"],
    )
    _stop_dialog(message.from_user.id)
    expires_text = expires_at.replace("T", " ")
    suffix = " Пользователь автоматически получил мут (3-й варн)." if third else ""
    await message.answer(f"✅ Варн выдан: #{warn_id}. Активных варнов: {total}. Срок до: {expires_text}.{suffix}")


async def _handle_rest_add_dialog(message: Message, step: int, data: Dict[str, Any], text: str):
    if step == 0:
        user_id = await _parse_user(text)
        if not user_id:
            await message.answer(USER_NOT_FOUND)
            return
        data["user_id"] = user_id
        DIALOGS[message.from_user.id]["step"] = 1
        await message.answer("Укажите срок реста: `бессрочно`/`0` или срок (`месяц`, `7 дней`, `2026-03-31`).")
        return

    if step == 1:
        if text.lower() in {"0", "бессрочно", "навсегда"}:
            data["expires_at"] = None
        else:
            deadline = parse_deadline(text)
            if not deadline or deadline <= datetime.now():
                await message.answer("Не удалось распознать срок реста.")
                return
            data["expires_at"] = deadline.isoformat(timespec="seconds")
        DIALOGS[message.from_user.id]["step"] = 2
        await message.answer("Укажите название реста/роли.")
        return

    set_rest_until(data["user_id"], text, data["expires_at"], message.from_user.id)
    _stop_dialog(message.from_user.id)
    if data["expires_at"]:
        await message.answer(f"✅ Рест выдан до {data['expires_at'].replace('T', ' ')}.")
    else:
        await message.answer("✅ Рест выдан бессрочно.")


async def _handle_rest_extend_dialog(message: Message, step: int, data: Dict[str, Any], text: str):
    if step == 0:
        user_id = await _parse_user(text)
        if not user_id:
            await message.answer(USER_NOT_FOUND)
            return
        data["user_id"] = user_id
        DIALOGS[message.from_user.id]["step"] = 1
        await message.answer("Укажите, на сколько продлить рест (например `5 часов`, `2 дня`, `месяц`).")
        return

    minutes = parse_ru_duration_to_minutes(text)
    if not minutes:
        await message.answer("Не удалось распознать длительность.")
        return

    changed = extend_rest(data["user_id"], minutes)
    _stop_dialog(message.from_user.id)
    if not changed:
        await message.answer("⚠️ У пользователя нет активного реста.")
        return
    await message.answer("✅ Рест продлен.")


async def _handle_rest_del_dialog(message: Message, step: int, text: str):
    if step != 0:
        _stop_dialog(message.from_user.id)
        return

    user_id = await _parse_user(text)
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return

    remove_rest(user_id)
    _stop_dialog(message.from_user.id)
    await message.answer("✅ Рест снят.")


async def _handle_mute_dialog(message: Message, step: int, data: Dict[str, Any], text: str):
    if step == 0:
        user_id = await _parse_user(text)
        if not user_id:
            await message.answer(USER_NOT_FOUND)
            return
        data["user_id"] = user_id
        DIALOGS[message.from_user.id]["step"] = 1
        await message.answer("Укажите срок мута (например `5 минут`, `2 часа`, `1 день`, `месяц`).")
        return

    if step == 1:
        minutes = parse_ru_duration_to_minutes(text)
        if not minutes:
            await message.answer("Не удалось распознать длительность мута.")
            return
        data["minutes"] = int(minutes)
        DIALOGS[message.from_user.id]["step"] = 2
        await message.answer("Укажите причину мута.")
        return

    result = await mute_user(data["user_id"], data["minutes"], message.from_user.id, text)
    _stop_dialog(message.from_user.id)
    await message.answer(result)


async def _handle_unmute_dialog(message: Message, step: int, text: str):
    if step != 0:
        _stop_dialog(message.from_user.id)
        return

    user_id = await _parse_user(text)
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return

    _stop_dialog(message.from_user.id)
    await message.answer(await unmute_user(user_id))


async def _handle_ban_dialog(message: Message, step: int, data: Dict[str, Any], text: str):
    if step == 0:
        user_id = await _parse_user(text)
        if not user_id:
            await message.answer(USER_NOT_FOUND)
            return
        data["user_id"] = user_id
        DIALOGS[message.from_user.id]["step"] = 1
        await message.answer("Укажите причину бана.")
        return

    try:
        await bot.ban_chat_member(get_group_id(), data["user_id"])
        _stop_dialog(message.from_user.id)
        await message.answer(f"✅ Пользователь забанен. Причина: {text}.")
    except TelegramBadRequest as exc:
        await message.answer(f"⚠️ Не удалось забанить пользователя: {exc.message}")


async def _handle_kick_dialog(message: Message, step: int, data: Dict[str, Any], text: str):
    if step == 0:
        user_id = await _parse_user(text)
        if not user_id:
            await message.answer(USER_NOT_FOUND)
            return
        data["user_id"] = user_id
        DIALOGS[message.from_user.id]["step"] = 1
        await message.answer("Укажите причину кика.")
        return

    try:
        group_id = get_group_id()
        await bot.ban_chat_member(group_id, data["user_id"])
        await bot.unban_chat_member(group_id, data["user_id"], only_if_banned=True)
        _stop_dialog(message.from_user.id)
        await message.answer(f"✅ Пользователь кикнут. Причина: {text}.")
    except TelegramBadRequest as exc:
        await message.answer(f"⚠️ Не удалось кикнуть пользователя: {exc.message}")


async def _handle_unban_dialog(message: Message, step: int, text: str):
    if step != 0:
        _stop_dialog(message.from_user.id)
        return

    user_id = await _parse_user(text)
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return

    try:
        await bot.unban_chat_member(get_group_id(), user_id, only_if_banned=True)
        _stop_dialog(message.from_user.id)
        await message.answer("✅ Пользователь разбанен.")
    except TelegramBadRequest as exc:
        await message.answer(f"⚠️ Не удалось разбанить пользователя: {exc.message}")


async def _handle_unwarn_dialog(message: Message, step: int, text: str):
    if step != 0:
        _stop_dialog(message.from_user.id)
        return

    raw = text.strip()
    if raw.isdigit():
        if remove_warn(int(raw)):
            _stop_dialog(message.from_user.id)
            await message.answer("✅ Варн снят.")
        else:
            await message.answer("⚠️ Активный варн с таким ID не найден.")
        return

    user_id = await parse_target(raw)
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return

    removed_warn_id = remove_latest_warn_by_user(user_id)
    _stop_dialog(message.from_user.id)
    if removed_warn_id is None:
        await message.answer("⚠️ У пользователя нет активных варнов.")
        return
    await message.answer(f"✅ Снят последний активный варн пользователя: #{removed_warn_id}.")


async def _handle_say_dialog(message: Message, step: int, text: str):
    if step != 0:
        _stop_dialog(message.from_user.id)
        return
    await bot.send_message(get_group_id(), text, parse_mode=None)
    _stop_dialog(message.from_user.id)
    await message.answer("✅ Сообщение отправлено в группу.")


async def _handle_say_any_dialog(message: Message, step: int, text: str):
    if step != 0:
        _stop_dialog(message.from_user.id)
        return
    try:
        await _send_any_to_group(message)
    except TelegramBadRequest as exc:
        await message.answer(f"⚠️ Не удалось отправить сообщение: {exc.message}")
        return
    except Exception as exc:
        await message.answer(f"⚠️ Ошибка отправки: {exc}")
        return
    _stop_dialog(message.from_user.id)
    await message.answer("✅ Сообщение отправлено в группу.")


async def _send_any_to_group(message: Message):
    await bot.copy_message(
        chat_id=get_group_id(),
        from_chat_id=message.chat.id,
        message_id=message.message_id,
    )


@router.message(
    F.chat.type == ChatType.PRIVATE,
    F.from_user.is_not(None),
    F.from_user.func(lambda u: u and u.id in DIALOGS),
)
async def dialog_any_message_input(message: Message):
    state = DIALOGS.get(message.from_user.id)
    if not state or state["command"] != "say_any":
        return
    if not await require_owner(message):
        _stop_dialog(message.from_user.id)
        return
    text = (message.text or "").strip().lower()
    if text in CANCEL_WORDS:
        _stop_dialog(message.from_user.id)
        await message.answer("Команда отменена.")
        return
    try:
        await _send_any_to_group(message)
    except TelegramBadRequest as exc:
        await message.answer(f"⚠️ Не удалось отправить сообщение: {exc.message}")
        return
    except Exception as exc:
        await message.answer(f"⚠️ Ошибка отправки: {exc}")
        return
    _stop_dialog(message.from_user.id)
    await message.answer("✅ Сообщение отправлено в группу.")


async def _handle_add_admin_dialog(message: Message, step: int, data: Dict[str, Any], text: str):
    if step == 0:
        user_id = await _parse_user(text)
        if not user_id:
            await message.answer(USER_NOT_FOUND)
            return
        data["user_id"] = int(user_id)
        DIALOGS[message.from_user.id]["step"] = 1
        await message.answer("Укажите имя админа (или '-' чтобы использовать ID).")
        return

    name = text.strip()
    if name == "-":
        name = str(data["user_id"])
    add_admin(data["user_id"], name)
    _stop_dialog(message.from_user.id)
    await message.answer("✅ Админ добавлен.")


async def _handle_del_admin_dialog(message: Message, step: int, text: str):
    if step != 0:
        _stop_dialog(message.from_user.id)
        return
    user_id = await _parse_user(text)
    if not user_id:
        await message.answer(USER_NOT_FOUND)
        return
    remove_admin(int(user_id))
    _stop_dialog(message.from_user.id)
    await message.answer("✅ Админ удален.")


async def _handle_del_complaint_dialog(message: Message, step: int, text: str):
    if step != 0:
        _stop_dialog(message.from_user.id)
        return
    raw = text.strip()
    if not raw.isdigit():
        await message.answer("Укажите числовой ID жалобы.")
        return
    complaint_id = int(raw)
    changed = delete_complaint(complaint_id)
    _stop_dialog(message.from_user.id)
    if changed:
        await message.answer("✅ Жалоба помечена как неактивная.")
    else:
        await message.answer("⚠️ Активная жалоба с таким ID не найдена.")


async def _handle_db_user_del_dialog(message: Message, step: int, text: str):
    if step != 0:
        _stop_dialog(message.from_user.id)
        return
    raw = text.strip()
    if not raw.isdigit():
        await message.answer("Укажите числовой user_id.")
        return
    user_id = int(raw)
    removed = purge_user_from_db(user_id)
    _stop_dialog(message.from_user.id)
    if removed:
        await message.answer(f"✅ Пользователь {user_id} удален из БД.")
    else:
        await message.answer("⚠️ Пользователь не найден в users. Связанные записи очищены.")



