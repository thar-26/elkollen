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


class DuckDBSink:
    """Local development and CI. Same table shape as Snowflake RAW."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        import duckdb

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect(str(path))
        self._con.execute(DUCKDB_DDL)

    def write(self, rows: Sequence[tuple]) -> int:
        if not rows:
            return 0
        placeholders = ", ".join("?" for _ in RAW_COLUMNS)
        self._con.executemany(
            f"insert into raw.elpris_prices ({', '.join(RAW_COLUMNS)}) values ({placeholders})",  # noqa: S608 - constant column list
            rows,
        )
        return len(rows)

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

    def write(self, rows: Sequence[tuple]) -> int:
        if not rows:
            return 0
        placeholders = ", ".join("%s" for _ in RAW_COLUMNS)
        cur = self._con.cursor()
        try:
            cur.executemany(
                f"insert into raw.elpris_prices ({', '.join(RAW_COLUMNS)}) values ({placeholders})",  # noqa: S608 - constant column list
                list(rows),
            )
        finally:
            cur.close()
        return len(rows)

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
