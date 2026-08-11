from datetime import date

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.services.admin_commands import AdminCommandService
from app.telegram.keyboards import main_menu_keyboard

router = Router()


def _commands(session: AsyncSession, settings: Settings) -> AdminCommandService:
    return AdminCommandService(session, settings)


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Панель мониторинга отчётов.",
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("status"))
@router.message(F.text == "📊 Статус сегодня")
async def cmd_status(message: Message, session: AsyncSession, settings: Settings) -> None:
    await message.answer(await _commands(session, settings).status_text())


@router.message(Command("week"))
async def cmd_week(message: Message, session: AsyncSession, settings: Settings) -> None:
    await message.answer(await _commands(session, settings).week_text())


@router.message(Command("month"))
async def cmd_month(message: Message, session: AsyncSession, settings: Settings) -> None:
    await message.answer(await _commands(session, settings).month_text())


@router.message(Command("salary"))
async def cmd_salary(message: Message, session: AsyncSession, settings: Settings) -> None:
    await message.answer(await _commands(session, settings).salary_text())


@router.message(Command("summary"))
async def cmd_summary(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    settings: Settings,
) -> None:
    commands = _commands(session, settings)
    parsed = commands.parse_summary_args(command.args)
    if isinstance(parsed, str):
        await message.answer(parsed)
        return
    start_date, end_date = parsed
    await message.answer(await commands.summary_text(start_date, end_date))


@router.message(Command("stats"))
async def cmd_stats(message: Message, session: AsyncSession, settings: Settings) -> None:
    await message.answer(await _commands(session, settings).stats_text())


@router.message(Command("remove_penalty"))
@router.message(F.text == "📋 Штрафы")
async def cmd_remove_penalty_list(
    message: Message, session: AsyncSession, settings: Settings
) -> None:
    await message.answer(await _commands(session, settings).active_penalties_text())


@router.message(F.text.regexp(r"^/rm_(\d+)$"))
async def cmd_remove_penalty(message: Message, session: AsyncSession, settings: Settings) -> None:
    penalty_id = int(message.text.removeprefix("/rm_"))
    await message.answer(
        await _commands(session, settings).remove_penalty(penalty_id, message.from_user.id)
    )


@router.message(Command("pending_chats"))
async def cmd_pending_chats(message: Message, session: AsyncSession, settings: Settings) -> None:
    await message.answer(await _commands(session, settings).pending_chats_text())


@router.message(Command("assignments"))
async def cmd_assignments(message: Message, session: AsyncSession, settings: Settings) -> None:
    await message.answer(await _commands(session, settings).assignments_text())


@router.message(Command("unassign"))
async def cmd_unassign(
    message: Message, command: CommandObject, session: AsyncSession, settings: Settings
) -> None:
    if not command.args or not command.args.isdigit():
        await message.answer("Использование: /unassign ID")
        return
    await message.answer(await _commands(session, settings).unassign(int(command.args)))


@router.message(Command("trainers"))
async def cmd_trainers(message: Message, session: AsyncSession, settings: Settings) -> None:
    await message.answer(await _commands(session, settings).trainers_text())


@router.message(Command("set_trainer_tg"))
async def cmd_set_trainer_tg(
    message: Message, command: CommandObject, session: AsyncSession, settings: Settings
) -> None:
    if not command.args:
        await message.answer("Использование: /set_trainer_tg TRAINER_ID TG_ID")
        return
    parts = command.args.split()
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        await message.answer("Использование: /set_trainer_tg TRAINER_ID TG_ID")
        return
    await message.answer(
        await _commands(session, settings).set_trainer_tg(int(parts[0]), int(parts[1]))
    )


@router.message(Command("set_trainer_max"))
async def cmd_set_trainer_max(
    message: Message, command: CommandObject, session: AsyncSession, settings: Settings
) -> None:
    if not command.args:
        await message.answer("Использование: /set_trainer_max TRAINER_ID USERNAME")
        return
    parts = command.args.split(maxsplit=1)
    if len(parts) != 2 or not parts[0].isdigit():
        await message.answer("Использование: /set_trainer_max TRAINER_ID USERNAME")
        return
    await message.answer(
        await _commands(session, settings).set_trainer_max_username(int(parts[0]), parts[1])
    )


@router.message(F.text == "🔗 Привязки")
async def bindings_menu(message: Message) -> None:
    await message.answer(
        "Привязки:\n"
        "/pending_chats — непривязанные чаты MAX\n"
        "/bind_chat — привязать чат к локации\n"
        "/bind_trainer — привязать тренера к локации\n"
        "/assignments — список связей\n"
        "/trainers — тренеры и их ID"
    )
