"""Command line entry point.

elkollen-ingest prices                      # today + tomorrow, all areas, DuckDB
elkollen-ingest prices --start 2025-09-28 --end 2025-10-03 --areas SE3
elkollen-ingest prices --sink snowflake     # needs ELKOLLEN_SF_* env vars
elkollen-ingest prices ... --save-raw fixtures/elpris   # also keep the raw JSON
elkollen-ingest load-fixtures fixtures/elpris           # offline: JSON files -> sink
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from elkollen_ingest import AREAS
from elkollen_ingest.elpris import DEFAULT_USER_AGENT, DayValidationError, ElprisClient, parse_day
from elkollen_ingest.sinks import DuckDBSink, Sink, SnowflakeSink, to_rows

log = logging.getLogger("elkollen_ingest")
STOCKHOLM = ZoneInfo("Europe/Stockholm")
BATCH_ROWS = 5000
MAX_DAYS_PER_RUN = 1100  # ~3 years x 4 areas ≈ 4400 requests; protects the free API


def today_stockholm() -> date:
    return datetime.now(STOCKHOLM).date()


def daterange(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def parse_areas(value: str) -> list[str]:
    areas = [a.strip().upper() for a in value.split(",") if a.strip()]
    unknown = sorted(set(areas) - set(AREAS))
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown areas {unknown}; choose from {AREAS}")
    return areas


def make_sink(kind: str) -> Sink:
    if kind == "duckdb":
        return DuckDBSink(os.environ.get("DUCKDB_PATH", "data/elkollen.duckdb"))
    if kind == "snowflake":
        return SnowflakeSink()
    raise ValueError(kind)


def cmd_prices(args: argparse.Namespace) -> int:
    start = args.start or today_stockholm()
    end = args.end or today_stockholm() + timedelta(days=1)
    if end < start:
        log.error("--end is before --start")
        return 2
    if (end - start).days + 1 > MAX_DAYS_PER_RUN:
        log.error("refusing to fetch more than %s days in one run", MAX_DAYS_PER_RUN)
        return 2

    run_id = str(uuid.uuid4())
    loaded_at = datetime.now(UTC).replace(tzinfo=None)
    save_dir = Path(args.save_raw) if args.save_raw else None
    written, missing, failed = 0, [], []

    sink = make_sink(args.sink)
    user_agent = os.environ.get("ELKOLLEN_USER_AGENT", DEFAULT_USER_AGENT)
    # Rows are written in batches: one INSERT per ~5000 rows instead of one per area-day,
    # so a long backfill keeps the Snowflake warehouse awake for minutes, not an hour.
    buffer: list[tuple] = []
    try:
        with ElprisClient(user_agent=user_agent) as client:
            for day in daterange(start, end):
                for area in args.areas:
                    url, payload = client.fetch_raw(area, day)
                    if payload is None:
                        missing.append(f"{area} {day}")
                        continue
                    try:
                        prices = parse_day(area, day, url, payload)
                    except (DayValidationError, ValueError) as exc:
                        failed.append(f"{area} {day}: {exc}")
                        continue
                    if save_dir:
                        save_dir.mkdir(parents=True, exist_ok=True)
                        (save_dir / f"{day.isoformat()}_{area}.json").write_text(
                            json.dumps(payload, indent=0), encoding="utf-8"
                        )
                    buffer.extend(to_rows(prices, run_id, loaded_at))
                    if len(buffer) >= BATCH_ROWS:
                        written += sink.write(buffer)
                        buffer = []
    finally:
        try:
            if buffer:  # keep what was fetched even if a later day failed
                written += sink.write(buffer)
        finally:
            sink.close()

    log.info("run %s: wrote %s rows to %s", run_id, written, args.sink)
    if missing:
        log.info("not published yet (404): %s", ", ".join(missing))
    for f in failed:
        log.error("validation failed, day skipped: %s", f)
    return 1 if failed else 0


def cmd_load_fixtures(args: argparse.Namespace) -> int:
    """Load saved API responses (<YYYY-MM-DD>_<AREA>.json) without touching the network."""
    run_id = f"fixtures-{uuid.uuid4()}"
    loaded_at = datetime.now(UTC).replace(tzinfo=None)
    files = sorted(Path(args.directory).glob("*.json"))
    if not files:
        log.error("no fixture files in %s", args.directory)
        return 2
    sink = make_sink(args.sink)
    written = 0
    try:
        for f in files:
            day_str, area = f.stem.split("_")
            day = date.fromisoformat(day_str)
            payload = json.loads(f.read_text(encoding="utf-8"))
            prices = parse_day(area, day, f"fixture://{f.name}", payload)
            written += sink.write(to_rows(prices, run_id, loaded_at))
    finally:
        sink.close()
    log.info("loaded %s rows from %s files", written, len(files))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="elkollen-ingest")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("prices", help="fetch day-ahead prices from elprisetjustnu.se")
    p.add_argument("--start", type=date.fromisoformat, help="first delivery date (default today)")
    p.add_argument("--end", type=date.fromisoformat, help="last delivery date (default tomorrow)")
    p.add_argument("--areas", type=parse_areas, default=list(AREAS))
    p.add_argument("--sink", choices=["duckdb", "snowflake"], default="duckdb")
    p.add_argument("--save-raw", metavar="DIR", help="also save each raw JSON response here")
    p.set_defaults(func=cmd_prices)

    f = sub.add_parser("load-fixtures", help="load saved JSON responses into a sink (offline)")
    f.add_argument("directory")
    f.add_argument("--sink", choices=["duckdb", "snowflake"], default="duckdb")
    f.set_defaults(func=cmd_load_fixtures)

    s = sub.add_parser(
        "synthetic-consumption", help="write invented demo users and 15-minute readings"
    )
    s.add_argument("--start", type=date.fromisoformat, required=True)
    s.add_argument("--end", type=date.fromisoformat, required=True)
    s.add_argument("--sink", choices=["duckdb", "snowflake"], default="duckdb")
    s.add_argument(
        "--with-deleted-user",
        action="store_true",
        help="also load a demo user with status 'deleted' (to verify deletion hiding)",
    )
    s.set_defaults(func=cmd_synthetic)
    return parser


def cmd_synthetic(args: argparse.Namespace) -> int:
    from elkollen_ingest.sinks import iter_chunks
    from elkollen_ingest.synthetic import (
        DELETED_DEMO_USER,
        DEMO_USERS,
        consumption_rows,
        user_rows,
    )

    if args.end < args.start or (args.end - args.start).days > 800:
        log.error("give --start <= --end, at most 800 days apart")
        return 2
    run_id = f"synthetic-{uuid.uuid4()}"
    loaded_at = datetime.now(UTC).replace(tzinfo=None)
    people = list(DEMO_USERS)
    rows = user_rows(run_id, loaded_at)
    if getattr(args, "with_deleted_user", False):
        people.append(DELETED_DEMO_USER)
        rows += user_rows(run_id, loaded_at, users=(DELETED_DEMO_USER,), status="deleted")
    sink = make_sink(args.sink)
    try:
        users = sink.write_table("raw.app_users", rows)
        readings = 0
        readings_iter = consumption_rows(args.start, args.end, run_id, loaded_at, tuple(people))
        for chunk in iter_chunks(readings_iter):
            readings += sink.write_table("raw.consumption_readings", chunk)
    finally:
        sink.close()
    log.info("wrote %s synthetic users and %s readings to %s", users, readings, args.sink)
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
