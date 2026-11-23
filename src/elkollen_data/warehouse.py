"""Read-only warehouse connections.

Queries are written once, with named parameters (`:name`), and run unchanged on DuckDB
(local development, CI, tests) or Snowflake (production, as the READER service user).
Values are always bound as parameters, never formatted into SQL text.
"""

import os
import re
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

_PARAM = re.compile(r"(?<!:):([a-zA-Z_][a-zA-Z0-9_]*)")


class Warehouse(Protocol):
    name: str

    def fetch(self, sql: str, params: Mapping[str, Any] | None = None) -> list[dict]: ...


def _to_duckdb(sql: str) -> str:
    return _PARAM.sub(r"$\1", sql)


def _to_pyformat(sql: str) -> str:
    return _PARAM.sub(r"%(\1)s", sql.replace("%", "%%"))


class DuckDBWarehouse:
    """Opens the DuckDB file read-only for each query, so ingestion can keep writing."""

    name = "duckdb"

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(
                f"{self.path} not found: run elkollen-ingest and dbt build first"
            )

    def fetch(self, sql: str, params: Mapping[str, Any] | None = None) -> list[dict]:
        import duckdb

        con = duckdb.connect(str(self.path), read_only=True)
        try:
            cur = con.execute(_to_duckdb(sql), dict(params or {}))
            columns = [d[0].lower() for d in cur.description]
            return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]
        finally:
            con.close()


class SnowflakeWarehouse:
    """Connects as the READER service user (key-pair auth). Reads MARTS only."""

    name = "snowflake"

    def __init__(self, connection=None) -> None:
        self._con = connection
        self._lock = threading.Lock()

    def _connection(self):
        if self._con is None:
            import snowflake.connector

            def required(key: str) -> str:
                value = os.environ.get(key)
                if not value:
                    raise RuntimeError(f"environment variable {key} is not set (see .env.example)")
                return value

            self._con = snowflake.connector.connect(
                account=required("ELKOLLEN_SF_ACCOUNT"),
                user=required("ELKOLLEN_SF_READER_USER"),
                private_key_file=required("ELKOLLEN_SF_READER_PRIVATE_KEY_PATH"),
                authenticator="SNOWFLAKE_JWT",
                role=os.environ.get("ELKOLLEN_SF_READER_ROLE", "ELKOLLEN_READER"),
                warehouse=os.environ.get("ELKOLLEN_SF_WAREHOUSE", "ELKOLLEN_WH"),
                database=os.environ.get("ELKOLLEN_SF_DATABASE", "ELKOLLEN"),
                application="elkollen-api",
                client_session_keep_alive=False,
            )
        return self._con

    def fetch(self, sql: str, params: Mapping[str, Any] | None = None) -> list[dict]:
        with self._lock:
            cur = self._connection().cursor()
            try:
                cur.execute(_to_pyformat(sql), dict(params or {}))
                columns = [d[0].lower() for d in cur.description]
                return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]
            finally:
                cur.close()


def warehouse_from_env() -> Warehouse:
    kind = os.environ.get("ELKOLLEN_WAREHOUSE", "duckdb")
    if kind == "duckdb":
        return DuckDBWarehouse(os.environ.get("DUCKDB_PATH", "data/elkollen.duckdb"))
    if kind == "snowflake":
        return SnowflakeWarehouse()
    raise ValueError(f"ELKOLLEN_WAREHOUSE must be duckdb or snowflake, not {kind!r}")
