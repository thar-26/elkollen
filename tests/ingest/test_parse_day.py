import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from elkollen_ingest.elpris import DayValidationError, parse_day

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "elpris"


def load(day: str, area: str):
    payload = json.loads((FIXTURES / f"{day}_{area}.json").read_text(encoding="utf-8"))
    return parse_day(area, date.fromisoformat(day), "fixture", payload)


@pytest.mark.parametrize(
    ("day", "rows", "resolution"),
    [
        ("2025-09-30", 24, 60),  # last hourly day
        ("2025-03-30", 23, 60),  # spring forward, hourly era
        ("2024-10-27", 25, 60),  # fall back, hourly era
        ("2025-10-01", 96, 15),  # first 15-minute day
        ("2025-10-26", 100, 15),  # fall back, 15-minute era
        ("2026-03-29", 92, 15),  # spring forward, 15-minute era
    ],
)
@pytest.mark.parametrize("area", ["SE1", "SE2", "SE3", "SE4"])
def test_real_days_have_expected_interval_counts(day, rows, resolution, area):
    prices = load(day, area)
    assert len(prices.points) == rows
    assert prices.interval_minutes == resolution


@pytest.mark.parametrize("day", ["2025-10-26", "2024-10-27"])
def test_fall_back_end_quirk_is_reported_not_rejected(day):
    prices = load(day, "SE3")
    assert len(prices.end_mismatches) == 1


def test_normal_day_has_no_end_mismatches():
    assert load("2025-10-01", "SE3").end_mismatches == ()


def test_negative_prices_are_accepted():
    prices = load("2025-10-04", "SE4")
    assert min(p.sek_per_kwh for p in prices.points) < 0


def _row(start: str, end: str, price: float = 0.5) -> dict:
    return {
        "SEK_per_kWh": price,
        "EUR_per_kWh": price / 11,
        "EXR": 11.0,
        "time_start": start,
        "time_end": end,
    }


def test_gap_in_starts_is_rejected():
    payload = [
        _row("2025-10-01T00:00:00+02:00", "2025-10-01T00:15:00+02:00"),
        _row("2025-10-01T00:30:00+02:00", "2025-10-01T00:45:00+02:00"),
    ]
    with pytest.raises(DayValidationError, match="not contiguous"):
        parse_day("SE3", date(2025, 10, 1), "x", payload)


def test_row_for_another_day_is_rejected():
    payload = [_row("2025-10-02T00:00:00+02:00", "2025-10-02T00:15:00+02:00")]
    with pytest.raises(DayValidationError, match="starts on"):
        parse_day("SE3", date(2025, 10, 1), "x", payload)


def test_unknown_resolution_is_rejected():
    payload = [_row("2025-10-01T00:00:00+02:00", "2025-10-01T00:30:00+02:00")]
    with pytest.raises(DayValidationError, match="resolution"):
        parse_day("SE3", date(2025, 10, 1), "x", payload)


def test_empty_payload_is_rejected():
    with pytest.raises(DayValidationError):
        parse_day("SE3", date(2025, 10, 1), "x", [])


def test_nan_price_is_rejected():
    payload = [_row("2025-10-01T00:00:00+02:00", "2025-10-01T00:15:00+02:00", float("nan"))]
    with pytest.raises(ValidationError):
        parse_day("SE3", date(2025, 10, 1), "x", payload)


def test_timestamp_without_offset_is_rejected():
    payload = [_row("2025-10-01T00:00:00", "2025-10-01T00:15:00")]
    with pytest.raises(ValidationError, match="offset"):
        parse_day("SE3", date(2025, 10, 1), "x", payload)


def test_unexpected_field_is_rejected():
    row = _row("2025-10-01T00:00:00+02:00", "2025-10-01T00:15:00+02:00")
    row["surprise"] = 1
    with pytest.raises(ValidationError):
        parse_day("SE3", date(2025, 10, 1), "x", [row])
