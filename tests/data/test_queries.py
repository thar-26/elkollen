from datetime import UTC, date, datetime

import pytest

from elkollen_data import queries
from elkollen_data.queries import QueryInputError
from tests.conftest import DELETED_USER

ANNA, ERIK = "demo-anna", "demo-erik"
WEEK = (date(2025, 9, 29), date(2025, 10, 5))


def raw_total(warehouse, user_id):
    return warehouse.fetch(
        "select sum(kwh) as kwh, sum(spot_cost_sek) as cost from marts.fct_consumption_15min "
        "where user_id = :u and delivery_date between :s and :e",
        {"u": user_id, "s": WEEK[0], "e": WEEK[1]},
    )[0]


# ------------------------------------------------------------------ prices


@pytest.mark.parametrize(
    ("day", "n"),
    [("2025-10-01", 96), ("2025-10-26", 100), ("2026-03-29", 92), ("2025-09-30", 96)],
)
def test_get_prices_interval_counts(warehouse, day, n):
    d = date.fromisoformat(day)
    r = queries.get_prices(warehouse, "SE3", d, d)
    assert r.data["summary"]["n_intervals"] == n
    assert r.data["unit"] == "öre/kWh"


def test_get_prices_flags_hourly_source(warehouse):
    r = queries.get_prices(warehouse, "SE3", date(2025, 9, 30), date(2025, 10, 1))
    flags = {i["upsampled_from_hourly"] for i in r.data["intervals"]}
    assert flags == {True, False}
    assert any("hourly" in n for n in r.notes)


def test_get_prices_keeps_negative_prices(warehouse):
    r = queries.get_prices(warehouse, "SE1", date(2025, 10, 2), date(2025, 10, 2))
    assert r.data["summary"]["min_ore_per_kwh"] == pytest.approx(-104.304)
    assert r.data["summary"]["n_negative"] > 0


@pytest.mark.parametrize(
    ("area", "start", "end", "message"),
    [
        ("SE5", "2025-10-01", "2025-10-01", "unknown price area"),
        ("se3", "2025-10-01", "2025-10-01", "unknown price area"),
        ("SE3", "2025-10-02", "2025-10-01", "before start"),
        ("SE3", "2025-10-01", "2025-10-20", "too long"),
    ],
)
def test_get_prices_rejects_bad_input(warehouse, area, start, end, message):
    with pytest.raises(QueryInputError, match=message):
        queries.get_prices(warehouse, area, date.fromisoformat(start), date.fromisoformat(end))


def test_get_prices_reports_missing_days(warehouse):
    r = queries.get_prices(warehouse, "SE3", date(2030, 1, 1), date(2030, 1, 1))
    assert r.data["intervals"] == [] and r.data["summary"] is None
    assert any("13:00" in n for n in r.notes)


# ------------------------------------------------------------------ cheapest window


def test_cheapest_window_is_cheapest(warehouse):
    r = queries.cheapest_window(warehouse, "SE4", date(2025, 10, 4), 60)
    cheap, dear = r.data["cheapest"], r.data["dearest"]
    assert cheap["avg_ore_per_kwh"] <= r.data["day_avg_ore_per_kwh"] <= dear["avg_ore_per_kwh"]
    # brute force over the same day
    day = date(2025, 10, 4)
    intervals = queries.get_prices(warehouse, "SE4", day, day).data["intervals"]
    prices = [i["price_ore_per_kwh"] for i in intervals]
    best = min(sum(prices[i : i + 4]) / 4 for i in range(len(prices) - 3))
    assert cheap["avg_ore_per_kwh"] == pytest.approx(best, abs=1e-3)
    assert (cheap["end_utc"] - cheap["start_utc"]).total_seconds() == 3600


def test_cheapest_window_respects_earliest_start(warehouse):
    day = date(2025, 10, 4)
    unrestricted = queries.cheapest_window(warehouse, "SE4", day, 60)
    later = datetime(2025, 10, 4, 15, 0)
    r = queries.cheapest_window(warehouse, "SE4", day, 60, earliest_start_utc=later)
    assert r.data["cheapest"]["start_utc"] >= later
    assert r.data["cheapest"]["avg_ore_per_kwh"] >= unrestricted.data["cheapest"]["avg_ore_per_kwh"]


@pytest.mark.parametrize("minutes", [0, 10, 20, 735, -15])
def test_cheapest_window_rejects_bad_duration(warehouse, minutes):
    with pytest.raises(QueryInputError, match="multiple of 15"):
        queries.cheapest_window(warehouse, "SE3", date(2025, 10, 1), minutes)


def test_cheapest_window_without_prices(warehouse):
    r = queries.cheapest_window(warehouse, "SE3", date(2030, 1, 1), 60)
    assert r.data["cheapest"] is None


# ------------------------------------------------------------------ per-user


def test_cost_of_my_usage_matches_the_mart(warehouse):
    r = queries.cost_of_my_usage(warehouse, ANNA, *WEEK)
    expected = raw_total(warehouse, ANNA)
    assert r.data["total_kwh"] == pytest.approx(expected["kwh"], abs=1e-3)
    assert r.data["total_cost_sek"] == pytest.approx(expected["cost"], abs=0.01)
    assert len(r.data["days"]) == 7
    assert "user_id" not in r.inputs  # never echoed back as if it were a parameter


