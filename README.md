# Elkollen

An electricity assistant for Sweden built on 15-minute day-ahead prices.
**Status: phases 1–3 of 6.** Data platform, unified 15-minute model, marts, a read-only
MCP server and an HTTP API. No web UI, chat or forecast yet.

## What works today (and how it was checked)

| Piece | State | Verified by |
|---|---|---|
| Price ingestion (elprisetjustnu.se → RAW) | Works | pytest; live runs against the API |
| dbt staging and the **unified 15-minute model** `fct_prices_15min` | Works on DuckDB **and Snowflake** | CI: real fixture days. Snowflake: two years of history (2024-10-26 → tomorrow, 193,936 source rows), `dbt build` 87/87: interval counts per day (96/92/100) against a DST calendar, gaps, duplicates, all areas, no missing day, hourly→15-min flag. Tests shown to fail on corrupted data |
| Marts: daily prices, price freshness, per-user consumption | Works on DuckDB and Snowflake | dbt data and unit tests (e.g. a user is only ever priced in their own area); the live "tomorrow's prices are in" test passes on Snowflake |
| Freshness check for tomorrow's prices | Works | `mart_price_freshness` + a `live` test, unit-tested with a pinned clock |
| Shared query layer (`elkollen_data`) | Works | 35 tests on a warehouse built by dbt |
| **MCP server** (5 read-only tools) | Works locally | 22 tests through the real MCP HTTP app: 8 kinds of bad token → 401, user A cannot read user B, no tool takes a user |
| **HTTP API** (FastAPI) | Works locally | 43 tests: bad tokens → 401, user A cannot read user B (also via smuggled query params), deleted users → 403 |
| Terraform for Snowflake | Applied | 37 objects (phase 1) + policy grants (phase 3) on a trial account; re-plan shows no drift |
| Least-privilege roles | Works | `RUN_SNOWFLAKE_TESTS=1 pytest tests/snowflake` (opt-in, not in CI) |
| Masking and row access policies | Works on Snowflake | Live checks: READER sees `****` meter ids and addresses and no deleted user; TRANSFORMER sees full values; policies attached. The query layer gives the same answers on Snowflake as on DuckDB (15/15 live checks) |
| Cost so far | 0.43 credits | Of the 5-credit monthly cap, including the two-year backfill |
| Scheduled / Snowflake-native ingestion | Off by default | Not run |

## Run it locally (no cloud account needed)

```powershell
pip install -c requirements-lock.txt -e ".[dev,dbt,api]"
$env:DUCKDB_PATH = "data/elkollen.duckdb"

elkollen-ingest load-fixtures fixtures/elpris            # real API responses, offline
elkollen-ingest synthetic-consumption --start 2025-09-29 --end 2025-10-05
dbt build --project-dir dbt --profiles-dir dbt --exclude tag:live `
  --vars '{price_continuity_start: "2025-09-29", price_continuity_end: "2025-10-05"}'
pytest                                                    # builds its own warehouse

$env:ELKOLLEN_JWT_SECRET = python -c "import secrets; print(secrets.token_urlsafe(48))"
uvicorn elkollen_api.app:create_app --factory --port 8000  # API, docs at /docs
elkollen-mcp                                               # MCP server on 127.0.0.1:8001/mcp
```

On Windows, if pip fails with a long-path error, create the virtualenv in a short path.

## The hard part: mixed time grain and daylight saving

Prices were hourly until 2025-09-30 and are 15-minute from 2025-10-01. A Swedish day
has 24 hours, except the last Sunday in March (23) and October (25).
`fct_prices_15min` puts the whole history on one 15-minute grain: hourly rows become
four quarters with the hourly price and `is_upsampled_from_hourly = true`, so every day
has 96 intervals, 92 or 100 on clock-change days. Tests check that against an
independent DST calendar, plus gaps, duplicates, missing areas and missing days.
Negative prices are real and pass. The source has a real quirk on fall-back days (one
`time_end` is an hour off): see [docs/data-sources.md](docs/data-sources.md).

## How the assistant gets its numbers

The assistant (phase 4) answers only through five read-only MCP tools: `get_prices`,
`cheapest_window`, `cost_of_my_usage`, `compare_plans`, `explain_spike`. Each result
carries the numbers it was computed from, its source tables and what it excludes
(VAT, tax, markup, grid fees). Inputs are validated, reads are capped at 2,000 rows,
and every call is audit-logged with a pseudonymous user hash.

## Privacy

- The public demo uses **synthetic** users and consumption only. No real meter data is
  committed or loaded.
- Stored per user: a display name, price area, meter id and address (both masked for the
  app role on Snowflake) and 15-minute consumption.
- The user is identified only from a verified, short-lived token. How isolation works,
  and its limits: [decision 0003](docs/decisions/0003-user-isolation-and-privacy.md).
- Deleting a user: set their status to `deleted` (hidden from the app immediately by the
  application and by a Snowflake row access policy), then purge their rows from
  `raw.app_users` and `raw.consumption_readings` and rebuild. A self-service delete
  button comes with the upload page in phase 5.

## Layout

```
infra/terraform/      Snowflake: database, schemas, warehouse, monitor, roles, grants
src/elkollen_ingest/  ingestion CLI: prices, fixtures, synthetic consumption
src/elkollen_data/    read-only query layer shared by API and MCP
src/elkollen_mcp/     MCP server (official Python SDK)
src/elkollen_api/     FastAPI backend
src/elkollen_auth/    short-lived backend tokens
dbt/                  staging, intermediate (15-min grain), marts, tests, privacy policies
fixtures/elpris/      real API responses used by tests and CI
docs/                 data sources and terms, decision records
```

## Known limitations

- The API and MCP server have been run against Snowflake only through their shared
  query layer (live checks); end-to-end HTTP tests run on DuckDB.
- Per-end-user isolation is enforced and tested in the application, not inside
  Snowflake (one service user for the app); see decision 0003.
- `explain_spike` infers context from prices only; load, wind and weather data are not
  connected yet (ENTSO-E token pending, SMHI terms to verify).
- The Snowflake-native ingestion path has not been run: trial accounts cannot call
  outside APIs. Some of its Terraform resources are "preview" in the provider.
- No web UI, chat, upload, forecast or alerts yet (phases 4–5).

## Credits

Price data: [elprisetjustnu.se](https://www.elprisetjustnu.se), sourced from the
ENTSO-E Transparency Platform.
