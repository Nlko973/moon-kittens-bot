from datetime import datetime

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message

from app.keyboards import BTN_COMPLAINT_CREATE, BTN_COMPLAINT_MINE, BTN_MY_NORM, BTN_MY_REST, BTN_MY_WARNS, BTN_OWNER_MSG_CREATE, BTN_OWNER_MSG_MINE, BTN_TAKE_REST
from app.services.chat_settings import get_group_id
from app.services.access import is_private
from app.services.owner_notifications import notify_owner
from app.texts import format_user, norm_status_text, rest_status_infinite, rest_status_none, rest_status_with_days
from db import count_active_complaints, count_active_owner_messages, create_complaint, create_owner_message, get_biweekly_norm, get_rest, get_user_complaints, get_user_owner_messages, get_user_period_count, get_user_warns, user_exists_in_db

router = Router()

AWAITING_COMPLAINT_USERS: set[int] = set()
AWAITING_OWNER_MESSAGE_USERS: set[int] = set()
AWAITING_REST_REQUEST_USERS: dict[int, dict[str, str]] = {}


def _is_target_group(message: Message) -> bool:
    return message.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP} and message.chat.id == get_group_id()


def _is_private(message: Message) -> bool:
    return is_private(message)


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_COMPLAINT_CREATE)
@router.message(Command("complaint"))
async def complaint_start(message: Message):
    if not _is_private(message):
        return
    if not user_exists_in_db(message.from_user.id):
        await message.answer("⚠️ Жалобу могут отправлять только участники, которые есть в базе бота.")
        return
    active_count = count_active_complaints(message.from_user.id)
    if active_count >= 3:
        await message.answer("⚠️ У вас уже 3 активные жалобы. Дождитесь, пока админ закроет хотя бы одну.")
        return
    AWAITING_COMPLAINT_USERS.add(message.from_user.id)
    await message.answer("Опишите жалобу одним сообщением. Отправьте текст следующим сообщением.")


@router.message(F.chat.type == ChatType.PRIVATE, F.from_user.is_not(None), F.text, F.from_user.func(lambda u: u and u.id in AWAITING_COMPLAINT_USERS))
async def complaint_receive(message: Message):
    if message.from_user.id not in AWAITING_COMPLAINT_USERS:
        return

    if not user_exists_in_db(message.from_user.id):
        AWAITING_COMPLAINT_USERS.discard(message.from_user.id)
        await message.answer("⚠️ Жалобу могут отправлять только участники, которые есть в базе бота.")
        return

    text = message.text.strip()
    if not text:
        await message.answer("Текст жалобы пустой. Напишите жалобу сообщением.")
        return

    active_count = count_active_complaints(message.from_user.id)
    if active_count >= 3:
        AWAITING_COMPLAINT_USERS.discard(message.from_user.id)
        await message.answer("⚠️ У вас уже 3 активные жалобы. Новую сейчас отправить нельзя.")
        return

    AWAITING_COMPLAINT_USERS.remove(message.from_user.id)
    complaint_id = create_complaint(message.from_user.id, message.from_user.username, message.from_user.full_name, text)
    if complaint_id is None:
        if not user_exists_in_db(message.from_user.id):
            await message.answer("⚠️ Жалобу могут отправлять только участники, которые есть в базе бота.")
        else:
            await message.answer("⚠️ У вас уже 3 активные жалобы. Новую сейчас отправить нельзя.")
        return

    owner_notice = (
        "📩 Новая жалоба\n"
        f"Номер: #{complaint_id}\n"
        f"Автор: {format_user(message.from_user.id, message.from_user.username, message.from_user.full_name)} "
        f"({message.from_user.id})\n"
        f"Текст: {text}"
    )
    await notify_owner(owner_notice)

    await message.answer(f"✅ Жалоба принята. Номер: #{complaint_id}")


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_OWNER_MSG_CREATE)
@router.message(Command("owner_msg"))
async def owner_message_start(message: Message):
    if not _is_private(message):
        return
    if not user_exists_in_db(message.from_user.id):
        await message.answer("⚠️ Сообщение влд могут отправлять только участники, которые есть в базе бота.")
        return
    active_count = count_active_owner_messages(message.from_user.id)
    if active_count >= 3:
        await message.answer("⚠️ У вас уже 3 активных сообщений влд. Дождитесь, пока админ закроет хотя бы одно.")
        return
    AWAITING_OWNER_MESSAGE_USERS.add(message.from_user.id)
    await message.answer("Опишите сообщение для влд одним сообщением. Отправьте текст следующим сообщением.")


