from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

from elkollen_ingest.cli import main
from elkollen_ingest.elpris import DayPrices, PricePoint
from elkollen_ingest.sinks import RAW_COLUMNS, DuckDBSink, SnowflakeSink, to_rows

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "elpris"
LOADED_AT = datetime(2026, 1, 1, 12, 0, tzinfo=UTC).replace(tzinfo=None)


def _day() -> DayPrices:
    point = PricePoint.model_validate(
        {
            "SEK_per_kWh": -0.01,
            "EUR_per_kWh": -0.001,
            "EXR": 11.0,
            "time_start": "2025-10-04T13:00:00+02:00",
            "time_end": "2025-10-04T13:15:00+02:00",
        }
    )
    return DayPrices("SE4", date(2025, 10, 4), "https://example.test", (point,), 15)


def test_to_rows_matches_raw_columns():
    rows = to_rows(_day(), "run-1", LOADED_AT)
    assert len(rows) == 1 and len(rows[0]) == len(RAW_COLUMNS)
    assert rows[0][4] == -0.01  # negative price preserved


def test_duckdb_sink_is_append_only(tmp_path):
    db = tmp_path / "t.duckdb"
    for run in ("run-1", "run-2"):
        sink = DuckDBSink(db)
        sink.write(to_rows(_day(), run, LOADED_AT))
        sink.close()
    con = duckdb.connect(str(db))
    assert con.execute(
        "select count(*), count(distinct ingest_run_id) from raw.elpris_prices"
    ).fetchone() == (2, 2)


class FakeCursor:
    def __init__(self, log):
        self.log = log

    def execute(self, sql):
        self.log.append(("execute", sql))

    def executemany(self, sql, rows):
        self.log.append(("executemany", sql, rows))

    def close(self):
        pass


class FakeConnection:
    def __init__(self):
        self.log = []

    def cursor(self):
        return FakeCursor(self.log)

    def close(self):
        self.log.append(("close",))


def test_snowflake_sink_creates_table_and_binds_parameters():
    con = FakeConnection()
    sink = SnowflakeSink(connection=con)
    assert sink.write(to_rows(_day(), "run-1", LOADED_AT)) == 1
    assert "create table if not exists raw.elpris_prices" in con.log[0][1]
    kind, sql, rows = con.log[1]
    assert kind == "executemany"
    assert sql.count("%s") == len(RAW_COLUMNS)  # values are bound, never formatted in
    assert rows[0][0] == "SE4"


def test_load_fixtures_cli(tmp_path, monkeypatch):
    db = tmp_path / "f.duckdb"
    monkeypatch.setenv("DUCKDB_PATH", str(db))
    assert main(["load-fixtures", str(FIXTURES)]) == 0
    con = duckdb.connect(str(db))
    areas, days = con.execute(
        "select count(distinct area), count(distinct delivery_date) from raw.elpris_prices"
    ).fetchone()
    assert areas == 4
    assert days == len(list(FIXTURES.glob("*_SE1.json")))
