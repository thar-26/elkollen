"""Where ingested rows land. RAW is append-only: re-running a day adds rows with a new
ingest_run_id and dbt staging keeps the latest load per interval."""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Protocol

from elkollen_ingest.elpris import DayPrices

RAW_COLUMNS = (
    "area",
    "delivery_date",
    "time_start",
    "time_end",
    "sek_per_kwh",
    "eur_per_kwh",
    "exr",
    "source_url",
    "ingest_run_id",
    "loaded_at",
)

DUCKDB_DDL = """
create schema if not exists raw;
create table if not exists raw.elpris_prices (
    area           varchar   not null,
    delivery_date  date      not null,
    time_start     varchar   not null,  -- as received, ISO 8601 with offset
    time_end       varchar   not null,
    sek_per_kwh    double    not null,
    eur_per_kwh    double    not null,
    exr            double    not null,
    source_url     varchar   not null,
    ingest_run_id  varchar   not null,
    loaded_at      timestamp not null   -- UTC
);
"""

SNOWFLAKE_DDL = """
create table if not exists raw.elpris_prices (
    area           varchar        not null,
    delivery_date  date           not null,
    time_start     varchar        not null comment 'As received, ISO 8601 with offset',
    time_end       varchar        not null,
    sek_per_kwh    float          not null,
    eur_per_kwh    float          not null,
    exr            float          not null,
    source_url     varchar        not null,
    ingest_run_id  varchar        not null,
    loaded_at      timestamp_ntz  not null comment 'UTC'
) comment = 'Append-only day-ahead prices from elprisetjustnu.se (source: ENTSO-E).'
"""


def to_rows(day: DayPrices, run_id: str, loaded_at: datetime) -> list[tuple]:
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


class Sink(Protocol):
    def write(self, rows: Sequence[tuple]) -> int: ...
    def close(self) -> None: ...


# Every RAW table a sink may write, with its column order. Table names are never taken
# from user input; write_table refuses anything not listed here.
RAW_TABLES: dict[str, tuple[str, ...]] = {
    "raw.elpris_prices": RAW_COLUMNS,
    "raw.app_users": (
        "user_id",
        "display_name",
        "price_area",
        "meter_id",
        "address",
        "status",
        "is_synthetic",
        "created_at",
        "ingest_run_id",
        "loaded_at",
    ),
    "raw.consumption_readings": (
        "user_id",
        "meter_id",
        "interval_start_utc",
        "interval_minutes",
        "kwh",
        "source",
        "ingest_run_id",
        "loaded_at",
    ),
    "raw.entsoe_forecasts": (
        "area",
        "series",
        "delivery_date",
        "interval_start_utc",
        "interval_start_local",
        "resolution_minutes",
        "mw",
        "document_type",
        "ingest_run_id",
        "loaded_at",
    ),
}

ENTSOE_DDL_DUCKDB = """
create schema if not exists raw;
create table if not exists raw.entsoe_forecasts (
    area varchar not null, series varchar not null, delivery_date date not null,
    interval_start_utc timestamp not null, interval_start_local timestamp not null,
    resolution_minutes integer not null, mw double not null, document_type varchar not null,
    ingest_run_id varchar not null, loaded_at timestamp not null
);
"""

ENTSOE_DDL_SNOWFLAKE = """create table if not exists raw.entsoe_forecasts (
    area varchar not null, series varchar not null, delivery_date date not null,
    interval_start_utc timestamp_ntz not null, interval_start_local timestamp_ntz not null,
    resolution_minutes integer not null, mw float not null, document_type varchar not null,
    ingest_run_id varchar not null, loaded_at timestamp_ntz not null
) comment = 'Append-only day-ahead load, wind and solar forecasts from ENTSO-E.'"""


def entsoe_rows(points, run_id: str, loaded_at: datetime) -> list[tuple]:
    return [
        (
            p.area,
            p.series,
            p.delivery_date,
            p.start_utc,
            p.start_local,
            p.resolution_minutes,
            p.mw,
            p.document_type,
            run_id,
            loaded_at,
        )
        for p in points
    ]


