# Elkollen

An electricity assistant for Sweden built on 15-minute day-ahead prices.
**Status: phase 1 of 6** — data foundation only. No API, assistant or UI yet.

## What works today (and how it was checked)

| Piece | State | Verified by |
|---|---|---|
| Price ingestion (elprisetjustnu.se → RAW) | Works | pytest suite; live runs against the API |
| dbt staging `stg_elpris__prices` | Works on DuckDB | `dbt build`: data tests + unit tests pass on real fixture days, and were shown to fail on deliberately corrupted data |
| Terraform for Snowflake | Validates | `terraform validate` against the provider schema. **Not applied** — needs your account |
| Snowflake sink and `snowflake` dbt target | Written, not run | Unit test with a fake connection only |
| Scheduled ingestion (GitHub Actions) | Off by default | Not run |

## Run it locally (no cloud account needed)

```powershell
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -c requirements-lock.txt -e ".[dev,dbt]"

# Offline: load committed real API responses (DST days, hourly -> 15 min switch)
$env:DUCKDB_PATH = "data/elkollen.duckdb"
elkollen-ingest load-fixtures fixtures/elpris
# or live: today + tomorrow for all areas
elkollen-ingest prices

dbt build --project-dir dbt --profiles-dir dbt
pytest
```

On Windows, if pip fails with a long-path error, create the virtualenv in a short
path (for example `C:\venvs\elkollen`).

## The hard part: mixed time grain and daylight saving

Prices were hourly until 2025-09-30 and are 15-minute from 2025-10-01. A Swedish day
has 24 hours, except the last Sunday in March (23) and October (25). So a day has
24/23/25 hourly rows or 96/92/100 quarter-hour rows. The staging model parses UTC
from the source's own offset, and a dbt test compares each day's row count with an
independent DST calendar. The source also has a real quirk on fall-back days (one
`time_end` is an hour off); see [docs/data-sources.md](docs/data-sources.md).
Why dbt runs on DuckDB in CI: [docs/decisions/0001](docs/decisions/0001-duckdb-for-local-and-ci.md).

## Layout

```
infra/terraform/     Snowflake database, schemas, warehouse, resource monitor, roles
src/elkollen_ingest/ price ingestion CLI (DuckDB or Snowflake sink)
dbt/                 staging models, generic tests, unit tests
fixtures/elpris/     real API responses used by tests and CI
docs/                data sources and terms, decision records
```

## Known limitations (phase 1)

- Snowflake resources and the Snowflake code paths have not been run against a real account.
- ENTSO-E and SMHI terms are not verified yet; those sources are not used.
- No unified 15-minute model, marts, API, MCP server, UI or forecast yet (phases 2–5).
- Missing *whole days* are not detected yet; a date-spine test comes with the marts.

## Credits

Price data: [elprisetjustnu.se](https://www.elprisetjustnu.se), sourced from the
ENTSO-E Transparency Platform.
