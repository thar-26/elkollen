# ruff: noqa: DTZ001 - the pipeline stores naive UTC, so tests compare naive UTC
"""ENTSO-E parser and client. All XML here and in fixtures/entsoe is invented."""

from collections import Counter
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest

from elkollen_ingest.entsoe import EntsoeClient, EntsoeError, local_day_bounds, parse_document

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "entsoe"
SECRET = "00000000-test-token-not-real-000000000"


def doc(points: str, *, doc_type="A65", curve="A03", unit="MAW", psr="", res="PT15M"):
    psr_xml = f"<MktPSRType><psrType>{psr}</psrType></MktPSRType>" if psr else ""
    return f"""<GL_MarketDocument xmlns="urn:x">
  <type>{doc_type}</type>
  <TimeSeries>
    <quantity_Measure_Unit.name>{unit}</quantity_Measure_Unit.name>
    <curveType>{curve}</curveType>{psr_xml}
    <Period>
      <timeInterval><start>2026-11-22T23:00Z</start><end>2026-11-23T00:00Z</end></timeInterval>
      <resolution>{res}</resolution>
      {points}
    </Period>
  </TimeSeries>
</GL_MarketDocument>"""


def pts(*pairs) -> str:
    return "".join(
        f"<Point><position>{p}</position><quantity>{q}</quantity></Point>" for p, q in pairs
    )


def test_a03_fills_left_out_positions_with_the_previous_value():
    out = parse_document("SE3", doc(pts((1, 100), (3, 300))))
    assert [p.mw for p in out] == [100, 100, 300, 300]
    assert out[0].start_utc == datetime(2026, 11, 22, 23, 0)
    assert out[0].delivery_date == date(2026, 11, 23)  # 00:00 local
    assert {p.resolution_minutes for p in out} == {15}


def test_regular_curve_with_a_gap_is_refused():
    with pytest.raises(EntsoeError, match="missing"):
        parse_document("SE3", doc(pts((1, 1), (3, 3), (4, 4)), curve="A01"))


@pytest.mark.parametrize(
    "points, kwargs, message",
    [
        (pts((1, 1)), {"unit": "KWH"}, "MW"),
        (pts((1, -5)), {}, "implausible"),
        (pts((1, 1), (9, 1)), {}, "outside"),
        (pts((2, 1)), {}, "position 1"),
        (pts((1, 1)), {"res": "P1D"}, "resolution"),
        (pts((1, 1)), {"doc_type": "A44"}, "document type"),
    ],
)
def test_bad_documents_are_refused(points, kwargs, message):
    with pytest.raises(EntsoeError, match=message):
        parse_document("SE3", doc(points, **kwargs))


def test_acknowledgement_means_no_data():
    ack = (
        '<Acknowledgement_MarketDocument xmlns="urn:x"><Reason>'
        "<text>No matching data found</text></Reason></Acknowledgement_MarketDocument>"
    )
    assert parse_document("SE3", ack) == []


def test_unused_production_types_are_skipped():
    assert parse_document("SE3", doc(pts((1, 5)), doc_type="A69", psr="B14")) == []
    wind = parse_document("SE3", doc(pts((1, 5)), doc_type="A69", psr="B19"))
    assert {p.series for p in wind} == {"wind_onshore_forecast"}


def test_fixture_days_have_the_clocks_number_of_intervals():
    counts = Counter()
    for f in FIXTURES.glob("*.xml"):
        for p in parse_document("SE3", f.read_bytes()):
            counts[(p.delivery_date, p.series, p.resolution_minutes)] += 1
    assert counts[(date(2025, 10, 1), "load_forecast", 15)] == 96
    assert counts[(date(2025, 10, 26), "load_forecast", 60)] == 25  # fall-back day
    assert counts[(date(2025, 10, 26), "wind_onshore_forecast", 15)] == 100
    assert counts[(date(2025, 10, 1), "solar_forecast", 15)] == 96


