"""Synthetic users and 15-minute consumption for the public demo and the tests.

Nothing here is real: the people, addresses and meter numbers are invented, and the
profiles are simple shapes (base load, morning and evening peaks, winter heating, night
EV charging). The public demo never holds real meter data.

Readings are generated per *local* Stockholm day, so a day has 96 quarter-hours, 92 on
the spring clock-change day and 100 on the autumn one, exactly like the prices.
"""

import random
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

STOCKHOLM = ZoneInfo("Europe/Stockholm")
QUARTER = timedelta(minutes=15)


@dataclass(frozen=True)
class SyntheticUser:
    user_id: str
    display_name: str
    price_area: str
    meter_id: str  # fake: real Swedish meter IDs start 735999 and have 18 digits
    address: str  # invented
    profile: str  # "apartment" or "house_ev"


DEMO_USERS: tuple[SyntheticUser, ...] = (
    SyntheticUser(
        "demo-anna",
        "Anna (demo)",
        "SE3",
        "735999000000000101",
        "Exempelgatan 1, 111 22 Stockholm",
        "apartment",
    ),
    SyntheticUser(
        "demo-erik",
        "Erik (demo)",
        "SE4",
        "735999000000000202",
        "Provvägen 7, 211 33 Malmö",
        "house_ev",
    ),
)


def quarter_hours_utc(day: date) -> list[datetime]:
    """UTC starts (naive) of every quarter-hour in the Stockholm local day."""
    start = datetime(day.year, day.month, day.day, tzinfo=STOCKHOLM).astimezone(UTC)
    nxt = day + timedelta(days=1)
    end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=STOCKHOLM).astimezone(UTC)
    out = []
    t = start
    while t < end:
        out.append(t.replace(tzinfo=None))
        t += QUARTER
    return out


def kwh(profile: str, local: datetime, rng: random.Random) -> float:
    """Energy used in one quarter-hour, in kWh."""
    winter = local.month in (11, 12, 1, 2, 3)
    hour = local.hour
    if profile == "apartment":
        load = 0.06 * (1.3 if winter else 1.0)
        if 7 <= hour < 9:
            load += 0.10
        if 17 <= hour < 22:
            load += 0.15
    elif profile == "house_ev":
        load = 0.25 * (1.8 if winter else 1.0)  # heat pump
        if 17 <= hour < 21:
            load += 0.30
        if local.weekday() < 5 and (hour >= 23 or hour < 3):
            load += 2.2  # about 8.8 kW EV charging on weeknights
    else:
        raise ValueError(f"unknown profile {profile!r}")
    return round(load * rng.uniform(0.85, 1.15), 3)  # noqa: S311 - not security related


def user_rows(run_id: str, loaded_at: datetime, users=DEMO_USERS) -> list[tuple]:
    created = datetime(2026, 1, 1)  # noqa: DTZ001 - naive UTC by convention in RAW
    return [
        (
            u.user_id,
            u.display_name,
            u.price_area,
            u.meter_id,
            u.address,
            "active",
            True,
            created,
            run_id,
            loaded_at,
        )
        for u in users
    ]


def consumption_rows(
    start: date, end: date, run_id: str, loaded_at: datetime, users=DEMO_USERS
) -> Iterator[tuple]:
    day = start
    while day <= end:
        for u in users:
            rng = random.Random(f"{u.user_id}:{day.isoformat()}")  # noqa: S311 - deterministic demo data
            for t in quarter_hours_utc(day):
                local = t.replace(tzinfo=UTC).astimezone(STOCKHOLM)
                yield (
                    u.user_id,
                    u.meter_id,
                    t,
                    15,
                    kwh(u.profile, local, rng),
                    "synthetic",
                    run_id,
                    loaded_at,
                )
        day += timedelta(days=1)
