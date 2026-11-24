"""Client and parser for the ENTSO-E Transparency Platform (day-ahead grid forecasts).

Two documents per price area and period:
- Load forecast: documentType A65, processType A01 (day ahead), one series.
- Wind and solar forecast: documentType A69, processType A01, one series per
  production type (B16 solar, B18 wind offshore, B19 wind onshore).

What the API does that the parser must handle (seen in live responses, 2026-11-24):
- Curve type A03: a point that repeats the previous value is left out, so a 96-quarter
  day can arrive with 95 points. Missing positions take the previous value.
- Resolution changes over time: the Swedish load forecast is hourly (PT60M) in 2024 and
  2025 and 15-minute (PT15M) later. Rows keep their native resolution; dbt puts them on
  the 15-minute grain.
- "No data" is an Acknowledgement document, not an empty result.

The security token is read from ENTSOE_API_TOKEN by the caller and only ever sent to
the API. It never appears in logs or exceptions: httpx errors carry the request URL
(which contains the token), so they are replaced by messages without it.
Rate limit (ENTSO-E help centre): 400 requests per minute per token. We pause between
requests and stay far below it. See docs/data-sources.md.
"""

import logging
import math
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger(__name__)

API_URL = "https://web-api.tp.entsoe.eu/api"
STOCKHOLM = ZoneInfo("Europe/Stockholm")

# Energy Identification Codes of the Swedish bidding zones.
AREA_EIC: dict[str, str] = {
    "SE1": "10Y1001A1001A44P",
    "SE2": "10Y1001A1001A45N",
    "SE3": "10Y1001A1001A46L",
    "SE4": "10Y1001A1001A47J",
}
PSR_SERIES = {
    "B16": "solar_forecast",
    "B18": "wind_offshore_forecast",
    "B19": "wind_onshore_forecast",
}
SERIES = ("load_forecast", *PSR_SERIES.values())
RESOLUTION_MINUTES = {"PT15M": 15, "PT30M": 30, "PT60M": 60}
MAX_MW = 100_000  # far above any Swedish zone; catches unit or parsing errors


class EntsoeError(RuntimeError):
    """A request or document the pipeline refuses. Never contains the token."""


@dataclass(frozen=True)
class GridPoint:
    area: str
    series: str
    start_utc: datetime  # naive UTC
    resolution_minutes: int
    mw: float
    document_type: str

    @property
    def start_local(self) -> datetime:
        return self.start_utc.replace(tzinfo=UTC).astimezone(STOCKHOLM).replace(tzinfo=None)

    @property
    def delivery_date(self) -> date:
        return self.start_local.date()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el: ET.Element, name: str) -> ET.Element | None:
    return next((c for c in el if _local(c.tag) == name), None)


def _text(el: ET.Element, name: str) -> str | None:
    found = next((c for c in el.iter() if _local(c.tag) == name), None)
    return found.text.strip() if found is not None and found.text else None


def _utc(value: str) -> datetime:
    # The API writes "2026-11-22T23:00Z" (no seconds).
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC).replace(tzinfo=None)


