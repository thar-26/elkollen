"""Live checks on a real Snowflake account (opt-in, like test_least_privilege.py):

* masking and row access policies work for the app's READER role;
* the shared query layer runs unchanged on Snowflake and gives the same answers as on
  DuckDB.

Needs: dbt built on Snowflake, and `elkollen-ingest synthetic-consumption --sink
snowflake --with-deleted-user` covering 2025-09-29..2025-10-05.
    RUN_SNOWFLAKE_TESTS=1 pytest tests/snowflake
"""

import os
from datetime import UTC, date, datetime

import pytest

from tests.snowflake.test_least_privilege import connect, run

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_SNOWFLAKE_TESTS") != "1",
    reason="set RUN_SNOWFLAKE_TESTS=1 and the ELKOLLEN_SF_* variables to run",
)

DB = os.environ.get("ELKOLLEN_SF_DATABASE", "ELKOLLEN")
WEEK = (date(2025, 9, 29), date(2025, 10, 5))


@pytest.fixture(scope="module")
def reader():
    con = connect("READER")
    yield con
    con.close()


@pytest.fixture(scope="module")
def transformer():
    con = connect("TRANSFORMER")
    yield con
    con.close()


# ------------------------------------------------------------------ privacy policies


def test_reader_sees_masked_meter_ids_and_addresses(reader):
    rows = run(reader, f"select meter_id, address from {DB}.marts.dim_app_users")
    assert rows, "no users visible"
    for meter_id, address in rows:
        assert meter_id.startswith("****") and len(meter_id) == 8
        assert address.startswith("****")


def test_transformer_sees_full_values(transformer):
    rows = run(transformer, f"select meter_id from {DB}.marts.dim_app_users")
    assert all(not m.startswith("****") and len(m) == 18 for (m,) in rows)


def test_deleted_user_is_hidden_from_reader_but_kept_for_transformer(reader, transformer):
    users = {u for (u,) in run(reader, f"select user_id from {DB}.marts.dim_app_users")}
    assert "demo-deleted" not in users and {"demo-anna", "demo-erik"} <= users
    hidden = run(
        reader,
        f"select count(*) from {DB}.marts.fct_consumption_15min where user_id = 'demo-deleted'",
    )[0][0]
    assert hidden == 0
    kept = run(
        transformer,
        f"select count(*) from {DB}.marts.fct_consumption_15min where user_id = 'demo-deleted'",
    )[0][0]
    assert kept > 0  # still there until purged; just invisible to the app


def test_policies_are_attached(transformer):
    refs = run(
        transformer,
        f"""select policy_name, ref_column_name
            from table({DB}.information_schema.policy_references(
                ref_entity_name => '{DB}.MARTS.DIM_APP_USERS', ref_entity_domain => 'table'))""",
    )
    names = {(p.upper(), (c or "").upper()) for p, c in refs}
    assert ("MASK_PII", "METER_ID") in names and ("MASK_PII", "ADDRESS") in names
    assert any(p == "RAP_ACTIVE_USER_STATUS" for p, _ in names)


# ------------------------------------------------------------------ query layer on Snowflake


@pytest.fixture(scope="module")
def wh():
    from elkollen_data.warehouse import SnowflakeWarehouse

    return SnowflakeWarehouse()


def test_get_prices_on_snowflake(wh):
    from elkollen_data import queries

    r = queries.get_prices(wh, "SE3", date(2025, 10, 26), date(2025, 10, 26))
    assert r.data["summary"]["n_intervals"] == 100


def test_cheapest_window_on_snowflake(wh):
    from elkollen_data import queries

    r = queries.cheapest_window(wh, "SE4", date(2025, 10, 4), 60)
    assert r.data["cheapest"]["avg_ore_per_kwh"] <= r.data["day_avg_ore_per_kwh"]


def test_explain_spike_on_snowflake(wh):
    from elkollen_data import queries

    r = queries.explain_spike(wh, "SE1", datetime(2025, 10, 2, 16, 45, tzinfo=UTC))
    assert r.data["interval"]["price_ore_per_kwh"] == pytest.approx(-104.304)


def test_per_user_queries_on_snowflake(wh):
    from elkollen_data import queries

    anna = queries.cost_of_my_usage(wh, "demo-anna", *WEEK).data
    erik = queries.cost_of_my_usage(wh, "demo-erik", *WEEK).data
    gone = queries.cost_of_my_usage(wh, "demo-deleted", *WEEK).data
    assert anna["total_kwh"] > 0 and erik["total_kwh"] > anna["total_kwh"]
    assert gone["total_kwh"] == 0  # row access policy hides a deleted user's rows
    plans = queries.compare_plans(wh, "demo-erik", *WEEK, fixed_price_ore_per_kwh=100).data
    assert plans["price_area"] == "SE4" and len(plans["plans"]) == 3
    assert queries.user_profile(wh, "demo-deleted") is None