@router.message(F.chat.type == ChatType.PRIVATE, F.from_user.is_not(None), F.text, F.from_user.func(lambda u: u and u.id in AWAITING_OWNER_MESSAGE_USERS))
async def owner_message_receive(message: Message):
    if message.from_user.id not in AWAITING_OWNER_MESSAGE_USERS:
        return

    if not user_exists_in_db(message.from_user.id):
        AWAITING_OWNER_MESSAGE_USERS.discard(message.from_user.id)
        await message.answer("⚠️ Сообщение влд могут отправлять только участники, которые есть в базе бота.")
        return

    text = message.text.strip()
    if not text:
        await message.answer("Текст сообщения пустой. Напишите сообщение влд сообщением.")
        return

    active_count = count_active_owner_messages(message.from_user.id)
    if active_count >= 3:
        AWAITING_OWNER_MESSAGE_USERS.discard(message.from_user.id)
        await message.answer("⚠️ У вас уже 3 активных сообщений влд. Новое сейчас отправить нельзя.")
        return

    AWAITING_OWNER_MESSAGE_USERS.remove(message.from_user.id)
    owner_message_id = create_owner_message(message.from_user.id, message.from_user.username, message.from_user.full_name, text)
    if owner_message_id is None:
        if not user_exists_in_db(message.from_user.id):
            await message.answer("⚠️ Сообщение влд могут отправлять только участники, которые есть в базе бота.")
        else:
            await message.answer("⚠️ У вас уже 3 активных сообщений влд. Новое сейчас отправить нельзя.")
        return

    owner_notice = (
        "📩 Новое сообщение влд\n"
        f"Номер: #{owner_message_id}\n"
        f"Автор: {format_user(message.from_user.id, message.from_user.username, message.from_user.full_name)} "
        f"({message.from_user.id})\n"
        f"Текст: {text}"
    )
    await notify_owner(owner_notice)

    await message.answer(f"✅ Сообщение влд принято. Номер: #{owner_message_id}")


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_TAKE_REST)
@router.message(Command("take_rest"))
async def rest_request_start(message: Message):
    if not _is_private(message):
        return
    if not user_exists_in_db(message.from_user.id):
        await message.answer("⚠️ Рест могут запросить только участники, которые есть в базе бота.")
        return
    AWAITING_REST_REQUEST_USERS[message.from_user.id] = {"step": "role"}
    await message.answer("Укажите роль, с которой хотите взять рест. Для отмены: стоп/отмена.")


@router.message(F.chat.type == ChatType.PRIVATE, F.from_user.is_not(None), F.text, F.from_user.func(lambda u: u and u.id in AWAITING_REST_REQUEST_USERS))
async def rest_request_receive(message: Message):
    state = AWAITING_REST_REQUEST_USERS.get(message.from_user.id)
    if not state:
        return
    text = (message.text or "").strip()
    if text.lower() in {"стоп", "отмена", "cancel", "stop"}:
        AWAITING_REST_REQUEST_USERS.pop(message.from_user.id, None)
        await message.answer("Заявка на рест отменена.")
        return
    if not text:
        await message.answer("Ответ пустой. Напишите текстом.")
        return

    step = state["step"]
    if step == "role":
        state["role"] = text
        state["step"] = "duration"
        await message.answer("Укажите срок реста: например `3 дня`, `неделя`, `до 2026-08-20`.")
        return
    if step == "duration":
        state["duration"] = text
        state["step"] = "reason"
        await message.answer("Укажите причину реста.")
        return

    AWAITING_REST_REQUEST_USERS.pop(message.from_user.id, None)
    notice = (
        "🛌 Новая заявка на рест\n"
        f"Автор: {format_user(message.from_user.id, message.from_user.username, message.from_user.full_name)} "
        f"({message.from_user.id})\n"
        f"Роль: {state.get('role')}\n"
        f"Срок: {state.get('duration')}\n"
        f"Причина: {text}"
    )
    await notify_owner(notice)
    await message.answer("✅ Заявка на рест отправлена.")


