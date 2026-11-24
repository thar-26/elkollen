import pytest

from elkollen_data import upload
from elkollen_data.queries import QueryInputError


def swedish_hourly(day: str, kwh: float = 1.0, hours=range(24)) -> bytes:
    lines = ["Kund;Exempel", "Datum;Förbrukning (kWh)"]
    lines += [f"{day} {h:02d}:00;{str(kwh).replace('.', ',')}" for h in hours]
    return "\n".join(lines).encode("utf-8")


def test_parses_swedish_hourly_export():
    rows = upload.parse_consumption(swedish_hourly("2025-10-04", 1.5))
    assert len(rows) == 24 and rows[0][1] == 60 and rows[0][2] == 1.5
    assert str(rows[0][0]) == "2025-10-03 22:00:00"  # 00:00 CEST


def test_repeated_hour_on_autumn_clock_change():
    hours = ["00", "01", "02", "02", "03"]
    text = "Datum;kWh\n" + "\n".join(f"2025-10-26 {h}:00;1,0" for h in hours)
    rows = upload.parse_consumption(text.encode())
    utc = [str(r[0])[11:16] for r in rows]
    assert utc == ["22:00", "23:00", "00:00", "01:00", "02:00"]  # five distinct hours


def test_quarter_hour_export_with_comma_delimiter():
    text = "time,consumption_kwh\n" + "\n".join(
        f"2025-10-04T12:{m:02d},0.25" for m in (0, 15, 30, 45)
    )
    rows = upload.parse_consumption(text.encode())
    assert [r[1] for r in rows] == [15] * 4


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b"a;b\n1;2", "time column"),
        (b"Datum;kWh\n2025-10-04 00:00;-1", "between 0 and 100"),
        (b"Datum;kWh\nyesterday;1", "could not read"),
    ],
)
def test_bad_files_are_rejected(raw, message):
    with pytest.raises(QueryInputError, match=message):
        upload.parse_consumption(raw)


def test_paid_equals_kwh_times_price_and_flex_never_costs_more(warehouse):
    result = upload.analyse(warehouse, "SE4", swedish_hourly("2025-10-04", 2.0), 0.3).data
    price = warehouse.fetch(
        "select avg(price_ore_per_kwh) as p from marts.fct_prices_15min "
        "where price_area = 'SE4' and delivery_date = '2025-10-04'"
    )[0]["p"]
    assert result["total_kwh"] == 48
    assert result["paid_sek"] == pytest.approx(48 * price / 100, abs=0.02)
    assert result["could_have_paid_sek"] <= result["paid_sek"]
    assert result["months"][0]["month"] == "2025-10"


def test_no_prices_for_the_period_is_an_error(warehouse):
    with pytest.raises(QueryInputError, match="no prices"):
        upload.analyse(warehouse, "SE3", swedish_hourly("2030-01-01"))
