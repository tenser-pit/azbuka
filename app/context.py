from dataclasses import dataclass
from typing import TYPE_CHECKING

from aiogram import Bot
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.config import Settings

if TYPE_CHECKING:
    from app.max.client import MaxClient


@dataclass
class AppContext:
    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]
    telegram_bot: Bot
    max_client: "MaxClient"
