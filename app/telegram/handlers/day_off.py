from datetime import date

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.db.models import Trainer
from app.services.reports import ReportService
from app.telegram.states import DayOffStates

router = Router()


@router.message(F.text == "🚫 Отменить рабочий день")
async def start_day_off(message: Message, state: FSMContext, session: AsyncSession) -> None:
    result = await session.execute(select(Trainer).where(Trainer.is_active.is_(True)))
    trainers = list(result.scalars().all())
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=trainer.name, callback_data=f"dayoff_tr:{trainer.id}")]
            for trainer in trainers
        ]
        + [[InlineKeyboardButton(text="👥 Все тренеры", callback_data="dayoff_tr:all")]]
    )
    await state.set_state(DayOffStates.choosing_trainer)
    await message.answer("Кто сегодня не работает?", reply_markup=keyboard)


@router.callback_query(DayOffStates.choosing_trainer, F.data.startswith("dayoff_tr:"))
async def day_off_choose_locations(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
) -> None:
    trainer_key = callback.data.split(":")[1]
    trainer_id = None if trainer_key == "all" else int(trainer_key)
    report_service = ReportService(session, settings)
    expected = await report_service.get_expected_reports(date.today())

    if trainer_id is not None:
        expected = [item for item in expected if item.trainer.id == trainer_id]

    if not expected:
        await callback.message.edit_text("На сегодня нет рабочих локаций для выбранного тренера.")
        await state.clear()
        await callback.answer()
        return

    location_options = {item.location.id: item.location.name for item in expected}
    await state.update_data(
        trainer_id=trainer_id,
        location_options=location_options,
        selected_location_ids=[],
    )
    await state.set_state(DayOffStates.choosing_locations)
    await callback.message.edit_text(
        "Выберите локации:",
        reply_markup=_locations_keyboard(location_options, []),
    )
    await callback.answer()


@router.callback_query(DayOffStates.choosing_locations, F.data.startswith("dayoff_loc:"))
async def day_off_toggle_location(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    action = callback.data.removeprefix("dayoff_loc:")
    data = await state.get_data()
    location_options: dict[str, str] = data["location_options"]
    options = {int(key): value for key, value in location_options.items()}
    selected: list[int] = list(data.get("selected_location_ids", []))

    if action == "all":
        selected = list(options.keys())
    elif action == "back":
        await state.set_state(DayOffStates.choosing_trainer)
        trainer_result = await session.execute(select(Trainer).where(Trainer.is_active.is_(True)))
        trainers = list(trainer_result.scalars().all())
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=trainer.name, callback_data=f"dayoff_tr:{trainer.id}")]
                for trainer in trainers
            ]
            + [[InlineKeyboardButton(text="👥 Все тренеры", callback_data="dayoff_tr:all")]]
        )
        await callback.message.edit_text("Кто сегодня не работает?", reply_markup=keyboard)
        await callback.answer()
        return
    elif action == "confirm":
        if not selected:
            await callback.answer("Выберите хотя бы одну локацию или «Все локации».", show_alert=True)
            return
        await state.update_data(selected_location_ids=selected)
        await state.set_state(DayOffStates.confirming)
        trainer_label = "Все тренеры" if data.get("trainer_id") is None else "выбранный тренер"
        location_names = ", ".join(options[location_id] for location_id in selected)
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Подтвердить", callback_data="dayoff_ok:yes"),
                    InlineKeyboardButton(text="❌ Отмена", callback_data="dayoff_ok:no"),
                ]
            ]
        )
        await callback.message.edit_text(
            f"Отменить рабочий день?\n{trainer_label} — {location_names}",
            reply_markup=keyboard,
        )
        await callback.answer()
        return
    else:
        location_id = int(action)
        if location_id in selected:
            selected.remove(location_id)
        else:
            selected.append(location_id)

    await state.update_data(selected_location_ids=selected)
    await callback.message.edit_reply_markup(
        reply_markup=_locations_keyboard(options, selected)
    )
    await callback.answer()


@router.callback_query(DayOffStates.confirming, F.data.startswith("dayoff_ok:"))
async def day_off_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
) -> None:
    if callback.data.endswith(":no"):
        await callback.message.edit_text("Отмена рабочего дня не выполнена.")
        await state.clear()
        await callback.answer()
        return

    data = await state.get_data()
    trainer_id = data.get("trainer_id")
    selected_location_ids = data.get("selected_location_ids", [])

    report_service = ReportService(session, settings)
    affected = await report_service.mark_excused(
        report_date=date.today(),
        trainer_id=trainer_id,
        location_ids=selected_location_ids,
        created_by=callback.from_user.id,
    )

    await callback.message.edit_text(
        f"Рабочий день отменён для {len(affected)} локаций."
    )
    await state.clear()
    await callback.answer("Готово")


def _locations_keyboard(
    options: dict[int, str], selected: list[int]
) -> InlineKeyboardMarkup:
    rows = []
    for location_id, name in options.items():
        prefix = "✅ " if location_id in selected else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{prefix}{name}",
                    callback_data=f"dayoff_loc:{location_id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="✅ Все локации", callback_data="dayoff_loc:all")])
    rows.append([InlineKeyboardButton(text="Далее →", callback_data="dayoff_loc:confirm")])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="dayoff_loc:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
