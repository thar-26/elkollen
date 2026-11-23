"""Shared fixtures: a real DuckDB warehouse built exactly like CI builds it.

Real price fixtures + the synthetic demo users + one deleted user, then `dbt build`.
Built once per test session in a temp folder (about 20 seconds).
"""

import os
import shutil
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONTINUITY = '{price_continuity_start: "2025-09-29", price_continuity_end: "2025-10-05"}'
DELETED_USER = "demo-deleted"


@pytest.fixture(scope="session")
def warehouse_path(tmp_path_factory) -> Path:
    from elkollen_ingest.cli import main as ingest
    from elkollen_ingest.sinks import DuckDBSink
    from elkollen_ingest.synthetic import SyntheticUser, consumption_rows, user_rows

    tmp = tmp_path_factory.mktemp("warehouse")
    db = tmp / "test.duckdb"
    old = {k: os.environ.get(k) for k in ("DUCKDB_PATH", "DBT_TARGET")}
    os.environ["DUCKDB_PATH"] = str(db)
    os.environ["DBT_TARGET"] = "local"
    try:
        assert ingest(["load-fixtures", str(ROOT / "fixtures" / "elpris")]) == 0
        for start, end in (("2025-09-29", "2025-10-05"), ("2025-10-25", "2025-10-27")):
            assert ingest(["synthetic-consumption", "--start", start, "--end", end]) == 0

        # A user who asked to be deleted: their rows must be invisible to the app.
        gone = SyntheticUser(
            DELETED_USER,
            "Deleted (demo)",
            "SE3",
            "735999000000000303",
            "Borttagen 3, Stockholm",
            "apartment",
        )
        loaded = datetime.now(UTC).replace(tzinfo=None)
        sink = DuckDBSink(db)
        try:
            row = list(user_rows("t", loaded, users=(gone,))[0])
            row[5] = "deleted"
            sink.write_table("raw.app_users", [tuple(row)])
            sink.write_table(
                "raw.consumption_readings",
                list(consumption_rows(date(2025, 9, 29), date(2025, 9, 30), "t", loaded, (gone,))),
            )
        finally:
            sink.close()

        # A separate process, as in CI: dbt-duckdb keeps its connection open in-process,
        # and DuckDB refuses a second (read-only) connection to the same file.
        dbt = shutil.which("dbt", path=str(Path(sys.executable).parent)) or "dbt"
        result = subprocess.run(  # noqa: S603 - fixed arguments
            [
                dbt,
                "build",
                "--project-dir",
                str(ROOT / "dbt"),
                "--profiles-dir",
                str(ROOT / "dbt"),
                "--target-path",
                str(tmp / "dbt-target"),
                "--log-path",
                str(tmp / "dbt-logs"),
                "--exclude",
                "tag:live",
                "--vars",
                CONTINUITY,
                "--quiet",
            ],
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"dbt build failed:\n{result.stdout}\n{result.stderr}"
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return db


@pytest.fixture(scope="session")
def warehouse(warehouse_path):
    from elkollen_data.warehouse import DuckDBWarehouse

    return DuckDBWarehouse(warehouse_path)
