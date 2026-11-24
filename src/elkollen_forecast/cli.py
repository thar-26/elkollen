"""elkollen-forecast backtest  [--test-days 60] [--since 2024-11-01] [--out reports/...]
elkollen-forecast tomorrow  --area SE3

Reads prices from the warehouse chosen by ELKOLLEN_WAREHOUSE (duckdb or snowflake)."""

import argparse
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from elkollen_data.warehouse import warehouse_from_env
from elkollen_forecast import model


def cmd_backtest(args) -> int:
    wh = warehouse_from_env()
    prices = model.load_prices(wh, args.since)
    grid = model.load_grid(wh, args.since)
    # With grid forecasts, every method is scored only on quarters that have them, so
    # "prices only" and "with grid forecasts" are compared on exactly the same rows.
    features = model.build_features(prices, grid=grid if not grid.empty else None)
    results = model.compare_methods(model.walk_forward(features, args.test_days))
    days = sorted(features["local_date"].unique())
    report = {
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "test_days": args.test_days,
        "test_period": [str(days[-args.test_days]), str(days[-1])],
        "history_since": str(args.since),
        "inputs": "prices + ENTSO-E day-ahead load/wind/solar forecasts"
        if not grid.empty
        else "prices only",
        "unit": "öre/kWh, mean absolute error",
        "results": results,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    for r in results:
        print(
            f"{r['area']}  {r['method']:<27} MAE {r['mae_ore_per_kwh']:>7.2f}  "
            f"gain {r['gain_pct'] if r['gain_pct'] is not None else '':>6}%  "
            f"won {r['days_won'] if r['days_won'] is not None else '-':>3}/{r['days']}  "
            f"{r['verdict']}"
        )
    return 0


def cmd_tomorrow(args) -> int:
    tomorrow = datetime.now(ZoneInfo("Europe/Stockholm")).date() + timedelta(days=1)
    prices = model.load_prices(warehouse_from_env(), tomorrow - timedelta(days=400))
    out = model.forecast_day(prices, args.area, tomorrow)
    print(out.to_string(index=False))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="elkollen-forecast")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backtest", help="walk-forward test against the baselines")
    b.add_argument("--test-days", type=int, default=60)
    b.add_argument("--since", type=date.fromisoformat, default=date(2024, 11, 1))
    b.add_argument("--out", default="reports/forecast_backtest.json")
    b.set_defaults(func=cmd_backtest)
    t = sub.add_parser("tomorrow", help="print tomorrow's forecast for one area")
    t.add_argument("--area", choices=["SE1", "SE2", "SE3", "SE4"], required=True)
    t.set_defaults(func=cmd_tomorrow)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
