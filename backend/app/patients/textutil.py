"""Dates and small-cell display."""

from __future__ import annotations

from datetime import date, datetime


def parse_iso(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def fmt_date(value: date | str | None) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        parsed = parse_iso(value)
        if parsed is None:
            return value
        value = parsed
    return f"{value.day} {value.strftime('%b')} {value.year}"


def age_band(birth_year: int | None, as_of: date | None) -> str:
    if not birth_year or not as_of:
        return ""
    age = as_of.year - int(birth_year)
    start = (age // 10) * 10
    return f"{start}–{start + 9}"


def age_band_short(birth_year: int | None, as_of: date | None) -> str:
    if not birth_year or not as_of:
        return ""
    age = as_of.year - int(birth_year)
    return f"{(age // 10) * 10}s"


def suppress_count(count: int, minimum: int) -> int | str:
    if minimum > 0 and count < minimum:
        return "<11"
    return count