def test_cost_of_my_usage_only_sees_own_rows(warehouse):
    anna = queries.cost_of_my_usage(warehouse, ANNA, *WEEK).data["total_kwh"]
    erik = queries.cost_of_my_usage(warehouse, ERIK, *WEEK).data["total_kwh"]
    assert anna == pytest.approx(raw_total(warehouse, ANNA)["kwh"], abs=1e-3)
    assert erik == pytest.approx(raw_total(warehouse, ERIK)["kwh"], abs=1e-3)
    assert anna != erik


@pytest.mark.parametrize(
    "user_id", ["", "x" * 200, "anna' or '1'='1", "demo-anna; drop table x", None]
)
def test_per_user_queries_reject_malformed_user_ids(warehouse, user_id):
    with pytest.raises(QueryInputError):
        queries.cost_of_my_usage(warehouse, user_id, *WEEK)


def test_unknown_user_gets_nothing(warehouse):
    r = queries.cost_of_my_usage(warehouse, "nobody", *WEEK)
    assert r.data["total_kwh"] == 0 and r.data["days"] == []


def test_deleted_user_cannot_read_own_consumption(warehouse):
    with pytest.raises(QueryInputError, match="deleted"):
        queries.cost_of_my_usage(warehouse, DELETED_USER, *WEEK)


def test_deleted_user_has_no_profile(warehouse):
    assert queries.user_profile(warehouse, DELETED_USER) is None
    assert queries.user_profile(warehouse, ANNA)["price_area"] == "SE3"


def test_compare_plans(warehouse):
    r = queries.compare_plans(warehouse, ERIK, *WEEK, fixed_price_ore_per_kwh=100)
    plans = {p["plan"]: p["cost_sek"] for p in r.data["plans"]}
    assert set(plans) == {"spot_15min", "monthly_average", "fixed"}
    spot = queries.cost_of_my_usage(warehouse, ERIK, *WEEK).data["total_cost_sek"]
    assert plans["spot_15min"] == pytest.approx(spot, abs=0.02)
    assert plans["fixed"] == pytest.approx(raw_total(warehouse, ERIK)["kwh"], abs=0.02)
    assert r.data["cheapest_plan"] == min(plans, key=plans.get)
    assert r.data["price_area"] == "SE4"


def test_compare_plans_rejects_silly_fixed_price(warehouse):
    with pytest.raises(QueryInputError, match="fixed price"):
        queries.compare_plans(warehouse, ERIK, *WEEK, fixed_price_ore_per_kwh=-5)


def test_compare_plans_refuses_deleted_user(warehouse):
    with pytest.raises(QueryInputError, match="no profile"):
        queries.compare_plans(warehouse, DELETED_USER, *WEEK)


# ------------------------------------------------------------------ explain_spike


def test_explain_spike_on_negative_price(warehouse):
    t = datetime(2025, 10, 2, 16, 45)  # 18:45 local, SE1 -104.304 öre/kWh
    r = queries.explain_spike(warehouse, "SE1", t)
    assert r.data["interval"]["price_ore_per_kwh"] == pytest.approx(-104.304)
    kinds = {o["kind"] for o in r.data["observations"]}
    assert {"vs_day_average", "rank_in_day", "area_spread", "peak_hours"} <= kinds
    spread = next(o for o in r.data["observations"] if o["kind"] == "area_spread")
    assert set(spread["prices_ore_per_kwh"]) == {"SE1", "SE2", "SE3", "SE4"}
    # No ENTSO-E fixture for SE1 that day: the answer says it used prices alone.
    assert "grid_forecast" not in kinds
    assert any("prices alone" in n for n in r.notes)
    assert "marts.fct_grid_forecast_15min" not in r.sources


def test_explain_spike_adds_grid_forecasts_when_stored(warehouse):
    from pathlib import Path

    from elkollen_ingest.entsoe import parse_document

    t = datetime(2025, 10, 1, 12, 0)  # 14:00 local; invented ENTSO-E fixture for SE3
    fixtures = Path(__file__).resolve().parents[2] / "fixtures" / "entsoe"
    expected = {
        p.series: p.mw
        for f in fixtures.glob("SE3_*_2025-10-01.xml")
        for p in parse_document("SE3", f.read_bytes())
        if p.start_utc == t
    }
    r = queries.explain_spike(warehouse, "SE3", t)
    grid = next(o for o in r.data["observations"] if o["kind"] == "grid_forecast")
    assert grid["load_mw"] == round(expected["load_forecast"])
    assert grid["wind_mw"] == round(expected["wind_onshore_forecast"])
    assert grid["solar_mw"] == round(expected["solar_forecast"])
    assert grid["load_vs_30d_avg_ratio"] > 0
    assert "marts.fct_grid_forecast_15min" in r.sources
    assert any("not measurements" in n for n in r.notes)


def test_explain_spike_accepts_aware_utc(warehouse):
    t = datetime(2025, 10, 2, 16, 45, tzinfo=UTC)
    r = queries.explain_spike(warehouse, "SE1", t)
    assert r.data["interval"]["start_utc"] == t.replace(tzinfo=None)


def test_explain_spike_rejects_off_grid_time(warehouse):
    with pytest.raises(QueryInputError, match="quarter-hour"):
        queries.explain_spike(warehouse, "SE1", datetime(2025, 10, 2, 16, 40))


# ------------------------------------------------------------------ row limit


def test_row_limit_marks_truncation(warehouse, monkeypatch):
    monkeypatch.setattr(queries, "MAX_ROWS", 10)
    r = queries.get_prices(warehouse, "SE3", date(2025, 10, 1), date(2025, 10, 1))
    assert r.truncated and len(r.data["intervals"]) == 10
