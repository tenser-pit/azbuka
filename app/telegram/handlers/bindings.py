from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Location, PendingMaxChat, Trainer, TrainerAssignment
from app.telegram.keyboards import format_weekdays
from app.telegram.states import BindChatStates, BindTrainerStates

router = Router()


@router.message(Command("bind_chat"))
async def start_bind_chat(message: Message, state: FSMContext, session: AsyncSession) -> None:
    result = await session.execute(
        select(PendingMaxChat).order_by(PendingMaxChat.added_at.desc())
    )
    pending_chats = list(result.scalars().all())
    if not pending_chats:
        await message.answer("Непривязанных чатов нет.")
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=chat.title, callback_data=f"bindchat:{chat.id}")]
            for chat in pending_chats
        ]
    )
    await state.set_state(BindChatStates.choosing_chat)
    await message.answer("Выберите MAX-чат:", reply_markup=keyboard)


@router.callback_query(BindChatStates.choosing_chat, F.data.startswith("bindchat:"))
async def bind_chat_choose_location(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    pending_id = int(callback.data.split(":")[1])
    result = await session.execute(
        select(Location).where(Location.max_chat_id.is_(None)).order_by(Location.name)
    )
    locations = list(result.scalars().all())
    if not locations:
        await callback.message.edit_text("Все локации уже привязаны к чатам.")
        await state.clear()
        await callback.answer()
        return

    await state.update_data(pending_id=pending_id)
    await state.set_state(BindChatStates.choosing_location)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=location.name,
                    callback_data=f"bindloc:{pending_id}:{location.id}",
                )
            ]
            for location in locations
        ]
    )
    await callback.message.edit_text("Выберите локацию:", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(BindChatStates.choosing_location, F.data.startswith("bindloc:"))
async def bind_chat_confirm(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    _, pending_id, location_id = callback.data.split(":")
    pending_id = int(pending_id)
    location_id = int(location_id)

    pending_result = await session.execute(
        select(PendingMaxChat).where(PendingMaxChat.id == pending_id)
    )
    pending_chat = pending_result.scalar_one_or_none()
    location_result = await session.execute(select(Location).where(Location.id == location_id))
    location = location_result.scalar_one_or_none()

    if pending_chat is None or location is None:
        await callback.message.edit_text("Чат или локация не найдены.")
        await state.clear()
        await callback.answer()
        return

    location.max_chat_id = pending_chat.max_chat_id
    await session.execute(delete(PendingMaxChat).where(PendingMaxChat.id == pending_id))
    await session.commit()

    await callback.message.edit_text(
        f"Чат «{pending_chat.title}» привязан к {location.name}."
    )
    await state.clear()
    await callback.answer("Привязано")


@router.message(Command("bind_trainer"))
async def start_bind_trainer(message: Message, state: FSMContext, session: AsyncSession) -> None:
    result = await session.execute(select(Trainer).where(Trainer.is_active.is_(True)))
    trainers = list(result.scalars().all())
    if not trainers:
        await message.answer("Тренеры не найдены.")
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=trainer.name, callback_data=f"bindtr:{trainer.id}")]
            for trainer in trainers
        ]
    )
    await state.set_state(BindTrainerStates.choosing_trainer)
    await message.answer("Выберите тренера:", reply_markup=keyboard)


@router.callback_query(BindTrainerStates.choosing_trainer, F.data.startswith("bindtr:"))
async def bind_trainer_choose_location(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    trainer_id = int(callback.data.split(":")[1])
    result = await session.execute(select(Location).order_by(Location.name))
    locations = list(result.scalars().all())
    if not locations:
        await callback.message.edit_text("Локации не найдены.")
        await state.clear()
        await callback.answer()
        return

    await state.update_data(trainer_id=trainer_id, weekdays=[])
    await state.set_state(BindTrainerStates.choosing_location)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=location.name,
                    callback_data=f"bindtrloc:{trainer_id}:{location.id}",
                )
            ]
            for location in locations
        ]
    )
    await callback.message.edit_text("Выберите локацию:", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(BindTrainerStates.choosing_location, F.data.startswith("bindtrloc:"))
async def bind_trainer_choose_weekdays(
    callback: CallbackQuery, state: FSMContext
) -> None:
    _, trainer_id, location_id = callback.data.split(":")
    await state.update_data(
        trainer_id=int(trainer_id),
        location_id=int(location_id),
        weekdays=[],
    )
    await state.set_state(BindTrainerStates.choosing_weekdays)
    await callback.message.edit_text(
        "Выберите дни недели:",
        reply_markup=_weekdays_keyboard([]),
    )
    await callback.answer()


@router.callback_query(BindTrainerStates.choosing_weekdays, F.data.startswith("wd:"))
async def bind_trainer_toggle_weekday(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    action = callback.data.removeprefix("wd:")
    data = await state.get_data()
    weekdays = list(data.get("weekdays", []))

    if action == "save":
        if not weekdays:
            await callback.answer("Выберите хотя бы один день.", show_alert=True)
            return
        await _save_assignment(callback, state, session)
        return

    if action == "preset_mw":
        weekdays = [0, 2]
    elif action == "preset_tt":
        weekdays = [1, 3]
    else:
        day = int(action)
        if day in weekdays:
            weekdays.remove(day)
        else:
            weekdays.append(day)

    await state.update_data(weekdays=weekdays)
    await callback.message.edit_reply_markup(reply_markup=_weekdays_keyboard(weekdays))
    await callback.answer()


async def _save_assignment(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    data = await state.get_data()
    trainer_id = data["trainer_id"]
    location_id = data["location_id"]
    weekdays = sorted(data["weekdays"])

    result = await session.execute(
        select(TrainerAssignment).where(
            TrainerAssignment.trainer_id == trainer_id,
            TrainerAssignment.location_id == location_id,
        )
    )
    assignment = result.scalar_one_or_none()
    if assignment is None:
        assignment = TrainerAssignment(
            trainer_id=trainer_id,
            location_id=location_id,
            weekdays=weekdays,
        )
        session.add(assignment)
    else:
        assignment.weekdays = weekdays
        assignment.is_active = True

    trainer_result = await session.execute(select(Trainer).where(Trainer.id == trainer_id))
    location_result = await session.execute(select(Location).where(Location.id == location_id))
    trainer = trainer_result.scalar_one()
    location = location_result.scalar_one()
    await session.commit()

    await callback.message.edit_text(
        f"Сохранено: {trainer.name} → {location.name} ({format_weekdays(weekdays)})"
    )
    await state.clear()
    await callback.answer("Сохранено")


def _weekdays_keyboard(selected: list[int]) -> InlineKeyboardMarkup:
    def label(day: int, title: str) -> str:
        return f"✅ {title}" if day in selected else title

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=label(0, "Пн"), callback_data="wd:0"),
                InlineKeyboardButton(text=label(1, "Вт"), callback_data="wd:1"),
                InlineKeyboardButton(text=label(2, "Ср"), callback_data="wd:2"),
                InlineKeyboardButton(text=label(3, "Чт"), callback_data="wd:3"),
            ],
            [
                InlineKeyboardButton(text="Пн+Ср", callback_data="wd:preset_mw"),
                InlineKeyboardButton(text="Вт+Чт", callback_data="wd:preset_tt"),
            ],
            [InlineKeyboardButton(text="✅ Сохранить", callback_data="wd:save")],
        ]
    )
