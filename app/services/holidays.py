import logging
from datetime import date

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import HolidayCache

logger = logging.getLogger(__name__)

_memory_cache: dict[str, str] = {}


class HolidayService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def is_holiday(self, check_date: date) -> bool:
        day_code = await self._get_day_code(check_date)
        if day_code is None:
            logger.warning("isdayoff.ru unavailable, treating %s as working day", check_date)
            return False
        return day_code == "1"

    async def _get_day_code(self, check_date: date) -> str | None:
        cache_key = f"{check_date.year}-{check_date.month:02d}"
        month_data = await self._get_month_data(cache_key, check_date.year, check_date.month)
        if month_data is None:
            return None
        day_index = check_date.day - 1
        if day_index >= len(month_data):
            return None
        return month_data[day_index]

    async def _get_month_data(self, cache_key: str, year: int, month: int) -> str | None:
        if cache_key in _memory_cache:
            return _memory_cache[cache_key]

        result = await self.session.execute(
            select(HolidayCache).where(HolidayCache.cache_key == cache_key)
        )
        cached = result.scalar_one_or_none()
        if cached is not None:
            _memory_cache[cache_key] = cached.data
            return cached.data

        fetched = await self._fetch_month_data(year, month)
        if fetched is None:
            return None

        if cached is None:
            self.session.add(HolidayCache(cache_key=cache_key, data=fetched))
        else:
            cached.data = fetched
        await self.session.commit()
        _memory_cache[cache_key] = fetched
        return fetched

    async def _fetch_month_data(self, year: int, month: int) -> str | None:
        url = f"https://isdayoff.ru/api/getdata?year={year}&month={month}"
        try:
            async with aiohttp.ClientSession() as http_session:
                async with http_session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status != 200:
                        return None
                    return (await response.text()).strip()
        except aiohttp.ClientError:
            logger.exception("Failed to fetch holiday data")
            return None
