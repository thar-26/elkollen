import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from elkollen_ingest import snowflake_proc
from elkollen_ingest.elpris import day_url, parse_day
from elkollen_ingest.sinks import RAW_COLUMNS, to_rows

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures" / "elpris"
# Same files, same order and same separator as infra/terraform/native_ingestion.tf
PROC_SOURCES = [
    ROOT / "src" / "elkollen_ingest" / "elpris.py",
    ROOT / "src" / "elkollen_ingest" / "snowflake_proc.py",
]


class FakeWriter:
    def __init__(self, log):
        self.log = log

    def mode(self, mode):
        self.log.append(("mode", mode))
        return self

    def save_as_table(self, table, column_order):
        self.log.append(("save_as_table", table, column_order))


class FakeFrame:
    def __init__(self, log):
        self.write = FakeWriter(log)


class FakeSession:
    """Records what the handler asks Snowpark to do."""

    def __init__(self):
        self.log = []
        self.rows = []
        self.schema = None

    def create_dataframe(self, rows, schema):
        self.rows, self.schema = rows, schema
        return FakeFrame(self.log)


class FixtureClient:
    """Serves saved API responses; unknown days answer 404 (not published)."""

    def __init__(self, broken=()):
        self.broken = set(broken)

    def fetch_raw(self, area, day):
        path = FIXTURES / f"{day.isoformat()}_{area}.json"
        if (area, day) in self.broken:
            return day_url(area, day), [{"SEK_per_kWh": "not a number"}]
        if not path.exists():
            return day_url(area, day), None
        return day_url(area, day), json.loads(path.read_text(encoding="utf-8"))

    def close(self):
        pass


def test_writes_all_areas_for_today_and_tomorrow():
    session = FakeSession()
    out = json.loads(
        snowflake_proc.run(session, 0, 1, today=date(2025, 10, 26), client=FixtureClient())
    )
    # 2025-10-26 is the 100-interval fall-back day, 2025-10-27 a normal 96-interval day
    assert out["rows"] == 4 * 100 + 4 * 96
    assert out["failed"] == [] and out["not_published"] == []
    assert session.log == [
        ("mode", "append"),
        ("save_as_table", "RAW.ELPRIS_PRICES", "name"),
    ]


def test_tomorrow_not_published_is_not_an_error():
    session = FakeSession()
    # 2025-10-28 is not in the fixtures, so it behaves like "before 13:00"
    out = json.loads(
        snowflake_proc.run(session, 0, 1, today=date(2025, 10, 27), client=FixtureClient())
    )
    assert out["rows"] == 4 * 96
    assert len(out["not_published"]) == 4


def test_bad_day_is_skipped_good_days_written_then_run_fails():
    session = FakeSession()
    client = FixtureClient(broken={("SE2", date(2025, 10, 27))})
    with pytest.raises(RuntimeError, match="SE2 2025-10-27"):
        snowflake_proc.run(session, 0, 1, today=date(2025, 10, 26), client=client)
    assert len(session.rows) == 4 * 100 + 3 * 96  # good days still land in RAW


@pytest.mark.parametrize(("back", "ahead"), [(-1, 1), (32, 1), (0, 2)])
def test_rejects_out_of_range_arguments(back, ahead):
    with pytest.raises(ValueError):
        snowflake_proc.run(FakeSession(), back, ahead, client=FixtureClient())


def test_rows_match_the_cli_sink_exactly():
    assert [c.lower() for c in snowflake_proc.PROC_RAW_COLUMNS] == list(RAW_COLUMNS)
    payload = json.loads((FIXTURES / "2025-10-04_SE4.json").read_text(encoding="utf-8"))
    day = parse_day("SE4", date(2025, 10, 4), "u", payload)
    loaded_at = datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None)
    assert snowflake_proc.proc_rows(day, "r", loaded_at) == to_rows(day, "r", loaded_at)


def test_concatenated_procedure_body_runs_without_the_package(monkeypatch):
    """What Terraform ships: elpris.py + snowflake_proc.py as one module, no package."""
    source = "\n".join(p.read_text(encoding="utf-8") for p in PROC_SOURCES)
    # Make the guarded import fail, as it does inside Snowflake.
    monkeypatch.setitem(sys.modules, "elkollen_ingest.elpris", None)
    namespace = {"__name__": "ingest_prices_procedure"}
    exec(compile(source, "INGEST_PRICES", "exec"), namespace)  # noqa: S102 - our own source

    assert namespace["ElprisClient"].__module__ == "ingest_prices_procedure"
    session = FakeSession()
    out = json.loads(
        namespace["run"](session, 0, 0, today=date(2026, 3, 29), client=FixtureClient())
    )
    assert out["rows"] == 4 * 92  # spring-forward day, 15-minute era
