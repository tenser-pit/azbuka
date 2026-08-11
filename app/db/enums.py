import enum


class LocationType(str, enum.Enum):
    KINDERGARTEN = "сад"
    SCHOOL = "школа"


class ReportStatus(str, enum.Enum):
    SUBMITTED = "сдан"
    MISSED = "пропущен"
    EXCUSED = "отменён"


class PenaltyReason(str, enum.Enum):
    MISSED_REPORT = "нет_отчёта"
    MISSED_VIDEO = "нет_видео"


class PhoneSource(str, enum.Enum):
    TRIAL = "пробный"
    OUTREACH = "общение"
