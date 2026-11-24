"""The read-only questions Elkollen can answer. Shared by the MCP tools and the API.

Rules every function follows:
* Inputs are validated here (areas, dates, ranges, durations) and rejected with
  QueryInputError before any SQL runs.
* Per-user functions take `user_id` as their own argument. Callers pass the id of the
  *verified* signed-in user; it is never taken from tool arguments or request bodies.
  Every per-user query filters on it.
* Values are bound as parameters. The only numbers formatted into SQL are validated
  integers (row limit, window length).
* At most MAX_ROWS rows are read per query; `truncated` says when a limit was hit.
* Results carry the numbers they were computed from, so the assistant and the UI can
  show their working, and notes on what the numbers do not include.
"""

import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from elkollen_data.warehouse import Warehouse

MAX_ROWS = 2000
AREAS = ("SE1", "SE2", "SE3", "SE4")
Area = Literal["SE1", "SE2", "SE3", "SE4"]
_USER_ID = re.compile(r"^[A-Za-z0-9_.:@|+-]{1,128}$")

ENERGY_ONLY_NOTE = (
    "Spot price only: excludes VAT, energy tax, supplier markup, certificates and grid fees."
)
NO_DRIVER_DATA_NOTE = (
    "No load or wind forecast is stored for this interval, so causes are inferred from "
    "prices alone (time of day, history and price differences between areas)."
)
GRID_NOTE = (
    "Load, wind and solar are day-ahead forecasts from the ENTSO-E Transparency Platform "
    "(published by the Swedish TSO), not measurements. Weather and imports are not included."
)


class QueryInputError(ValueError):
    """A request the tools refuse before touching the warehouse."""


class Result(BaseModel):
    """Envelope returned by every query: the answer plus how it was computed."""

    tool: str
    inputs: dict[str, Any]
    data: Any
    rows_read: int
    truncated: bool = False
    sources: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- validation helpers


def check_area(area: str) -> str:
    if area not in AREAS:
        raise QueryInputError(f"unknown price area {area!r}; use one of {', '.join(AREAS)}")
    return area


def check_user_id(user_id: str) -> str:
    if not isinstance(user_id, str) or not _USER_ID.match(user_id):
        raise QueryInputError("invalid user id")
    return user_id


def check_range(start: date, end: date, max_days: int) -> None:
    if end < start:
        raise QueryInputError("end date is before start date")
    if (end - start).days + 1 > max_days:
        raise QueryInputError(f"date range too long: at most {max_days} days")


def _num(value: Any, digits: int = 4) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        value = float(value)
    return round(float(value), digits)


def _fetch(wh: Warehouse, sql: str, params: dict[str, Any]) -> tuple[list[dict], bool]:
    rows = wh.fetch(sql + f"\nlimit {MAX_ROWS + 1}", params)
    return rows[:MAX_ROWS], len(rows) > MAX_ROWS


# ---------------------------------------------------------------- public queries


def list_areas(wh: Warehouse) -> Result:
    rows, truncated = _fetch(
        wh,
        "select price_area, name_sv, name_en, reference_city "
        "from marts.dim_price_areas order by sort_order",
        {},
    )
    return Result(
        tool="list_areas",
        inputs={},
        data=rows,
        rows_read=len(rows),
        truncated=truncated,
        sources=["marts.dim_price_areas"],
    )