@router.message(F.text == BTN_MY_NORM)
@router.message(F.text.regexp(r"(?i)^моя\s+норма$"))
@router.message(F.text.regexp(r"(?i)^(?:📊\s*)?моя\s+норма$"))
@router.message(Command("mynorm"))
async def mynorm(message: Message):
    if not (_is_private(message) or _is_target_group(message)):
        return
    norm = get_biweekly_norm()
    count = get_user_period_count(message.from_user.id)
    await message.answer(norm_status_text(message.from_user.id, message.from_user.username, message.from_user.full_name, count, norm))


@router.message(F.text == BTN_MY_REST)
@router.message(F.text.regexp(r"(?i)^мой\s+рест$"))
@router.message(F.text.regexp(r"(?i)^(?:🛌\s*)?мой\s+рест$"))
@router.message(Command("myrest"))
async def myrest(message: Message):
    if not (_is_private(message) or _is_target_group(message)):
        return

    rest = get_rest(message.from_user.id)
    if not rest:
        await message.answer(rest_status_none(message.from_user.id, message.from_user.username, message.from_user.full_name))
        return

    expires_at = rest["expires_at"]
    if not expires_at:
        await message.answer(
            rest_status_infinite(message.from_user.id, message.from_user.username, message.from_user.full_name, rest["role_name"])
        )
        return

    remain = datetime.fromisoformat(expires_at) - datetime.now()
    days = max(0, remain.days)
    await message.answer(
        rest_status_with_days(message.from_user.id, message.from_user.username, message.from_user.full_name, rest["role_name"], days)
    )


@router.message(F.text == BTN_MY_WARNS)
@router.message(F.text.regexp(r"(?i)^мои\s+варны$"))
@router.message(F.text.regexp(r"(?i)^(?:⚠️\s*)?мои\s+варны$"))
@router.message(Command("mywarns"))
async def mywarns(message: Message):
    if not (_is_private(message) or _is_target_group(message)):
        return

    warns = get_user_warns(message.from_user.id, active_only=True)
    if not warns:
        await message.answer("✅ У вас нет активных варнов.")
        return

    lines = [f"⚠️ Ваши активные варны: {len(warns)}."]
    for idx, row in enumerate(warns[:20], start=1):
        lines.append(f"{idx}. [{row['warn_type']}] {row['reason']}")
    await message.answer("\n".join(lines))


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_COMPLAINT_MINE)
@router.message(Command("my_complaints"))
async def my_complaints(message: Message):
    rows = get_user_complaints(message.from_user.id)
    if not rows:
        await message.answer("У вас пока нет жалоб.")
        return

    lines = ["Ваши жалобы:"]
    for idx, row in enumerate(rows[:20], start=1):
        lines.append(f"{idx}. {row['created_at']}: {row['text']}")
    await message.answer("\n".join(lines))


@router.message(F.chat.type == ChatType.PRIVATE, F.text == BTN_OWNER_MSG_MINE)
@router.message(Command("my_owner_msgs"))
async def my_owner_messages(message: Message):
    rows = get_user_owner_messages(message.from_user.id)
    if not rows:
        await message.answer("У вас пока нет сообщений влд.")
        return

    lines = ["Ваши сообщения влд:"]
    for idx, row in enumerate(rows[:20], start=1):
        lines.append(f"{idx}. {row['created_at']}: {row['text']}")
    await message.answer("\n".join(lines))

