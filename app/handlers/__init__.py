from aiogram import Dispatcher

from app.handlers.admin import router as admin_router
from app.handlers.callbacks import router as callbacks_router
from app.handlers.common import router as common_router
from app.handlers.group_events import router as group_events_router
from app.handlers.member import router as member_router
from app.handlers.private_fallback import router as private_fallback_router


def register_handlers(dp: Dispatcher):
    dp.include_router(callbacks_router)
    dp.include_router(common_router)
    dp.include_router(member_router)
    dp.include_router(admin_router)
    dp.include_router(group_events_router)
    dp.include_router(private_fallback_router)