def get_prices(wh: Warehouse, area: str, start_date: date, end_date: date) -> Result:
    """15-minute prices for one area, max 14 delivery days."""
    check_area(area)
    check_range(start_date, end_date, 14)
    rows, truncated = _fetch(
        wh,
        """select delivery_date, interval_start_utc, interval_end_utc, interval_start_local,
                  price_ore_per_kwh, is_upsampled_from_hourly
           from marts.fct_prices_15min
           where price_area = :area and delivery_date between :start_date and :end_date
           order by interval_start_utc""",
        {"area": area, "start_date": start_date, "end_date": end_date},
    )
    prices = [_num(r["price_ore_per_kwh"]) for r in rows]
    summary = None
    if prices:
        summary = {
            "min_ore_per_kwh": min(prices),
            "avg_ore_per_kwh": _num(sum(prices) / len(prices)),
            "max_ore_per_kwh": max(prices),
            "n_intervals": len(prices),
            "n_negative": sum(p < 0 for p in prices),
            "days_with_data": len({r["delivery_date"] for r in rows}),
        }
    notes = [ENERGY_ONLY_NOTE]
    if any(r["is_upsampled_from_hourly"] for r in rows):
        notes.append("Some days were hourly at the source; each quarter shows the hourly price.")
    if not rows:
        notes.append("No prices for these days. Tomorrow's prices arrive from about 13:00.")
    return Result(
        tool="get_prices",
        inputs={"area": area, "start_date": start_date, "end_date": end_date},
        data={
            "unit": "öre/kWh",
            "summary": summary,
            "intervals": [
                {
                    "start_utc": r["interval_start_utc"],
                    "end_utc": r["interval_end_utc"],
                    "start_local": r["interval_start_local"],
                    "price_ore_per_kwh": _num(r["price_ore_per_kwh"]),
                    "upsampled_from_hourly": bool(r["is_upsampled_from_hourly"]),
                }
                for r in rows
            ],
        },
        rows_read=len(rows),
        truncated=truncated,
        sources=["marts.fct_prices_15min"],
        notes=notes,
    )


def cheapest_window(
    wh: Warehouse,
    area: str,
    day: date,
    duration_minutes: int,
    earliest_start_utc: datetime | None = None,
) -> Result:
    """Cheapest (and dearest) contiguous run of `duration_minutes` within one delivery day."""
    check_area(area)
    if (
        not isinstance(duration_minutes, int)
        or duration_minutes % 15
        or not (15 <= duration_minutes <= 720)
    ):
        raise QueryInputError("duration must be a multiple of 15 minutes, from 15 to 720")
    n = duration_minutes // 15
    frame = f"rows between current row and {n - 1} following"
    rows, truncated = _fetch(
        wh,
        f"""select interval_start_utc, interval_start_local,
                   avg(price_ore_per_kwh) over (order by interval_start_utc {frame}) as avg_ore,
                   count(*) over (order by interval_start_utc {frame}) as n_intervals,
                   max(interval_end_utc) over (order by interval_start_utc {frame}) as end_utc,
                   avg(price_ore_per_kwh) over () as day_avg_ore
            from marts.fct_prices_15min
            where price_area = :area and delivery_date = :day
            order by interval_start_utc""",  # noqa: S608 - n is a validated integer
        {"area": area, "day": day},
    )
    candidates = [r for r in rows if r["n_intervals"] == n]
    if earliest_start_utc is not None:
        candidates = [r for r in candidates if r["interval_start_utc"] >= earliest_start_utc]
    notes = [ENERGY_ONLY_NOTE]
    data: dict[str, Any] = {"unit": "öre/kWh", "duration_minutes": duration_minutes}
    if not candidates:
        notes.append("No complete window found: prices for that day may not be published yet.")
        data.update(cheapest=None, dearest=None, day_avg_ore_per_kwh=None)
    else:

        def window(r: dict) -> dict:
            return {
                "start_utc": r["interval_start_utc"],
                "end_utc": r["end_utc"],
                "start_local": r["interval_start_local"],
                "avg_ore_per_kwh": _num(r["avg_ore"]),
            }

        best = min(candidates, key=lambda r: (r["avg_ore"], r["interval_start_utc"]))
        worst = max(candidates, key=lambda r: (r["avg_ore"], r["interval_start_utc"]))
        day_avg = _num(rows[0]["day_avg_ore"])
        data.update(
            cheapest=window(best),
            dearest=window(worst),
            day_avg_ore_per_kwh=day_avg,
            saving_vs_day_avg_ore_per_kwh=_num(day_avg - _num(best["avg_ore"])),
            saving_vs_dearest_ore_per_kwh=_num(_num(worst["avg_ore"]) - _num(best["avg_ore"])),
        )
    return Result(
        tool="cheapest_window",
        inputs={
            "area": area,
            "day": day,
            "duration_minutes": duration_minutes,
            "earliest_start_utc": earliest_start_utc,
        },
        data=data,
        rows_read=len(rows),
        truncated=truncated,
        sources=["marts.fct_prices_15min"],
        notes=notes,
    )


