from datetime import date

import numpy as np
import pandas as pd
import pytest

from elkollen_forecast import model


def synthetic(days: int = 40, start: str = "2026-01-01", noise: float = 2.0) -> pd.DataFrame:
    """A clear daily shape (cheap night, dear evening) plus a little noise, in UTC."""
    idx = pd.date_range(start, periods=days * 96, freq="15min", tz="UTC")
    local_hour = idx.tz_convert("Europe/Stockholm").hour
    base = 50 + 40 * np.sin((local_hour - 6) / 24 * 2 * np.pi)
    rng = np.random.default_rng(1)
    return pd.DataFrame(
        {"area": "SE3", "start_utc": idx, "ore": base + rng.normal(0, noise, len(idx))}
    )


def test_inputs_never_look_at_the_same_day():
    """Changing a day's prices must not change that day's inputs (the 24-hour rule)."""
    prices = synthetic()
    before = model.build_features(prices)
    changed = prices.copy()
    cutoff = changed["start_utc"].max() - pd.Timedelta(hours=23, minutes=45)
    changed.loc[changed["start_utc"] >= cutoff, "ore"] = 9999.0
    after = model.build_features(changed)
    day = before["local_date"].max()
    cols = model.FEATURES
    pd.testing.assert_frame_equal(
        before[before["local_date"] == day][cols].reset_index(drop=True),
        after[after["local_date"] == day][cols].reset_index(drop=True),
    )


@pytest.mark.parametrize(
    ("day", "n"), [("2026-02-10", 96), ("2026-03-29", 92), ("2026-10-25", 100)]
)
def test_forecast_covers_every_quarter_of_the_local_day(day, n):
    d = date.fromisoformat(day)
    prices = synthetic(days=(d - date(2026, 1, 1)).days)
    out = model.forecast_day(prices, "SE3", d)
    assert len(out) == n


def test_forecast_learns_the_daily_shape():
    day = date(2026, 2, 10)
    history = synthetic(days=40)
    out = model.forecast_day(history, "SE3", day)
    truth = synthetic(days=41)
    truth = truth[truth["start_utc"].isin(out["start_utc"])]["ore"].to_numpy()
    assert np.mean(np.abs(out["forecast_ore"].to_numpy() - truth)) < 6  # noise is 2 öre


def test_forecast_needs_yesterdays_prices():
    with pytest.raises(ValueError, match="previous day"):
        model.forecast_day(synthetic(days=30), "SE3", date(2026, 3, 15))


def test_walk_forward_and_verdicts():
    results = model.compare_methods(model.walk_forward(model.build_features(synthetic(40)), 10))
    by_method = {r["method"]: r for r in results}
    assert by_method["same_quarter_yesterday"]["verdict"] == "reference"
    assert by_method["ridge"]["days"] == 10
    assert by_method["ridge"]["verdict"] in {"beats baseline", "not proven", "worse"}


@pytest.mark.parametrize(
    ("low", "high", "expected"),
    [(0.5, 2.0, "beats baseline"), (-1.0, 1.0, "not proven"), (-2.0, -0.5, "worse")],
)
def test_verdict(low, high, expected):
    assert model.verdict(low, high) == expected
