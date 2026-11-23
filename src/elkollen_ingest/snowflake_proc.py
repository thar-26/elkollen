# Handler for the Snowflake stored procedure ELKOLLEN.RAW.INGEST_PRICES.
#
# Terraform builds the procedure body as elpris.py + "\n" + this file, so the code that
# runs inside Snowflake is exactly the client the test suite covers. Two rules follow:
#   * no `from __future__` import and no imports from the elkollen_ingest package
#     except the guarded one below (inside Snowflake there is no package, the names
#     come from elpris.py concatenated above);
#   * only packages from Snowflake's Anaconda channel (httpx, pydantic, tzdata).
# The procedure only runs where external network access is allowed (not on trial
# accounts by default). It is off unless Terraform var enable_native_ingestion = true.

import json
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

try:  # noqa: SIM105 - local development and tests
    from elkollen_ingest.elpris import (
        AREAS,
        DEFAULT_USER_AGENT,
        DayPrices,
        ElprisClient,
        parse_day,
    )
except ImportError:  # inside Snowflake: defined by elpris.py, concatenated above
    pass

RAW_TABLE = "RAW.ELPRIS_PRICES"
PROC_RAW_COLUMNS = (
    "AREA",
    "DELIVERY_DATE",
    "TIME_START",
    "TIME_END",
    "SEK_PER_KWH",
    "EUR_PER_KWH",
    "EXR",
    "SOURCE_URL",
    "INGEST_RUN_ID",
    "LOADED_AT",
)
MAX_DAYS_BACK = 31


def proc_rows(day: "DayPrices", run_id: str, loaded_at: datetime) -> list[tuple]:
    return [
        (
            day.area,
            day.delivery_date,
            p.time_start,
            p.time_end,
            p.sek_per_kwh,
            p.eur_per_kwh,
            p.exr,
            day.source_url,
            run_id,
            loaded_at,
        )
        for p in day.points
    ]


def run(session, days_back: int = 0, days_ahead: int = 1, today=None, client=None) -> str:
    """Fetch [today - days_back, today + days_ahead] for all areas and append to RAW.

    Days that are not published yet (404) are skipped. Days that fail validation are
    skipped too, the good days are still written, and the call then raises so the
    task run is marked failed and shows up in TASK_HISTORY.
    """
    if not 0 <= days_back <= MAX_DAYS_BACK:
        raise ValueError(f"days_back must be between 0 and {MAX_DAYS_BACK}")
    if days_ahead not in (0, 1):
        raise ValueError("days_ahead must be 0 or 1")

    today = today or datetime.now(ZoneInfo("Europe/Stockholm")).date()
    run_id = f"sf-proc-{uuid.uuid4()}"
    loaded_at = datetime.now(UTC).replace(tzinfo=None)
    rows: list[tuple] = []
    missing: list[str] = []
    failed: list[str] = []

    own_client = client is None
    client = client or ElprisClient(user_agent=DEFAULT_USER_AGENT + " (snowflake-task)")
    try:
        for offset in range(-days_back, days_ahead + 1):
            day = today + timedelta(days=offset)
            for area in AREAS:
                url, payload = client.fetch_raw(area, day)
                if payload is None:
                    missing.append(f"{area} {day}")
                    continue
                try:
                    prices = parse_day(area, day, url, payload)
                except ValueError as exc:  # DayValidationError and pydantic errors
                    failed.append(f"{area} {day}: {exc}")
                    continue
                rows.extend(proc_rows(prices, run_id, loaded_at))
    finally:
        if own_client:
            client.close()

    if rows:
        frame = session.create_dataframe(rows, schema=list(PROC_RAW_COLUMNS))
        frame.write.mode("append").save_as_table(RAW_TABLE, column_order="name")

    summary = json.dumps(
        {"run_id": run_id, "rows": len(rows), "not_published": missing, "failed": failed}
    )
    if failed:
        raise RuntimeError(summary)
    return summary