def user_profile(wh: Warehouse, user_id: str) -> dict | None:
    check_user_id(user_id)
    rows = wh.fetch(
        "select user_id, display_name, price_area, is_synthetic "
        "from marts.dim_app_users where user_id = :user_id and status = 'active' limit 1",
        {"user_id": user_id},
    )
    return rows[0] if rows else None


def is_deleted(wh: Warehouse, user_id: str) -> bool:
    """True if the account asked to be deleted. (On Snowflake the app role cannot see
    such rows at all, so this is False there and the row access policy does the work.)"""
    check_user_id(user_id)
    rows = wh.fetch(
        "select 1 as x from marts.dim_app_users where user_id = :user_id and status = 'deleted'",
        {"user_id": user_id},
    )
    return bool(rows)


def cost_of_my_usage(wh: Warehouse, user_id: str, start_date: date, end_date: date) -> Result:
    """What the signed-in user's consumption cost at 15-minute spot prices (max 93 days)."""
    check_user_id(user_id)
    check_range(start_date, end_date, 93)
    if is_deleted(wh, user_id):
        raise QueryInputError("this account has been deleted")
    rows, truncated = _fetch(
        wh,
        """select delivery_date,
                  sum(kwh)                                              as kwh,
                  sum(spot_cost_sek)                                    as cost_sek,
                  avg(price_ore_per_kwh)                                as day_avg_ore,
                  sum(case when has_price then 0 else 1 end)            as n_unpriced
           from marts.fct_consumption_15min
           where user_id = :user_id
             and delivery_date between :start_date and :end_date
           group by delivery_date
           order by delivery_date""",
        {"user_id": user_id, "start_date": start_date, "end_date": end_date},
    )
    days = [
        {
            "date": r["delivery_date"],
            "kwh": _num(r["kwh"], 3),
            "cost_sek": _num(r["cost_sek"], 2),
            "avg_paid_ore_per_kwh": _num(100 * float(r["cost_sek"]) / float(r["kwh"]))
            if r["kwh"]
            else None,
            "day_avg_ore_per_kwh": _num(r["day_avg_ore"]),
        }
        for r in rows
    ]
    total_kwh = sum(d["kwh"] or 0 for d in days)
    total_cost = sum(float(r["cost_sek"] or 0) for r in rows)
    flat_cost = sum((d["kwh"] or 0) * (d["day_avg_ore_per_kwh"] or 0) / 100 for d in days)
    notes = [ENERGY_ONLY_NOTE]
    if any(r["n_unpriced"] for r in rows):
        notes.append("Some readings have no price yet and are left out of the cost.")
    if not rows:
        notes.append("No consumption for these days.")
    return Result(
        tool="cost_of_my_usage",
        inputs={"start_date": start_date, "end_date": end_date},
        data={
            "unit_cost": "SEK",
            "unit_price": "öre/kWh",
            "total_kwh": _num(total_kwh, 3),
            "total_cost_sek": _num(total_cost, 2),
            "avg_paid_ore_per_kwh": _num(100 * total_cost / total_kwh) if total_kwh else None,
            "cost_at_daily_average_sek": _num(flat_cost, 2),
            # negative = you used more when it was cheap than an even spread would
            "timing_effect_sek": _num(total_cost - flat_cost, 2),
            "days": days,
        },
        rows_read=len(rows),
        truncated=truncated,
        sources=["marts.fct_consumption_15min"],
        notes=notes,
    )


