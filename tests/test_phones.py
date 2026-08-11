from app.db.enums import PhoneSource
from app.services.phones import normalize_phone, parse_phones_from_report_text


def test_normalize_phone_variants() -> None:
    assert normalize_phone("+7 (999) 123-45-67") == "79991234567"
    assert normalize_phone("8 999 123 45 67") == "79991234567"
    assert normalize_phone("9991234567") == "79991234567"
    assert normalize_phone("12345") is None


def test_parse_phones_from_blocks_only() -> None:
    text = """
Сегодня тренировка
Сад 174
Лишний номер вне блока: +7 900 000-00-00
С пробного:
+7 999 111-22-33
8 (888) 222-33-44
С общения:
+7 977 555-66-77
"""
    phones = parse_phones_from_report_text(text)
    assert [(item.phone_normalized, item.source) for item in phones] == [
        ("79991112233", PhoneSource.TRIAL),
        ("78882223344", PhoneSource.TRIAL),
        ("79775556677", PhoneSource.OUTREACH),
    ]


def test_parse_phones_ignores_text_without_headers() -> None:
    text = "Сегодня тренировка\n+7 999 111-22-33"
    assert parse_phones_from_report_text(text) == []


def test_parse_phones_deduplicates_within_source() -> None:
    text = """
С пробного:
9991112233
+7 999 111 22 33
"""
    phones = parse_phones_from_report_text(text)
    assert len(phones) == 1
    assert phones[0].phone_normalized == "79991112233"
