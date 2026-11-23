"""Live checks against a real Snowflake account: each service user can do its job and
nothing more, and staging behaves on Snowflake exactly as on DuckDB.

Opt-in, because it needs credentials and wakes the warehouse for a few seconds:
    RUN_SNOWFLAKE_TESTS=1 pytest tests/snowflake
CI does not run it (no credentials there).
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_SNOWFLAKE_TESTS") != "1",
    reason="set RUN_SNOWFLAKE_TESTS=1 and the ELKOLLEN_SF_* variables to run",
)

DB = os.environ.get("ELKOLLEN_SF_DATABASE", "ELKOLLEN")
DENIED = ("does not exist or not authorized", "insufficient privileges")


def connect(kind: str):
    import snowflake.connector

    return snowflake.connector.connect(
        account=os.environ["ELKOLLEN_SF_ACCOUNT"],
        user=os.environ[f"ELKOLLEN_SF_{kind}_USER"],
        private_key_file=os.environ[f"ELKOLLEN_SF_{kind}_PRIVATE_KEY_PATH"],
        authenticator="SNOWFLAKE_JWT",
        role=f"ELKOLLEN_{kind}",
        warehouse=os.environ.get("ELKOLLEN_SF_WAREHOUSE", "ELKOLLEN_WH"),
        database=DB,
        application="elkollen-grant-tests",
    )


@pytest.fixture(scope="module", params=["LOADER", "TRANSFORMER", "READER"])
def session(request):
    con = connect(request.param)
    yield request.param, con
    con.close()


def run(con, sql: str):
    cur = con.cursor()
    try:
        return cur.execute(sql).fetchall()
    finally:
        cur.close()


def assert_denied(con, sql: str):
    import snowflake.connector

    with pytest.raises(snowflake.connector.errors.ProgrammingError) as exc:
        run(con, sql)
    assert any(word in str(exc.value).lower() for word in DENIED), str(exc.value)


# role -> (allowed statements, denied statements)
MATRIX = {
    "LOADER": (
        [f"select count(*) from {DB}.raw.elpris_prices"],
        [
            f"create table {DB}.staging.loader_should_not_create (x int)",
            f"select count(*) from {DB}.staging.stg_elpris__prices",
        ],
    ),
    "TRANSFORMER": (
        [
            f"select count(*) from {DB}.raw.elpris_prices",
            f"select count(*) from {DB}.staging.stg_elpris__prices",
        ],
        [
            f"insert into {DB}.raw.elpris_prices (area) values ('SE9')",
            f"delete from {DB}.raw.elpris_prices where 1 = 0",
        ],
    ),
    "READER": (
        [f"show tables in schema {DB}.marts"],
        [
            f"select count(*) from {DB}.raw.elpris_prices",
            f"select count(*) from {DB}.staging.stg_elpris__prices",
            f"create table {DB}.marts.reader_should_not_create (x int)",
        ],
    ),
}


def test_role_can_do_its_job(session):
    role, con = session
    for sql in MATRIX[role][0]:
        run(con, sql)


def test_role_cannot_do_anything_else(session):
    role, con = session
    for sql in MATRIX[role][1]:
        assert_denied(con, sql)


def test_staging_dst_counts_on_snowflake():
    con = connect("TRANSFORMER")
    try:
        rows = dict(
            run(
                con,
                f"""select to_varchar(delivery_date), count(*)
                    from {DB}.staging.stg_elpris__prices
                    where price_area = 'SE3'
                      and delivery_date in ('2025-03-30', '2024-10-27', '2025-10-26', '2026-03-29')
                    group by 1""",
            )
        )
        quirks = run(
            con,
            f"select count(*) from {DB}.staging.stg_elpris__prices where has_source_end_mismatch",
        )[0][0]
    finally:
        con.close()
    assert rows == {"2025-03-30": 23, "2024-10-27": 25, "2025-10-26": 100, "2026-03-29": 92}
    assert quirks == 8  # one per area on each of the two fall-back days in the fixtures