def compare_plans(
    wh: Warehouse,
    user_id: str,
    start_date: date,
    end_date: date,
    fixed_price_ore_per_kwh: float | None = None,
) -> Result:
    """The user's consumption priced three ways: 15-minute spot, monthly average, fixed."""
    check_user_id(user_id)
    check_range(start_date, end_date, 366)
    if fixed_price_ore_per_kwh is not None and not (0 <= fixed_price_ore_per_kwh <= 1000):
        raise QueryInputError("fixed price must be between 0 and 1000 öre/kWh")
    profile = user_profile(wh, user_id)
    if profile is None:
        raise QueryInputError("no profile for this user")
    area = profile["price_area"]

    usage, t1 = _fetch(
        wh,
        """select extract(year from delivery_date)  as y,
                  extract(month from delivery_date) as m,
                  sum(kwh)                          as kwh,
                  sum(spot_cost_sek)                as spot_cost_sek
           from marts.fct_consumption_15min
           where user_id = :user_id and has_price
             and delivery_date between :start_date and :end_date
           group by 1, 2
           order by 1, 2""",
        {"user_id": user_id, "start_date": start_date, "end_date": end_date},
    )
    month_start = start_date.replace(day=1)
    month_end = (end_date.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    averages, t2 = _fetch(
        wh,
        """select extract(year from delivery_date)  as y,
                  extract(month from delivery_date) as m,
                  avg(price_ore_per_kwh)            as avg_ore,
                  count(distinct delivery_date)     as days_with_prices
           from marts.fct_prices_15min
           where price_area = :area and delivery_date between :month_start and :month_end
           group by 1, 2""",
        {"area": area, "month_start": month_start, "month_end": month_end},
    )
    avg_by_month = {(int(a["y"]), int(a["m"])): a for a in averages}
    months = []
    for u in usage:
        key = (int(u["y"]), int(u["m"]))
        a = avg_by_month.get(key)
        kwh = float(u["kwh"])
        months.append(
            {
                "month": f"{key[0]:04d}-{key[1]:02d}",
                "kwh": _num(kwh, 3),
                "spot_15min_sek": _num(u["spot_cost_sek"], 2),
                "monthly_avg_ore_per_kwh": _num(a["avg_ore"]) if a else None,
                "monthly_average_sek": _num(kwh * float(a["avg_ore"]) / 100, 2) if a else None,
                "days_with_prices_in_month": int(a["days_with_prices"]) if a else 0,
                "fixed_sek": _num(kwh * fixed_price_ore_per_kwh / 100, 2)
                if fixed_price_ore_per_kwh is not None
                else None,
            }
        )
    plans = [
        {
            "plan": "spot_15min",
            "label": "15-minute spot price",
            "cost_sek": _num(sum(m["spot_15min_sek"] or 0 for m in months), 2),
        },
        {
            "plan": "monthly_average",
            "label": "Monthly average spot price",
            "cost_sek": _num(sum(m["monthly_average_sek"] or 0 for m in months), 2),
        },
    ]
    if fixed_price_ore_per_kwh is not None:
        plans.append(
            {
                "plan": "fixed",
                "label": f"Fixed {fixed_price_ore_per_kwh:g} öre/kWh",
                "cost_sek": _num(sum(m["fixed_sek"] or 0 for m in months), 2),
            }
        )
    cheapest = min(plans, key=lambda p: p["cost_sek"]) if months else None
    notes = [
        ENERGY_ONLY_NOTE,
        "Monthly average is the plain average of the month's 15-minute prices; suppliers "
        "may weight it differently.",
    ]
    if any(m["days_with_prices_in_month"] < 28 for m in months):
        notes.append(
            "Some months have incomplete price history; their monthly average is "
            "based on the days available."
        )
    return Result(
        tool="compare_plans",
        inputs={
            "start_date": start_date,
            "end_date": end_date,
            "fixed_price_ore_per_kwh": fixed_price_ore_per_kwh,
        },
        data={
            "price_area": area,
            "unit": "SEK",
            "plans": plans,
            "cheapest_plan": cheapest["plan"] if cheapest else None,
            "months": months,
        },
        rows_read=len(usage) + len(averages),
        truncated=t1 or t2,
        sources=["marts.fct_consumption_15min", "marts.fct_prices_15min", "marts.dim_app_users"],
        notes=notes,
    )


def explain_spike(wh: Warehouse, area: str, interval_start_utc: datetime) -> Result:
    """Put one 15-minute price in context: its day, its history and the other areas."""
    check_area(area)
    if interval_start_utc.tzinfo is not None:
        interval_start_utc = interval_start_utc.astimezone(UTC).replace(tzinfo=None)
    if interval_start_utc.minute % 15 or interval_start_utc.second:
        raise QueryInputError("interval start must be on a quarter-hour (UTC)")
    week_ago = interval_start_utc - timedelta(days=7)
    month_ago = interval_start_utc - timedelta(days=30)

    same_time, t1 = _fetch(
        wh,
        """select price_area, delivery_date, interval_start_utc, interval_start_local,
                  price_ore_per_kwh, is_upsampled_from_hourly
           from marts.fct_prices_15min
           where interval_start_utc in (:t, :week_ago)
           order by interval_start_utc, price_area""",
        {"t": interval_start_utc, "week_ago": week_ago},
    )
    target = next(
        (
            r
            for r in same_time
            if r["price_area"] == area and r["interval_start_utc"] == interval_start_utc
        ),
        None,
    )
    if target is None:
        raise QueryInputError("no price for that area and interval")

    context, t2 = _fetch(
        wh,
        """select
               avg(case when delivery_date = :day then price_ore_per_kwh end)  as day_avg,
               max(case when delivery_date = :day then price_ore_per_kwh end)  as day_max,
               sum(case when delivery_date = :day and price_ore_per_kwh < :price
                        then 1 else 0 end)                                      as n_cheaper_in_day,
               sum(case when delivery_date = :day then 1 else 0 end)            as n_in_day,
               avg(case when interval_start_utc >= :month_ago
                         and interval_start_utc < :t then price_ore_per_kwh end) as avg_30d
           from marts.fct_prices_15min
           where price_area = :area
             and interval_start_utc >= :month_ago
             and interval_start_utc < :next_day""",
        {
            "area": area,
            "day": target["delivery_date"],
            "price": target["price_ore_per_kwh"],
            "month_ago": month_ago,
            "t": interval_start_utc,
            "next_day": interval_start_utc + timedelta(days=1),
        },
    )
    c = context[0]
    price = _num(target["price_ore_per_kwh"])
    others = {
        r["price_area"]: _num(r["price_ore_per_kwh"])
        for r in same_time
        if r["interval_start_utc"] == interval_start_utc
    }
    week = next(
        (
            _num(r["price_ore_per_kwh"])
            for r in same_time
            if r["price_area"] == area and r["interval_start_utc"] == week_ago
        ),
        None,
    )
    observations = []
    day_avg = _num(c["day_avg"])
    if day_avg:
        observations.append(
            {
                "kind": "vs_day_average",
                "day_avg_ore_per_kwh": day_avg,
                "ratio": _num(price / day_avg, 2) if day_avg > 0 else None,
            }
        )
    if c["n_in_day"]:
        observations.append(
            {
                "kind": "rank_in_day",
                "share_of_day_cheaper": _num(int(c["n_cheaper_in_day"]) / int(c["n_in_day"]), 2),
                "is_day_max": price == _num(c["day_max"]),
            }
        )
    if c["avg_30d"] is not None:
        observations.append(
            {"kind": "vs_30_day_average", "avg_30d_ore_per_kwh": _num(c["avg_30d"])}
        )
    if week is not None:
        observations.append({"kind": "same_time_last_week", "price_ore_per_kwh": week})
    hour = target["interval_start_local"].hour
    if 7 <= hour < 10 or 16 <= hour < 20:
        observations.append({"kind": "peak_hours", "local_hour": hour})
    lowest_area = min(others, key=others.get)
    spread = _num(price - others[lowest_area])
    observations.append(
        {
            "kind": "area_spread",
            "prices_ore_per_kwh": others,
            "gap_to_cheapest_area_ore_per_kwh": spread,
            "cheapest_area": lowest_area,
            # Areas only get different prices when transmission between them is full.
            "suggests_congestion": bool(spread and spread > 1),
        }
    )

    # Day-ahead grid forecasts for the same quarter, against the area's 30-day average.
    grid, t3 = _fetch(
        wh,
        """select
               max(case when interval_start_utc = :t then load_mw end)  as load_mw,
               max(case when interval_start_utc = :t then wind_mw end)  as wind_mw,
               max(case when interval_start_utc = :t then solar_mw end) as solar_mw,
               avg(case when interval_start_utc < :t then load_mw end)  as load_avg_30d,
               avg(case when interval_start_utc < :t then wind_mw end)  as wind_avg_30d,
               sum(case when interval_start_utc = :t then 1 else 0 end) as n_target
           from marts.fct_grid_forecast_15min
           where price_area = :area
             and interval_start_utc >= :month_ago
             and interval_start_utc <= :t""",
        {"area": area, "month_ago": month_ago, "t": interval_start_utc},
    )
    g = grid[0] if grid else {}
    has_grid = bool(g.get("n_target"))
    if has_grid:

        def ratio(value, average):
            value, average = _num(value), _num(average)
            return _num(value / average, 2) if value is not None and average else None

        observations.append(
            {
                "kind": "grid_forecast",
                "load_mw": _num(g["load_mw"], 0),
                "wind_mw": _num(g["wind_mw"], 0),
                "solar_mw": _num(g["solar_mw"], 0),
                "load_vs_30d_avg_ratio": ratio(g["load_mw"], g["load_avg_30d"]),
                "wind_vs_30d_avg_ratio": ratio(g["wind_mw"], g["wind_avg_30d"]),
            }
        )
    return Result(
        tool="explain_spike",
        inputs={"area": area, "interval_start_utc": interval_start_utc},
        data={
            "unit": "öre/kWh",
            "interval": {
                "start_utc": target["interval_start_utc"],
                "start_local": target["interval_start_local"],
                "price_ore_per_kwh": price,
                "upsampled_from_hourly": bool(target["is_upsampled_from_hourly"]),
            },
            "observations": observations,
        },
        rows_read=len(same_time) + len(context) + len(grid),
        truncated=t1 or t2 or t3,
        sources=["marts.fct_prices_15min"]
        + (["marts.fct_grid_forecast_15min"] if has_grid else []),
        notes=[ENERGY_ONLY_NOTE, GRID_NOTE if has_grid else NO_DRIVER_DATA_NOTE],
    )


def alerts(wh: Warehouse, area: str, day: date) -> Result:
    """Things worth telling someone about one delivery day, each with its numbers:
    negative quarters, a cheap 2-hour window (below half the 30-day average) and a
    spike (a quarter above twice the 30-day average)."""
    check_area(area)
    rows, truncated = _fetch(
        wh,
        """select interval_start_utc, interval_end_utc, price_ore_per_kwh
           from marts.fct_prices_15min
           where price_area = :area and delivery_date = :day
           order by interval_start_utc""",
        {"area": area, "day": day},
    )
    base = wh.fetch(
        """select avg(price_ore_per_kwh) as avg_30d from marts.fct_prices_15min
           where price_area = :area and delivery_date >= :since and delivery_date < :day""",
        {"area": area, "since": day - timedelta(days=30), "day": day},
    )
    avg_30d = _num(base[0]["avg_30d"]) if base and base[0]["avg_30d"] is not None else None
    found: list[dict] = []
    if rows:
        negative = [r for r in rows if r["price_ore_per_kwh"] < 0]
        if negative:
            found.append(
                {
                    "kind": "negative_prices",
                    "n_quarters": len(negative),
                    "first_start_utc": negative[0]["interval_start_utc"],
                    "last_end_utc": negative[-1]["interval_end_utc"],
                    "lowest_ore_per_kwh": _num(min(r["price_ore_per_kwh"] for r in negative)),
                }
            )
        if avg_30d and avg_30d > 0 and len(rows) >= 8:
            prices = [float(r["price_ore_per_kwh"]) for r in rows]
            sums = [sum(prices[i : i + 8]) / 8 for i in range(len(prices) - 7)]
            best = min(range(len(sums)), key=sums.__getitem__)
            if sums[best] < 0.5 * avg_30d:
                found.append(
                    {
                        "kind": "cheap_window",
                        "start_utc": rows[best]["interval_start_utc"],
                        "end_utc": rows[best + 7]["interval_end_utc"],
                        "avg_ore_per_kwh": _num(sums[best]),
                        "avg_30d_ore_per_kwh": avg_30d,
                    }
                )
            peak = max(rows, key=lambda r: r["price_ore_per_kwh"])
            if peak["price_ore_per_kwh"] > 2 * avg_30d:
                found.append(
                    {
                        "kind": "spike",
                        "start_utc": peak["interval_start_utc"],
                        "price_ore_per_kwh": _num(peak["price_ore_per_kwh"]),
                        "avg_30d_ore_per_kwh": avg_30d,
                    }
                )
    return Result(
        tool="alerts",
        inputs={"area": area, "day": day},
        data={"published": bool(rows), "alerts": found, "avg_30d_ore_per_kwh": avg_30d},
        rows_read=len(rows) + len(base),
        truncated=truncated,
        sources=["marts.fct_prices_15min"],
        notes=[ENERGY_ONLY_NOTE],
    )
