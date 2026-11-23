"""Analyse an uploaded consumption export in memory. Nothing is stored.

Accepted: CSV/semicolon exports as Swedish grid companies give them, hourly or 15-minute,
one row per interval with a local start time and kWh (decimal comma or point). The
time column and kWh column are found by name; times are Swedish local time, and on the
autumn clock-change day the repeated hour is read in order (first summer time, then
winter time).

What it computes, per day and month:
* paid: each interval's kWh x the spot price of that interval (an hourly reading is
  priced at the average of its four quarters). Spot price only, like everywhere else.
* could have paid: the same, but with a flexible share of each day's energy (default
  30 %, e.g. dishwasher, laundry, car) moved into that day's cheapest 4-hour window.
  An estimate with a stated assumption, not a promise.
"""

import csv
import io
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from elkollen_data.queries import ENERGY_ONLY_NOTE, QueryInputError, Result, check_area
from elkollen_data.warehouse import Warehouse

TZ = ZoneInfo("Europe/Stockholm")
MAX_BYTES = 5_000_000
MAX_ROWS = 60_000
MAX_DAYS = 400
_TIME_COL = re.compile(r"datum|date|tid|time|från|from|start|period", re.I)
_KWH_COL = re.compile(r"kwh|förbrukning|forbrukning|consumption|energi|energy|värde|value", re.I)


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise QueryInputError("the file is not text (expected CSV)")


def _number(text: str) -> float:
    return float(text.strip().replace(" ", "").replace(" ", "").replace(",", "."))


