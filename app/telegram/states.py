from aiogram.fsm.state import State, StatesGroup


class BindChatStates(StatesGroup):
    choosing_chat = State()
    choosing_location = State()


class BindTrainerStates(StatesGroup):
    choosing_trainer = State()
    choosing_location = State()
    choosing_weekdays = State()


class DayOffStates(StatesGroup):
    choosing_trainer = State()
    choosing_locations = State()
    confirming = State()