def test_local_day_bounds_follow_daylight_saving():
    assert local_day_bounds(date(2025, 10, 26), date(2025, 10, 26)) == (
        datetime(2025, 10, 25, 22),
        datetime(2025, 10, 26, 23),
    )
    assert local_day_bounds(date(2026, 3, 29), date(2026, 3, 29)) == (
        datetime(2026, 3, 28, 23),
        datetime(2026, 3, 29, 22),
    )


def client_with(handler) -> EntsoeClient:
    client = EntsoeClient(SECRET, pause_s=0, retries=1)
    client._http = httpx.Client(transport=httpx.MockTransport(handler))
    return client


def test_token_never_appears_in_errors(monkeypatch):
    monkeypatch.setattr("elkollen_ingest.entsoe.time.sleep", lambda s: None)

    def boom(request):
        raise httpx.ConnectError(f"cannot reach {request.url}", request=request)

    with client_with(boom) as c, pytest.raises(EntsoeError) as err:
        c.fetch("SE3", date(2026, 11, 23), date(2026, 11, 23))
    assert SECRET not in str(err.value)
    assert "network error" in str(err.value)


@pytest.mark.parametrize("status", [401, 403])
def test_refused_token_stops_without_retry(monkeypatch, status):
    calls = []
    monkeypatch.setattr("elkollen_ingest.entsoe.time.sleep", lambda s: None)

    def refuse(request):
        calls.append(request)
        return httpx.Response(status, text="Unauthorized")

    with client_with(refuse) as c, pytest.raises(EntsoeError, match="token refused"):
        c.fetch("SE3", date(2026, 11, 23), date(2026, 11, 23))
    assert len(calls) == 1


def test_fetch_sends_both_documents_and_keeps_only_the_asked_days(monkeypatch):
    monkeypatch.setattr("elkollen_ingest.entsoe.time.sleep", lambda s: None)
    seen = []

    def answer(request):
        seen.append(dict(request.url.params))
        name = "load" if request.url.params["documentType"] == "A65" else "generation"
        return httpx.Response(200, text=(FIXTURES / f"SE3_{name}_2025-10-01.xml").read_text())

    with client_with(answer) as c:
        out = c.fetch("SE3", date(2025, 10, 1), date(2025, 10, 1))
    assert [s["documentType"] for s in seen] == ["A65", "A69"]
    assert seen[0]["periodStart"] == "202509302200"
    assert seen[0]["securityToken"] == SECRET  # sent to the API, and only there
    assert Counter(p.series for p in out) == {
        "load_forecast": 96,
        "solar_forecast": 96,
        "wind_onshore_forecast": 96,
    }


def test_too_long_or_unknown_requests_are_refused():
    with client_with(lambda r: httpx.Response(500)) as c:
        with pytest.raises(EntsoeError, match="31 days"):
            c.fetch("SE3", date(2026, 1, 1), date(2026, 3, 1))
        with pytest.raises(EntsoeError, match="unknown area"):
            c.fetch("NO1", date(2026, 1, 1), date(2026, 1, 1))


def test_cli_never_logs_the_token(monkeypatch, tmp_path, caplog):
    import logging

    from elkollen_ingest import cli

    monkeypatch.setenv("ENTSOE_API_TOKEN", SECRET)
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "t.duckdb"))
    monkeypatch.setattr("elkollen_ingest.entsoe.time.sleep", lambda s: None)
    real_client = httpx.Client

    def answer(request):
        name = "load" if request.url.params["documentType"] == "A65" else "generation"
        return httpx.Response(200, text=(FIXTURES / f"SE3_{name}_2025-10-01.xml").read_text())

    monkeypatch.setattr(
        "elkollen_ingest.entsoe.httpx.Client",
        lambda **kw: real_client(transport=httpx.MockTransport(answer), **kw),
    )
    with caplog.at_level(logging.DEBUG):
        code = cli.main(
            ["entsoe", "--start", "2025-10-01", "--end", "2025-10-01", "--areas", "SE3"]
        )
    assert code == 0
    assert "wrote 288 ENTSO-E rows" in caplog.text
    assert SECRET not in caplog.text


def test_missing_token_is_a_clear_error():
    with pytest.raises(EntsoeError, match="ENTSOE_API_TOKEN"):
        EntsoeClient("")
