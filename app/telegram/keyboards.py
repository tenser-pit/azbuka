from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

WEEKDAY_LABELS = {0: "Пн", 1: "Вт", 2: "Ср", 3: "Чт", 4: "Пт", 5: "Сб", 6: "Вс"}


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📊 Статус сегодня"),
                KeyboardButton(text="📋 Штрафы"),
            ],
            [
                KeyboardButton(text="🔗 Привязки"),
                KeyboardButton(text="🚫 Отменить рабочий день"),
            ],
        ],
        resize_keyboard=True,
    )


def format_weekdays(weekdays: list[int]) -> str:
    return ", ".join(WEEKDAY_LABELS[day] for day in sorted(weekdays))
