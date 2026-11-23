"""Features, baselines, walk-forward test and the next-day forecast.

Port of thar-26/elpris-forecast (features.py, baseline.py, backtest.py, evaluate.py),
moved from hours to quarter-hours:

* The forecast for tomorrow is made today, when prices up to the end of today are known.
  So every input for a quarter is at least 24 hours (96 quarters) older than it.
* Baselines a model must beat: the same quarter yesterday and the same quarter last week.
* Walk-forward test: each test day is forecast by a model trained only on earlier days.
* A win must be proven: a 95% bootstrap range for the average daily gain that excludes
  zero; otherwise the verdict is "not proven". A worse model is reported as worse.

Units are öre/kWh throughout (the old project used SEK/kWh).
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

LOCAL_TZ = "Europe/Stockholm"
Q_DAY = 96  # quarters in a normal day
Q_WEEK = 7 * Q_DAY
MIN_TRAINING_DAYS = 14
REFERENCE = "same_quarter_yesterday"

FEATURES = [
    "lag_96",  # price at the same quarter yesterday
    "lag_192",  # same quarter two days ago
    "lag_672",  # same quarter last week
    "mean_96",  # average of the 24 hours ending 24 hours ago
    "std_96",  # how much prices moved in those 24 hours
    "mean_672",  # average of the week ending 24 hours ago
    "quarter",  # quarter of the local day, 0..95
    "weekend",  # 1 on Saturday and Sunday
]


def build_features(prices: pd.DataFrame, until: pd.Timestamp | None = None) -> pd.DataFrame:
    """One row per area and quarter with the actual price and inputs that are all at
    least 24 hours old.

    Input columns: area, start_utc (tz-aware UTC), ore.
    Output columns: area, start_utc, local_date, actual, *FEATURES.
    `until` adds future quarters (actual empty) built by the same code as training rows.
    """
    frames = []
    for area, group in prices.groupby("area"):
        series = group.set_index("start_utc")["ore"].sort_index().asfreq("15min")
        if until is not None and until > series.index.max():
            series = series.reindex(pd.date_range(series.index.min(), until, freq="15min"))
        known = series.shift(Q_DAY)  # the newest price we may use for each quarter

        frame = pd.DataFrame({"actual": series})
        frame["lag_96"] = known
        frame["lag_192"] = series.shift(2 * Q_DAY)
        frame["lag_672"] = series.shift(Q_WEEK)
        frame["mean_96"] = known.rolling(Q_DAY).mean()
        frame["std_96"] = known.rolling(Q_DAY).std()
        frame["mean_672"] = known.rolling(Q_WEEK).mean()
        local = frame.index.tz_convert(LOCAL_TZ)
        frame["quarter"] = local.hour * 4 + local.minute // 15
        frame["weekend"] = (local.dayofweek >= 5).astype(int)
        frame["local_date"] = local.date
        frame["area"] = area
        frame.index.name = "start_utc"
        frames.append(frame.reset_index())

    columns = ["area", "start_utc", "local_date", "actual", *FEATURES]
    if not frames:
        return pd.DataFrame(columns=columns)
    out = pd.concat(frames, ignore_index=True)[columns].dropna(subset=FEATURES)
    if until is None:
        out = out.dropna(subset=["actual"])
    return out.reset_index(drop=True)


def walk_forward(features: pd.DataFrame, test_days: int = 60) -> pd.DataFrame:
    """Forecast each of the last `test_days` days with models trained only on earlier days.

    Columns: area, start_utc, local_date, method, actual, forecast.
    """
    days = sorted(features["local_date"].unique())
    if len(days) < test_days + MIN_TRAINING_DAYS:
        raise ValueError(
            f"need at least {test_days + MIN_TRAINING_DAYS} usable days, have {len(days)}"
        )
    pieces = []
    for _area, rows in features.groupby("area"):
        for day in days[-test_days:]:
            train = rows[rows["local_date"] < day]
            test = rows[rows["local_date"] == day]
            if test.empty:
                continue
            model = Ridge(alpha=1.0).fit(train[FEATURES], train["actual"])
            forecasts = {
                REFERENCE: test["lag_96"].to_numpy(),
                "same_quarter_last_week": test["lag_672"].to_numpy(),
                "blend_yesterday_and_week": (
                    0.5 * test["lag_96"] + 0.5 * test["mean_672"]
                ).to_numpy(),
                "ridge": model.predict(test[FEATURES]),
            }
            for method, values in forecasts.items():
                piece = test[["area", "start_utc", "local_date", "actual"]].copy()
                piece["method"] = method
                piece["forecast"] = values
                pieces.append(piece)
    return pd.concat(pieces, ignore_index=True)


def gain_range(daily_gain, resamples: int = 5000) -> tuple[float, float]:
    """95% range for the average daily gain, by resampling the days (seeded)."""
    gain = np.asarray(daily_gain, dtype=float)
    samples = np.random.default_rng(0).choice(gain, size=(resamples, len(gain))).mean(axis=1)
    low, high = np.percentile(samples, [2.5, 97.5])
    return float(low), float(high)


def verdict(low: float, high: float) -> str:
    if low > 0:
        return "beats baseline"
    if high < 0:
        return "worse"
    return "not proven"


def compare_methods(predictions: pd.DataFrame, resamples: int = 5000) -> list[dict]:
    """Every method against the reference (same quarter yesterday), area by area."""
    scored = predictions.assign(miss=(predictions["actual"] - predictions["forecast"]).abs())
    daily = scored.groupby(["area", "method", "local_date"])["miss"].mean().unstack("method")
    overall = scored.groupby(["area", "method"])["miss"].mean()
    rows = []
    for area, area_daily in daily.groupby(level="area"):
        ref = overall[(area, REFERENCE)]
        for method in area_daily.columns:
            mae = overall[(area, method)]
            row = {
                "area": area,
                "method": method,
                "mae_ore_per_kwh": round(float(mae), 2),
                "gain_pct": round(float(100 * (ref - mae) / ref), 1) if ref else None,
                "days": int(len(area_daily)),
                "days_won": None,
                "gain_low": None,
                "gain_high": None,
                "verdict": "reference",
            }
            if method != REFERENCE:
                gain = (area_daily[REFERENCE] - area_daily[method]).to_numpy()
                low, high = gain_range(gain, resamples)
                row.update(
                    days_won=int((gain > 0).sum()),
                    gain_low=round(low, 2),
                    gain_high=round(high, 2),
                    verdict=verdict(low, high),
                )
            rows.append(row)
    return sorted(rows, key=lambda r: (r["area"], r["method"] != REFERENCE, r["mae_ore_per_kwh"]))


def forecast_day(prices: pd.DataFrame, area: str, day: date) -> pd.DataFrame:
    """Ridge forecast for every quarter of local `day` in `area`, trained on all known
    history. Needs prices up to the end of the day before `day`.

    Columns: start_utc, forecast_ore.
    """
    rows = prices[prices["area"] == area]
    # Local midnight to local midnight: 96 quarters, or 92/100 on clock-change days.
    start = pd.Timestamp(day.isoformat()).tz_localize(LOCAL_TZ).tz_convert("UTC")
    end = (
        pd.Timestamp((day + timedelta(days=1)).isoformat()).tz_localize(LOCAL_TZ).tz_convert("UTC")
    )
    known = rows[rows["start_utc"] < start]
    if known.empty or known["start_utc"].max() < start - pd.Timedelta(minutes=15):
        raise ValueError("prices up to the end of the previous day are needed")
    features = build_features(known, until=end - pd.Timedelta(minutes=15))
    train = features.dropna(subset=["actual"])
    target = features[(features["start_utc"] >= start) & (features["start_utc"] < end)]
    if len(train) < MIN_TRAINING_DAYS * Q_DAY or target.empty:
        raise ValueError("not enough history to forecast")
    model = Ridge(alpha=1.0).fit(train[FEATURES], train["actual"])
    return pd.DataFrame(
        {
            "start_utc": target["start_utc"].to_numpy(),
            "forecast_ore": model.predict(target[FEATURES]),
        }
    )


def load_prices(wh, since: date) -> pd.DataFrame:
    """All 15-minute prices since `since`, from the warehouse (DuckDB or Snowflake)."""
    rows = wh.fetch(
        "select price_area as area, interval_start_utc as start_utc, price_ore_per_kwh as ore "
        "from marts.fct_prices_15min where delivery_date >= :since order by 1, 2",
        {"since": since},
    )
    frame = pd.DataFrame(rows, columns=["area", "start_utc", "ore"])
    frame["start_utc"] = pd.to_datetime(frame["start_utc"]).dt.tz_localize("UTC")
    frame["ore"] = frame["ore"].astype(float)
    return frame