def parse_consumption(raw: bytes) -> list[tuple[datetime, int, float]]:
    """Return (start_utc naive, interval_minutes, kWh) rows, sorted."""
    if len(raw) > MAX_BYTES:
        raise QueryInputError("file too large (max 5 MB)")
    text = _decode(raw)
    delimiter = ";" if text.count(";") > text.count(",") / 2 else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    header_idx = next(
        (
            i
            for i, r in enumerate(rows[:20])
            if any(_TIME_COL.search(c) for c in r) and any(_KWH_COL.search(c) for c in r)
        ),
        None,
    )
    if header_idx is None:
        raise QueryInputError("could not find a time column and a kWh column")
    header = rows[header_idx]
    t_col = next(i for i, c in enumerate(header) if _TIME_COL.search(c))
    k_col = next(i for i, c in enumerate(header) if _KWH_COL.search(c) and i != t_col)
    body = [r for r in rows[header_idx + 1 :] if len(r) > max(t_col, k_col) and r[t_col].strip()]
    if not body:
        raise QueryInputError("the file has no data rows")
    if len(body) > MAX_ROWS:
        raise QueryInputError(f"too many rows (max {MAX_ROWS})")

    local_times, values = [], []
    for r in body:
        stamp = r[t_col].strip().replace("T", " ")[:16]
        try:
            local_times.append(datetime.strptime(stamp, "%Y-%m-%d %H:%M"))  # noqa: DTZ007
            values.append(_number(r[k_col]))
        except ValueError as exc:
            raise QueryInputError(f"could not read row {r!r}") from exc
    if any(v < 0 or v > 100 for v in values):
        raise QueryInputError("kWh values must be between 0 and 100 per interval")

    out, seen = [], set()
    for local, kwh in zip(local_times, values, strict=True):
        fold = 1 if local in seen else 0  # the repeated hour on the autumn change day
        seen.add(local)
        utc = local.replace(tzinfo=TZ, fold=fold).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        out.append([utc, kwh])
    out.sort()
    gaps = sorted(
        {int((b[0] - a[0]).total_seconds() // 60) for a, b in zip(out, out[1:], strict=False)}
    )
    minutes = 15 if gaps and gaps[0] == 15 else 60
    if (out[-1][0] - out[0][0]).days > MAX_DAYS:
        raise QueryInputError(f"period too long (max {MAX_DAYS} days)")
    return [(t, minutes, k) for t, k in out]


def analyse(wh: Warehouse, area: str, raw: bytes, flexible_share: float = 0.3) -> Result:
    check_area(area)
    if not 0 <= flexible_share <= 1:
        raise QueryInputError("flexible share must be between 0 and 1")
    readings = parse_consumption(raw)
    first, last = readings[0][0], readings[-1][0]
    prices = wh.fetch(
        """select delivery_date, interval_start_utc, price_ore_per_kwh
           from marts.fct_prices_15min
           where price_area = :area and interval_start_utc >= :first
             and interval_start_utc < :last
           order by interval_start_utc""",
        {"area": area, "first": first, "last": last + timedelta(hours=1)},
    )
    price_at = {p["interval_start_utc"]: float(p["price_ore_per_kwh"]) for p in prices}
    day_of = {p["interval_start_utc"]: p["delivery_date"] for p in prices}
    by_day: dict[date, list[float]] = defaultdict(list)
    for p in prices:
        by_day[p["delivery_date"]].append(float(p["price_ore_per_kwh"]))
    cheapest_4h = {
        d: min(sum(v[i : i + 16]) / 16 for i in range(len(v) - 15))
        for d, v in by_day.items()
        if len(v) >= 16
    }

    days: dict[date, dict] = {}
    unpriced = 0
    for start, minutes, kwh in readings:
        quarters = [start + timedelta(minutes=15 * i) for i in range(minutes // 15)]
        known = [price_at[q] for q in quarters if q in price_at]
        if len(known) != len(quarters):
            unpriced += 1
            continue
        day = days.setdefault(day_of[quarters[0]], {"kwh": 0.0, "paid": 0.0})
        day["kwh"] += kwh
        day["paid"] += kwh * (sum(known) / len(known)) / 100
    if not days:
        raise QueryInputError("no prices for the uploaded period and area")

    months: dict[str, dict] = defaultdict(
        lambda: {"kwh": 0.0, "paid": 0.0, "could": 0.0, "days": 0}
    )
    for d, v in sorted(days.items()):
        could = v["paid"]
        if d in cheapest_4h:
            moved = flexible_share * v["kwh"] * cheapest_4h[d] / 100
            could = (1 - flexible_share) * v["paid"] + moved
        m = months[f"{d:%Y-%m}"]
        m["kwh"] += v["kwh"]
        m["paid"] += v["paid"]
        m["could"] += min(could, v["paid"])
        m["days"] += 1
    total = {k: sum(m[k] for m in months.values()) for k in ("kwh", "paid", "could")}
    return Result(
        tool="analyse_upload",
        inputs={"area": area, "flexible_share": flexible_share},
        data={
            "resolution_minutes": readings[0][1],
            "first_start_utc": first,
            "last_start_utc": last,
            "readings": len(readings),
            "unpriced_readings": unpriced,
            "total_kwh": round(total["kwh"], 3),
            "paid_sek": round(total["paid"], 2),
            "could_have_paid_sek": round(total["could"], 2),
            "saving_sek": round(total["paid"] - total["could"], 2),
            "avg_paid_ore_per_kwh": round(100 * total["paid"] / total["kwh"], 2)
            if total["kwh"]
            else None,
            "months": [
                {
                    "month": k,
                    "days": v["days"],
                    "kwh": round(v["kwh"], 3),
                    "paid_sek": round(v["paid"], 2),
                    "could_have_paid_sek": round(v["could"], 2),
                }
                for k, v in sorted(months.items())
            ],
        },
        rows_read=len(prices),
        sources=["uploaded file (not stored)", "marts.fct_prices_15min"],
        notes=[
            ENERGY_ONLY_NOTE,
            f"'Could have paid' moves {round(flexible_share * 100)} % of each day's energy "
            "into that day's cheapest 4-hour window. It is an estimate.",
            "The file is analysed in memory and not stored.",
        ],
    )