def parse_document(area: str, xml: str | bytes) -> list[GridPoint]:
    """All points in one ENTSO-E document, with A03 gaps filled. An Acknowledgement
    ("no matching data") gives an empty list; anything malformed raises EntsoeError."""
    try:
        root = ET.fromstring(xml)  # noqa: S314 - response from the official API over HTTPS
    except ET.ParseError as exc:
        raise EntsoeError(f"response is not XML: {exc}") from None
    kind = _local(root.tag)
    if kind == "Acknowledgement_MarketDocument":
        return []
    if kind != "GL_MarketDocument":
        raise EntsoeError(f"unexpected document {kind}")
    doc_type = (_child(root, "type").text or "").strip() if _child(root, "type") is not None else ""
    if doc_type not in ("A65", "A69"):
        raise EntsoeError(f"unexpected document type {doc_type!r}")

    points: list[GridPoint] = []
    for ts in (c for c in root if _local(c.tag) == "TimeSeries"):
        if doc_type == "A65":
            series = "load_forecast"
        else:
            psr = _text(ts, "psrType")
            if psr not in PSR_SERIES:
                continue  # a production type we do not use
            series = PSR_SERIES[psr]
        if (_text(ts, "quantity_Measure_Unit.name") or "MAW") != "MAW":
            raise EntsoeError("expected quantities in MW (MAW)")
        curve = _text(ts, "curveType") or "A01"
        for period in (c for c in ts if _local(c.tag) == "Period"):
            interval = _child(period, "timeInterval")
            resolution = _text(period, "resolution")
            if interval is None or resolution not in RESOLUTION_MINUTES:
                raise EntsoeError(f"period without interval or with resolution {resolution!r}")
            start = _utc(_text(interval, "start") or "")
            end = _utc(_text(interval, "end") or "")
            step = RESOLUTION_MINUTES[resolution]
            n = int((end - start).total_seconds() // 60 // step)
            given: dict[int, float] = {}
            for p in (c for c in period if _local(c.tag) == "Point"):
                pos = int(_text(p, "position") or 0)
                qty = float(_text(p, "quantity") or "nan")
                if not 1 <= pos <= n:
                    raise EntsoeError(f"position {pos} outside 1..{n}")
                if not math.isfinite(qty) or not 0 <= qty <= MAX_MW:
                    raise EntsoeError(f"implausible quantity {qty} MW")
                given[pos] = qty
            if 1 not in given:
                raise EntsoeError("period does not start with position 1")
            last = given[1]
            for pos in range(1, n + 1):
                if pos in given:
                    last = given[pos]
                elif curve != "A03":
                    raise EntsoeError(f"position {pos} missing in a curve type {curve} series")
                points.append(
                    GridPoint(
                        area=area,
                        series=series,
                        start_utc=start + timedelta(minutes=step * (pos - 1)),
                        resolution_minutes=step,
                        mw=last,
                        document_type=doc_type,
                    )
                )
    return points


def local_day_bounds(first: date, last: date) -> tuple[datetime, datetime]:
    """UTC start and end of local Stockholm days first..last (inclusive)."""
    start = datetime.combine(first, datetime.min.time(), STOCKHOLM).astimezone(UTC)
    end = datetime.combine(last + timedelta(days=1), datetime.min.time(), STOCKHOLM)
    return start.replace(tzinfo=None), end.astimezone(UTC).replace(tzinfo=None)


class EntsoeClient:
    def __init__(
        self, token: str, pause_s: float = 0.25, retries: int = 3, timeout_s: float = 60
    ) -> None:
        if not token:
            raise EntsoeError("ENTSOE_API_TOKEN is not set (see .env.example)")
        self._token = token
        self._pause = pause_s
        self._retries = retries
        self._http = httpx.Client(timeout=timeout_s)

    def __enter__(self) -> "EntsoeClient":
        return self

    def __exit__(self, *exc) -> None:
        self._http.close()

    def _get(self, params: dict[str, str]) -> str:
        what = f"{params['documentType']} {params['periodStart']}-{params['periodEnd']}"
        error = "no attempt"
        for attempt in range(self._retries + 1):
            time.sleep(self._pause)
            try:
                response = self._http.get(API_URL, params={**params, "securityToken": self._token})
            except httpx.HTTPError as exc:
                # The exception text includes the URL and thus the token: drop it.
                error = f"network error ({type(exc).__name__})"
            else:
                if response.status_code == 200:
                    return response.text
                if response.status_code == 400 and "Acknowledgement" in response.text:
                    return response.text  # "no matching data": the parser returns []
                if response.status_code in (401, 403):
                    raise EntsoeError(f"token refused (HTTP {response.status_code})")
                error = f"HTTP {response.status_code}"
                if response.status_code not in (429, 500, 502, 503, 504):
                    raise EntsoeError(f"{what}: {error}")
            if attempt < self._retries:
                time.sleep(2**attempt * 5)
        raise EntsoeError(f"{what}: {error} after {self._retries} retries")

    def fetch(self, area: str, first: date, last: date) -> list[GridPoint]:
        """Load, wind and solar forecasts for local days first..last (at most 31 days)."""
        if area not in AREA_EIC:
            raise EntsoeError(f"unknown area {area!r}")
        if last < first or (last - first).days > 30:
            raise EntsoeError("ask for 1 to 31 days at a time")
        start, end = local_day_bounds(first, last)
        period = {
            "periodStart": start.strftime("%Y%m%d%H%M"),
            "periodEnd": end.strftime("%Y%m%d%H%M"),
        }
        eic = AREA_EIC[area]
        load = self._get(
            {"documentType": "A65", "processType": "A01", "outBiddingZone_Domain": eic, **period}
        )
        gen = self._get({"documentType": "A69", "processType": "A01", "in_Domain": eic, **period})
        points = parse_document(area, load) + parse_document(area, gen)
        return [p for p in points if start <= p.start_utc < end]