APP_DDL_DUCKDB = """
create schema if not exists raw;
create table if not exists raw.app_users (
    user_id varchar not null, display_name varchar, price_area varchar not null,
    meter_id varchar, address varchar, status varchar not null, is_synthetic boolean not null,
    created_at timestamp not null, ingest_run_id varchar not null, loaded_at timestamp not null
);
create table if not exists raw.consumption_readings (
    user_id varchar not null, meter_id varchar, interval_start_utc timestamp not null,
    interval_minutes integer not null, kwh double not null, source varchar not null,
    ingest_run_id varchar not null, loaded_at timestamp not null
);
"""

APP_DDL_SNOWFLAKE = (
    """create table if not exists raw.app_users (
    user_id varchar not null, display_name varchar, price_area varchar not null,
    meter_id varchar, address varchar, status varchar not null, is_synthetic boolean not null,
    created_at timestamp_ntz not null, ingest_run_id varchar not null,
    loaded_at timestamp_ntz not null
) comment = 'App users. Public demo holds synthetic users only.'""",
    """create table if not exists raw.consumption_readings (
    user_id varchar not null, meter_id varchar, interval_start_utc timestamp_ntz not null,
    interval_minutes integer not null, kwh float not null, source varchar not null,
    ingest_run_id varchar not null, loaded_at timestamp_ntz not null
) comment = 'Per-user consumption. Public demo holds synthetic readings only.'""",
)


def _insert_sql(table: str, placeholder: str) -> str:
    if table not in RAW_TABLES:
        raise ValueError(f"refusing to write to unknown table {table!r}")
    columns = RAW_TABLES[table]
    values = ", ".join(placeholder for _ in columns)
    return f"insert into {table} ({', '.join(columns)}) values ({values})"  # noqa: S608 - allowlisted


class DuckDBSink:
    """Local development and CI. Same table shapes as Snowflake RAW."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        import duckdb

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect(str(path))
        self._con.execute(DUCKDB_DDL)
        self._con.execute(APP_DDL_DUCKDB)
        self._con.execute(ENTSOE_DDL_DUCKDB)

    def write_table(self, table: str, rows: Sequence[tuple]) -> int:
        if not rows:
            return 0
        self._con.executemany(_insert_sql(table, "?"), rows)
        return len(rows)

    def write(self, rows: Sequence[tuple]) -> int:
        return self.write_table("raw.elpris_prices", rows)

    def close(self) -> None:
        self._con.close()


class SnowflakeSink:
    """Writes to <database>.RAW.ELPRIS_PRICES as the LOADER service user (key-pair auth).

    Connection settings come from environment variables only (see .env.example).
    """

    def __init__(self, connection=None) -> None:
        self._con = connection if connection is not None else self._connect_from_env()
        cur = self._con.cursor()
        try:
            cur.execute(SNOWFLAKE_DDL)
            for ddl in (*APP_DDL_SNOWFLAKE, ENTSOE_DDL_SNOWFLAKE):
                cur.execute(ddl)
        finally:
            cur.close()

    @staticmethod
    def _connect_from_env():
        import snowflake.connector

        def required(name: str) -> str:
            value = os.environ.get(name)
            if not value:
                raise RuntimeError(f"environment variable {name} is not set (see .env.example)")
            return value

        return snowflake.connector.connect(
            account=required("ELKOLLEN_SF_ACCOUNT"),
            user=required("ELKOLLEN_SF_LOADER_USER"),
            private_key_file=required("ELKOLLEN_SF_LOADER_PRIVATE_KEY_PATH"),
            authenticator="SNOWFLAKE_JWT",
            role=os.environ.get("ELKOLLEN_SF_LOADER_ROLE", "ELKOLLEN_LOADER"),
            warehouse=os.environ.get("ELKOLLEN_SF_WAREHOUSE", "ELKOLLEN_WH"),
            database=os.environ.get("ELKOLLEN_SF_DATABASE", "ELKOLLEN"),
            schema="RAW",
            application="elkollen-ingest",
        )

    def write_table(self, table: str, rows: Sequence[tuple]) -> int:
        if not rows:
            return 0
        cur = self._con.cursor()
        try:
            cur.executemany(_insert_sql(table, "%s"), list(rows))
        finally:
            cur.close()
        return len(rows)

    def write(self, rows: Sequence[tuple]) -> int:
        return self.write_table("raw.elpris_prices", rows)

    def close(self) -> None:
        self._con.close()


def iter_chunks(rows: Iterable[tuple], size: int = 5000) -> Iterable[list[tuple]]:
    chunk: list[tuple] = []
    for row in rows:
        chunk.append(row)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk
