"""Client for the free elprisetjustnu.se day-ahead price API.

Endpoint: https://www.elprisetjustnu.se/api/v1/prices/{YYYY}/{MM}-{DD}_{AREA}.json
- Hourly rows until 2025-09-30, 15-minute rows from 2025-10-01.
- Tomorrow's prices are published at the earliest 13:00 Europe/Stockholm the day before;
  before that the endpoint answers 404, which we treat as "not published yet", not an error.
- No published rate limit. We are polite anyway: one request at a time, a pause between
  requests, a descriptive User-Agent and bounded retries with backoff.
See docs/data-sources.md.

This module must stay self-contained (stdlib + httpx + pydantic, no imports from the
elkollen_ingest package): Terraform also ships it, unchanged, as the body of the
Snowflake stored procedure RAW.INGEST_PRICES (see snowflake_proc.py). For the same
reason there is no `from __future__ import annotations`: dataclasses would then look
the module up in sys.modules, which a bare procedure body is not guaranteed to be in.
"""

import logging
import math
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

log = logging.getLogger(__name__)

AREAS: tuple[str, ...] = ("SE1", "SE2", "SE3", "SE4")
BASE_URL = "https://www.elprisetjustnu.se/api/v1/prices"
DEFAULT_USER_AGENT = "elkollen/0.1 (portfolio project; contact via GitHub repository)"
FIRST_AVAILABLE_DAY = date(2022, 11, 1)  # earliest day the API serves


class PricePoint(BaseModel):
    """One row as returned by the API. Field names mirror the source exactly."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sek_per_kwh: float = Field(alias="SEK_per_kWh")
    eur_per_kwh: float = Field(alias="EUR_per_kWh")
    exr: float = Field(alias="EXR", gt=0)
    time_start: str
    time_end: str

    @field_validator("sek_per_kwh", "eur_per_kwh")
    @classmethod
    def finite(cls, v: float) -> float:
        # Negative prices are real (surplus wind/hydro) and must pass. NaN/inf must not.
        if not math.isfinite(v):
            raise ValueError("price must be a finite number")
        return v

    @field_validator("time_start", "time_end")
    @classmethod
    def has_offset(cls, v: str) -> str:
        parsed = datetime.fromisoformat(v)
        if parsed.utcoffset() is None:
            raise ValueError(f"timestamp without UTC offset: {v!r}")
        return v


class DayValidationError(ValueError):
    """The API answered, but the payload for a day is not internally consistent."""


@dataclass(frozen=True)
class DayPrices:
    area: str
    delivery_date: date
    source_url: str
    points: tuple[PricePoint, ...]
    interval_minutes: int
    # Rows whose declared time_end disagrees with start + resolution (see parse_day).
    end_mismatches: tuple[str, ...] = ()


def day_url(area: str, day: date) -> str:
    return f"{BASE_URL}/{day:%Y}/{day:%m-%d}_{area}.json"


def parse_day(area: str, day: date, url: str, payload: object) -> DayPrices:
    """Validate a raw JSON payload for one area and day. Raises DayValidationError.

    The interval *starts* are the source of truth. Known source quirk: on the autumn
    clock-change day the last interval before the change declares its end in the new
    offset (e.g. 02:45+02:00 -> 03:00+01:00), which is one hour too late. We therefore
    derive the day's resolution from the starts, check that the starts are contiguous,
    and only report (not reject) declared ends that disagree. RAW keeps the values as
    received; staging recomputes interval_end from start + resolution.
    """
    if not isinstance(payload, list) or not payload:
        raise DayValidationError(f"{area} {day}: expected a non-empty JSON list")

    points = tuple(PricePoint.model_validate(item) for item in payload)
    starts = [datetime.fromisoformat(p.time_start) for p in points]
    ends = [datetime.fromisoformat(p.time_end) for p in points]

    durations = {int((e - s).total_seconds() // 60) for s, e in zip(starts, ends, strict=True)}
    if min(durations) <= 0:
        raise DayValidationError(f"{area} {day}: an interval ends before it starts")
    resolution = min(durations)
    if resolution not in (15, 60):
        raise DayValidationError(f"{area} {day}: unknown resolution {resolution} min")

    step = timedelta(minutes=resolution)
    for s in starts:
        if s.date() != day:
            raise DayValidationError(f"{area} {day}: row starts on {s.date()}")
    for prev, cur in zip(starts, starts[1:], strict=False):
        if cur - prev != step:
            raise DayValidationError(
                f"{area} {day}: starts not contiguous at {cur.isoformat()} "
                f"(expected step {resolution} min)"
            )

    mismatches = tuple(
        p.time_start for p, s, e in zip(points, starts, ends, strict=True) if e - s != step
    )
    if mismatches:
        log.warning(
            "%s %s: %d row(s) with declared end != start + %s min (kept as received): %s",
            area,
            day,
            len(mismatches),
            resolution,
            ", ".join(mismatches),
        )

    return DayPrices(
        area=area,
        delivery_date=day,
        source_url=url,
        points=points,
        interval_minutes=resolution,
        end_mismatches=mismatches,
    )


class ElprisClient:
    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        pause_seconds: float = 0.25,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
        sleep=time.sleep,
    ) -> None:
        self._http = httpx.Client(
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            timeout=httpx.Timeout(15.0),
            transport=transport,
        )
        self._pause = pause_seconds
        self._max_retries = max_retries
        self._sleep = sleep

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "ElprisClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def fetch_raw(self, area: str, day: date) -> tuple[str, object | None]:
        """Return (url, parsed JSON) or (url, None) if the day is not published (404)."""
        if area not in AREAS:
            raise ValueError(f"unknown price area {area!r}; expected one of {AREAS}")
        if day < FIRST_AVAILABLE_DAY:
            raise ValueError(
                f"{day} is before the first day the API serves ({FIRST_AVAILABLE_DAY})"
            )

        url = day_url(area, day)
        for attempt in range(self._max_retries + 1):
            response = self._http.get(url)
            if response.status_code == 404:
                return url, None
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == self._max_retries:
                    response.raise_for_status()
                backoff = 2**attempt
                log.warning("HTTP %s for %s, retrying in %ss", response.status_code, url, backoff)
                self._sleep(backoff)
                continue
            response.raise_for_status()
            self._sleep(self._pause)
            return url, response.json()
        raise AssertionError("unreachable")  # pragma: no cover

    def fetch_day(self, area: str, day: date) -> DayPrices | None:
        url, payload = self.fetch_raw(area, day)
        if payload is None:
            return None
        return parse_day(area, day, url, payload)
