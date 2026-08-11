from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import PhoneSource
from app.db.models import DailyReport, ReportPhone

PHONE_CANDIDATE_PATTERN = re.compile(
    r"(?:\+?7|8)?[\s\-\(]*\d{3}[\s\-\)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}"
    r"|(?:\+?7|8)\d{10}"
    r"|\d{10,11}"
)

HEADER_TRIAL_PATTERN = re.compile(r"с\s+пробного\s*:", re.IGNORECASE)
HEADER_OUTREACH_PATTERN = re.compile(r"с\s+общения\s*:", re.IGNORECASE)
HEADER_ANY_PATTERN = re.compile(
    r"(с\s+пробного\s*:|с\s+общения\s*:)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedPhone:
    phone_raw: str
    phone_normalized: str
    source: PhoneSource


def normalize_phone(raw_phone: str) -> str | None:
    digits = re.sub(r"\D", "", raw_phone)
    if len(digits) == 11 and digits.startswith(("7", "8")):
        return "7" + digits[1:]
    if len(digits) == 10:
        return "7" + digits
    return None


def parse_phones_from_report_text(message_text: str) -> list[ParsedPhone]:
    blocks = _extract_source_blocks(message_text)
    parsed: list[ParsedPhone] = []
    seen: set[tuple[str, PhoneSource]] = set()

    for source, block_text in blocks:
        for match in PHONE_CANDIDATE_PATTERN.finditer(block_text):
            raw_phone = match.group(0).strip()
            normalized = normalize_phone(raw_phone)
            if normalized is None:
                continue
            key = (normalized, source)
            if key in seen:
                continue
            seen.add(key)
            parsed.append(
                ParsedPhone(
                    phone_raw=raw_phone,
                    phone_normalized=normalized,
                    source=source,
                )
            )
    return parsed


def _extract_source_blocks(message_text: str) -> list[tuple[PhoneSource, str]]:
    matches = list(HEADER_ANY_PATTERN.finditer(message_text))
    if not matches:
        return []

    blocks: list[tuple[PhoneSource, str]] = []
    for index, match in enumerate(matches):
        header = match.group(1).lower()
        if HEADER_TRIAL_PATTERN.fullmatch(header.strip()) or "пробного" in header:
            source = PhoneSource.TRIAL
        else:
            source = PhoneSource.OUTREACH

        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(message_text)
        blocks.append((source, message_text[start:end]))
    return blocks


async def replace_phones_for_report(
    session: AsyncSession,
    daily_report: DailyReport,
    parsed_phones: list[ParsedPhone],
) -> None:
    await session.execute(
        delete(ReportPhone).where(ReportPhone.daily_report_id == daily_report.id)
    )
    for parsed_phone in parsed_phones:
        session.add(
            ReportPhone(
                daily_report_id=daily_report.id,
                trainer_id=daily_report.trainer_id,
                location_id=daily_report.location_id,
                phone_raw=parsed_phone.phone_raw,
                phone_normalized=parsed_phone.phone_normalized,
                source=parsed_phone.source,
            )
        )
    await session.commit()


async def get_report_phones(
    session: AsyncSession,
    daily_report_id: int,
) -> list[ReportPhone]:
    result = await session.execute(
        select(ReportPhone)
        .where(ReportPhone.daily_report_id == daily_report_id)
        .order_by(ReportPhone.id)
    )
    return list(result.scalars().all())
