from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.config import Settings
from app.telegram.handlers import bindings, commands, day_off
from app.telegram.middlewares import AdminMiddleware


class SessionMiddleware:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], settings: Settings):
        self.session_factory = session_factory
        self.settings = settings

    async def __call__(self, handler, event, data):
        async with self.session_factory() as session:
            data["session"] = session
            data["settings"] = self.settings
            return await handler(event, data)


def create_dispatcher(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.message.middleware(AdminMiddleware(settings))
    dispatcher.callback_query.middleware(AdminMiddleware(settings))
    dispatcher.message.middleware(SessionMiddleware(session_factory, settings))
    dispatcher.callback_query.middleware(SessionMiddleware(session_factory, settings))

    dispatcher.include_router(commands.router)
    dispatcher.include_router(bindings.router)
    dispatcher.include_router(day_off.router)
    return dispatcher
