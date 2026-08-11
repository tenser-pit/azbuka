import asyncio
import logging

from sqlalchemy import select

from app.config import get_settings
from app.db.enums import LocationType
from app.db.models import Location, Trainer, TrainerAssignment
from app.db.session import async_session_factory

WEEKDAYS_MON_WED = [0, 2]
WEEKDAYS_TUE_THU = [1, 3]

SEED_TRAINERS = [
    {"name": "Соня", "max_user_id": 1001},
    {"name": "Аркадий", "max_user_id": 1002},
    {"name": "Милана", "max_user_id": 1003},
]

SEED_LOCATIONS = [
    (174, LocationType.KINDERGARTEN),
    (74, LocationType.KINDERGARTEN),
    (158, LocationType.KINDERGARTEN),
    (191, LocationType.KINDERGARTEN),
    (97, LocationType.KINDERGARTEN),
    (8, LocationType.KINDERGARTEN),
    (93, LocationType.KINDERGARTEN),
    (161, LocationType.KINDERGARTEN),
    (55, LocationType.KINDERGARTEN),
    (135, LocationType.KINDERGARTEN),
    (94, LocationType.SCHOOL),
    (132, LocationType.KINDERGARTEN),
    (55, LocationType.SCHOOL),
    (118, LocationType.KINDERGARTEN),
    (63, LocationType.KINDERGARTEN),
    (54, LocationType.KINDERGARTEN),
]

SEED_ASSIGNMENTS = [
    ("Соня", 174, LocationType.KINDERGARTEN, WEEKDAYS_MON_WED),
    ("Соня", 74, LocationType.KINDERGARTEN, WEEKDAYS_MON_WED),
    ("Соня", 158, LocationType.KINDERGARTEN, WEEKDAYS_MON_WED),
    ("Соня", 191, LocationType.KINDERGARTEN, WEEKDAYS_TUE_THU),
    ("Соня", 97, LocationType.KINDERGARTEN, WEEKDAYS_TUE_THU),
    ("Аркадий", 8, LocationType.KINDERGARTEN, WEEKDAYS_MON_WED),
    ("Аркадий", 93, LocationType.KINDERGARTEN, WEEKDAYS_MON_WED),
    ("Аркадий", 161, LocationType.KINDERGARTEN, WEEKDAYS_TUE_THU),
    ("Аркадий", 55, LocationType.KINDERGARTEN, WEEKDAYS_TUE_THU),
    ("Аркадий", 135, LocationType.KINDERGARTEN, WEEKDAYS_TUE_THU),
    ("Аркадий", 94, LocationType.SCHOOL, WEEKDAYS_TUE_THU),
    ("Милана", 132, LocationType.KINDERGARTEN, WEEKDAYS_MON_WED),
    ("Милана", 55, LocationType.SCHOOL, WEEKDAYS_MON_WED),
    ("Милана", 118, LocationType.KINDERGARTEN, WEEKDAYS_MON_WED),
    ("Милана", 63, LocationType.KINDERGARTEN, WEEKDAYS_TUE_THU),
    ("Милана", 54, LocationType.KINDERGARTEN, WEEKDAYS_TUE_THU),
]


def _location_name(number: int, location_type: LocationType) -> str:
    type_label = "Сад" if location_type == LocationType.KINDERGARTEN else "Школа"
    return f"{type_label} {number}"


async def run_seeds() -> None:
    settings = get_settings()
    async with async_session_factory() as session:
        existing_trainers = await session.execute(select(Trainer.id))
        if existing_trainers.first() is not None:
            print("Seed skipped: data already exists.")
            return

        trainer_by_name: dict[str, Trainer] = {}
        for trainer_data in SEED_TRAINERS:
            trainer = Trainer(
                name=trainer_data["name"],
                max_user_id=trainer_data["max_user_id"],
            )
            session.add(trainer)
            trainer_by_name[trainer.name] = trainer

        await session.flush()

        location_by_key: dict[tuple[int, LocationType], Location] = {}
        for number, location_type in SEED_LOCATIONS:
            location = Location(
                number=number,
                type=location_type,
                name=_location_name(number, location_type),
            )
            session.add(location)
            location_by_key[(number, location_type)] = location

        await session.flush()

        for trainer_name, number, location_type, weekdays in SEED_ASSIGNMENTS:
            session.add(
                TrainerAssignment(
                    trainer_id=trainer_by_name[trainer_name].id,
                    location_id=location_by_key[(number, location_type)].id,
                    weekdays=weekdays,
                )
            )

        await session.commit()
        print("Seed completed.")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_seeds())


if __name__ == "__main__":
    main()
