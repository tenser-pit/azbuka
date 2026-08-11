from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Location, PendingMaxChat, Trainer, TrainerAssignment
from app.max.client import MaxClient
from app.services.admin_commands import AdminCommandService
from app.services.reports import ReportService
from app.telegram.keyboards import format_weekdays
from datetime import date

logger = logging.getLogger(__name__)

RM_PATTERN = re.compile(r"^/rm_(\d+)$")


def build_inline_keyboard(rows: list[list[tuple[str, str]]]) -> list[dict[str, Any]]:
    buttons = []
    for row in rows:
        buttons.append(
            [
                {"type": "callback", "text": button_text, "payload": payload}
                for button_text, payload in row
            ]
        )
    return [
        {
            "type": "inline_keyboard",
            "payload": {"buttons": buttons},
        }
    ]


class MaxAdminHandler:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        max_client: MaxClient,
        fsm_storage: dict[int, dict[str, Any]],
    ):
        self.session = session
        self.settings = settings
        self.max_client = max_client
        self.fsm_storage = fsm_storage
        self.commands = AdminCommandService(session, settings)

    def is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self.settings.admin_max_id_set

    async def handle_message(
        self,
        *,
        user_id: int,
        chat_id: int | None,
        text: str,
    ) -> bool:
        if not self.is_admin(user_id):
            return False

        text = (text or "").strip()
        if not text:
            return False

        state = self.fsm_storage.get(user_id)
        if state and not text.startswith("/"):
            handled = await self._continue_text_fsm(user_id, text, state)
            if handled:
                return True

        if text.startswith("/start"):
            await self._reply(user_id, chat_id, self.commands.start_menu_text())
            return True
        if text.startswith("/status") or text == "📊 Статус сегодня":
            await self._reply(user_id, chat_id, await self.commands.status_text())
            return True
        if text.startswith("/week"):
            await self._reply(user_id, chat_id, await self.commands.week_text())
            return True
        if text.startswith("/month"):
            await self._reply(user_id, chat_id, await self.commands.month_text())
            return True
        if text.startswith("/salary"):
            await self._reply(user_id, chat_id, await self.commands.salary_text())
            return True
        if text.startswith("/stats"):
            await self._reply(user_id, chat_id, await self.commands.stats_text())
            return True
        if text.startswith("/summary"):
            args = text[len("/summary") :].strip()
            parsed = self.commands.parse_summary_args(args or None)
            if isinstance(parsed, str):
                await self._reply(user_id, chat_id, parsed)
            else:
                start_date, end_date = parsed
                await self._reply(
                    user_id,
                    chat_id,
                    await self.commands.summary_text(start_date, end_date),
                )
            return True
        if text.startswith("/remove_penalty") or text == "📋 Штрафы":
            await self._reply(user_id, chat_id, await self.commands.active_penalties_text())
            return True
        rm_match = RM_PATTERN.match(text)
        if rm_match:
            await self._reply(
                user_id,
                chat_id,
                await self.commands.remove_penalty(int(rm_match.group(1)), user_id),
            )
            return True
        if text.startswith("/pending_chats"):
            await self._reply(user_id, chat_id, await self.commands.pending_chats_text())
            return True
        if text.startswith("/assignments"):
            await self._reply(user_id, chat_id, await self.commands.assignments_text())
            return True
        if text.startswith("/unassign"):
            parts = text.split()
            if len(parts) != 2 or not parts[1].isdigit():
                await self._reply(user_id, chat_id, "Использование: /unassign ID")
            else:
                await self._reply(
                    user_id,
                    chat_id,
                    await self.commands.unassign(int(parts[1])),
                )
            return True
        if text.startswith("/trainers"):
            await self._reply(user_id, chat_id, await self.commands.trainers_text())
            return True
        if text.startswith("/set_trainer_tg"):
            parts = text.split()
            if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
                await self._reply(user_id, chat_id, "Использование: /set_trainer_tg TRAINER_ID TG_ID")
            else:
                await self._reply(
                    user_id,
                    chat_id,
                    await self.commands.set_trainer_tg(int(parts[1]), int(parts[2])),
                )
            return True
        if text.startswith("/set_trainer_max"):
            parts = text.split(maxsplit=2)
            if len(parts) != 3 or not parts[1].isdigit():
                await self._reply(
                    user_id,
                    chat_id,
                    "Использование: /set_trainer_max TRAINER_ID USERNAME",
                )
            else:
                await self._reply(
                    user_id,
                    chat_id,
                    await self.commands.set_trainer_max_username(int(parts[1]), parts[2]),
                )
            return True
        if text.startswith("/bind_chat"):
            await self._start_bind_chat(user_id, chat_id)
            return True
        if text.startswith("/bind_trainer"):
            await self._start_bind_trainer(user_id, chat_id)
            return True
        if text.startswith("/day_off") or text == "🚫 Отменить рабочий день":
            await self._start_day_off(user_id, chat_id)
            return True
        return False

    async def handle_callback(
        self,
        *,
        user_id: int,
        chat_id: int | None,
        payload: str,
        callback_id: str | None = None,
    ) -> bool:
        if not self.is_admin(user_id):
            return False

        if payload.startswith("bindchat:"):
            await self._bind_chat_choose_location(user_id, chat_id, int(payload.split(":")[1]))
            return True
        if payload.startswith("bindloc:"):
            _, pending_id, location_id = payload.split(":")
            await self._bind_chat_confirm(user_id, chat_id, int(pending_id), int(location_id))
            return True
        if payload.startswith("bindtr:"):
            await self._bind_trainer_choose_location(user_id, chat_id, int(payload.split(":")[1]))
            return True
        if payload.startswith("bindtrloc:"):
            _, trainer_id, location_id = payload.split(":")
            await self._bind_trainer_choose_weekdays(
                user_id, chat_id, int(trainer_id), int(location_id)
            )
            return True
        if payload.startswith("wd:"):
            await self._bind_trainer_toggle_weekday(user_id, chat_id, payload.removeprefix("wd:"))
            return True
        if payload.startswith("dayoff_tr:"):
            trainer_key = payload.split(":")[1]
            trainer_id = None if trainer_key == "all" else int(trainer_key)
            await self._day_off_choose_locations(user_id, chat_id, trainer_id)
            return True
        if payload.startswith("dayoff_loc:"):
            await self._day_off_toggle_location(user_id, chat_id, payload.removeprefix("dayoff_loc:"))
            return True
        if payload.startswith("dayoff_confirm:"):
            await self._day_off_confirm(user_id, chat_id, payload.removeprefix("dayoff_confirm:"))
            return True
        return False

    async def _continue_text_fsm(self, user_id: int, text: str, state: dict[str, Any]) -> bool:
        return False

    async def _reply(
        self,
        user_id: int,
        chat_id: int | None,
        text: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> None:
        # Админ-команды всегда отвечаем в личку по user_id.
        # chat_id диалога MAX часто нельзя использовать как chat_id группового чата.
        await self.max_client.send_message_to_user(
            user_id,
            text,
            format=None,
            attachments=attachments,
        )

    async def _start_bind_chat(self, user_id: int, chat_id: int | None) -> None:
        result = await self.session.execute(
            select(PendingMaxChat).order_by(PendingMaxChat.added_at.desc())
        )
        pending_chats = list(result.scalars().all())
        if not pending_chats:
            await self._reply(user_id, chat_id, "Непривязанных чатов нет.")
            return
        rows = [[(chat.title[:60], f"bindchat:{chat.id}")] for chat in pending_chats]
        self.fsm_storage[user_id] = {"flow": "bind_chat"}
        await self._reply(
            user_id,
            chat_id,
            "Выберите MAX-чат:",
            attachments=build_inline_keyboard(rows),
        )

    async def _bind_chat_choose_location(
        self, user_id: int, chat_id: int | None, pending_id: int
    ) -> None:
        result = await self.session.execute(
            select(Location).where(Location.max_chat_id.is_(None)).order_by(Location.name)
        )
        locations = list(result.scalars().all())
        if not locations:
            self.fsm_storage.pop(user_id, None)
            await self._reply(user_id, chat_id, "Все локации уже привязаны к чатам.")
            return
        rows = [
            [(location.name, f"bindloc:{pending_id}:{location.id}")] for location in locations
        ]
        self.fsm_storage[user_id] = {"flow": "bind_chat", "pending_id": pending_id}
        await self._reply(
            user_id,
            chat_id,
            "Выберите локацию:",
            attachments=build_inline_keyboard(rows),
        )

    async def _bind_chat_confirm(
        self,
        user_id: int,
        chat_id: int | None,
        pending_id: int,
        location_id: int,
    ) -> None:
        pending_result = await self.session.execute(
            select(PendingMaxChat).where(PendingMaxChat.id == pending_id)
        )
        pending_chat = pending_result.scalar_one_or_none()
        location_result = await self.session.execute(
            select(Location).where(Location.id == location_id)
        )
        location = location_result.scalar_one_or_none()
        if pending_chat is None or location is None:
            await self._reply(user_id, chat_id, "Чат или локация не найдены.")
            self.fsm_storage.pop(user_id, None)
            return
        location.max_chat_id = pending_chat.max_chat_id
        await self.session.execute(delete(PendingMaxChat).where(PendingMaxChat.id == pending_id))
        await self.session.commit()
        self.fsm_storage.pop(user_id, None)
        await self._reply(
            user_id,
            chat_id,
            f"Чат «{pending_chat.title}» привязан к {location.name}.",
        )

    async def _start_bind_trainer(self, user_id: int, chat_id: int | None) -> None:
        result = await self.session.execute(select(Trainer).where(Trainer.is_active.is_(True)))
        trainers = list(result.scalars().all())
        if not trainers:
            await self._reply(user_id, chat_id, "Тренеры не найдены.")
            return
        rows = [[(trainer.name, f"bindtr:{trainer.id}")] for trainer in trainers]
        self.fsm_storage[user_id] = {"flow": "bind_trainer"}
        await self._reply(
            user_id,
            chat_id,
            "Выберите тренера:",
            attachments=build_inline_keyboard(rows),
        )

    async def _bind_trainer_choose_location(
        self, user_id: int, chat_id: int | None, trainer_id: int
    ) -> None:
        result = await self.session.execute(select(Location).order_by(Location.name))
        locations = list(result.scalars().all())
        if not locations:
            await self._reply(user_id, chat_id, "Локации не найдены.")
            return
        rows = [
            [(location.name, f"bindtrloc:{trainer_id}:{location.id}")]
            for location in locations
        ]
        self.fsm_storage[user_id] = {
            "flow": "bind_trainer",
            "trainer_id": trainer_id,
            "weekdays": [],
        }
        await self._reply(
            user_id,
            chat_id,
            "Выберите локацию:",
            attachments=build_inline_keyboard(rows),
        )

    async def _bind_trainer_choose_weekdays(
        self,
        user_id: int,
        chat_id: int | None,
        trainer_id: int,
        location_id: int,
    ) -> None:
        self.fsm_storage[user_id] = {
            "flow": "bind_trainer",
            "trainer_id": trainer_id,
            "location_id": location_id,
            "weekdays": [],
        }
        await self._reply(
            user_id,
            chat_id,
            "Выберите дни недели:",
            attachments=self._weekdays_attachments([]),
        )

    async def _bind_trainer_toggle_weekday(
        self, user_id: int, chat_id: int | None, action: str
    ) -> None:
        state = self.fsm_storage.get(user_id) or {}
        weekdays = list(state.get("weekdays", []))
        if action == "save":
            if not weekdays:
                await self._reply(user_id, chat_id, "Выберите хотя бы один день.")
                return
            await self._save_assignment(user_id, chat_id, state, weekdays)
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
        state["weekdays"] = weekdays
        self.fsm_storage[user_id] = state
        await self._reply(
            user_id,
            chat_id,
            "Выберите дни недели:",
            attachments=self._weekdays_attachments(weekdays),
        )

    async def _save_assignment(
        self,
        user_id: int,
        chat_id: int | None,
        state: dict[str, Any],
        weekdays: list[int],
    ) -> None:
        trainer_id = int(state["trainer_id"])
        location_id = int(state["location_id"])
        weekdays = sorted(weekdays)
        result = await self.session.execute(
            select(TrainerAssignment).where(
                TrainerAssignment.trainer_id == trainer_id,
                TrainerAssignment.location_id == location_id,
            )
        )
        assignment = result.scalar_one_or_none()
        if assignment is None:
            self.session.add(
                TrainerAssignment(
                    trainer_id=trainer_id,
                    location_id=location_id,
                    weekdays=weekdays,
                )
            )
        else:
            assignment.weekdays = weekdays
            assignment.is_active = True
        trainer = (
            await self.session.execute(select(Trainer).where(Trainer.id == trainer_id))
        ).scalar_one()
        location = (
            await self.session.execute(select(Location).where(Location.id == location_id))
        ).scalar_one()
        await self.session.commit()
        self.fsm_storage.pop(user_id, None)
        await self._reply(
            user_id,
            chat_id,
            f"Сохранено: {trainer.name} → {location.name} ({format_weekdays(weekdays)})",
        )

    def _weekdays_attachments(self, selected: list[int]) -> list[dict[str, Any]]:
        def label(day: int, title: str) -> str:
            return f"✅ {title}" if day in selected else title

        rows = [
            [
                (label(0, "Пн"), "wd:0"),
                (label(1, "Вт"), "wd:1"),
                (label(2, "Ср"), "wd:2"),
                (label(3, "Чт"), "wd:3"),
            ],
            [("Пн+Ср", "wd:preset_mw"), ("Вт+Чт", "wd:preset_tt")],
            [("✅ Сохранить", "wd:save")],
        ]
        return build_inline_keyboard(rows)

    async def _start_day_off(self, user_id: int, chat_id: int | None) -> None:
        result = await self.session.execute(select(Trainer).where(Trainer.is_active.is_(True)))
        trainers = list(result.scalars().all())
        rows = [[(trainer.name, f"dayoff_tr:{trainer.id}")] for trainer in trainers]
        rows.append([("👥 Все тренеры", "dayoff_tr:all")])
        self.fsm_storage[user_id] = {"flow": "day_off"}
        await self._reply(
            user_id,
            chat_id,
            "Кто сегодня не работает?",
            attachments=build_inline_keyboard(rows),
        )

    async def _day_off_choose_locations(
        self,
        user_id: int,
        chat_id: int | None,
        trainer_id: int | None,
    ) -> None:
        report_service = ReportService(self.session, self.settings)
        expected = await report_service.get_expected_reports(date.today())
        if trainer_id is not None:
            expected = [item for item in expected if item.trainer.id == trainer_id]
        if not expected:
            self.fsm_storage.pop(user_id, None)
            await self._reply(
                user_id,
                chat_id,
                "На сегодня нет рабочих локаций для выбранного тренера.",
            )
            return
        location_options = {item.location.id: item.location.name for item in expected}
        self.fsm_storage[user_id] = {
            "flow": "day_off",
            "trainer_id": trainer_id,
            "location_options": location_options,
            "selected_location_ids": [],
        }
        await self._reply(
            user_id,
            chat_id,
            "Выберите локации:",
            attachments=self._day_off_locations_attachments(location_options, []),
        )

    async def _day_off_toggle_location(
        self, user_id: int, chat_id: int | None, action: str
    ) -> None:
        state = self.fsm_storage.get(user_id) or {}
        location_options = {
            int(key): value for key, value in (state.get("location_options") or {}).items()
        }
        selected = list(state.get("selected_location_ids", []))
        if action == "all":
            selected = list(location_options.keys())
        elif action == "back":
            await self._start_day_off(user_id, chat_id)
            return
        elif action == "done":
            if not selected:
                await self._reply(user_id, chat_id, "Выберите хотя бы одну локацию.")
                return
            names = [location_options[location_id] for location_id in selected]
            trainer_id = state.get("trainer_id")
            if trainer_id is None:
                trainer_label = "Все тренеры"
            else:
                trainer = (
                    await self.session.execute(select(Trainer).where(Trainer.id == trainer_id))
                ).scalar_one()
                trainer_label = trainer.name
            state["selected_location_ids"] = selected
            self.fsm_storage[user_id] = state
            rows = [
                [("✅ Подтвердить", "dayoff_confirm:yes")],
                [("❌ Отмена", "dayoff_confirm:no")],
            ]
            await self._reply(
                user_id,
                chat_id,
                f"Отменить рабочий день?\n{trainer_label} — {', '.join(names)}",
                attachments=build_inline_keyboard(rows),
            )
            return
        else:
            location_id = int(action)
            if location_id in selected:
                selected.remove(location_id)
            else:
                selected.append(location_id)
        state["selected_location_ids"] = selected
        self.fsm_storage[user_id] = state
        await self._reply(
            user_id,
            chat_id,
            "Выберите локации:",
            attachments=self._day_off_locations_attachments(location_options, selected),
        )

    async def _day_off_confirm(
        self, user_id: int, chat_id: int | None, action: str
    ) -> None:
        if action != "yes":
            self.fsm_storage.pop(user_id, None)
            await self._reply(user_id, chat_id, "Отмена.")
            return
        state = self.fsm_storage.get(user_id) or {}
        trainer_id = state.get("trainer_id")
        selected = list(state.get("selected_location_ids", []))
        report_service = ReportService(self.session, self.settings)
        affected = await report_service.mark_excused(
            report_date=date.today(),
            trainer_id=trainer_id,
            location_ids=selected,
            created_by=user_id,
        )
        self.fsm_storage.pop(user_id, None)
        await self._reply(
            user_id,
            chat_id,
            f"Рабочий день отменён для локаций: {len(affected)}",
        )

    def _day_off_locations_attachments(
        self,
        location_options: dict[int, str],
        selected: list[int],
    ) -> list[dict[str, Any]]:
        rows: list[list[tuple[str, str]]] = []
        for location_id, name in location_options.items():
            prefix = "✅ " if location_id in selected else ""
            rows.append([(f"{prefix}{name}", f"dayoff_loc:{location_id}")])
        rows.append([("✅ Все локации", "dayoff_loc:all")])
        rows.append([("◀️ Назад", "dayoff_loc:back")])
        rows.append([("✅ Готово", "dayoff_loc:done")])
        return build_inline_keyboard(rows)
