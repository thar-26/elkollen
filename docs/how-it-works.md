# How Elkollen works

The details behind the [README](../README.md): what was checked and how, the hard parts,
and how each feature works.

## What works (and how it was checked)

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
| ENTSO-E load, wind and solar forecasts → `fct_grid_forecast_15min` | Works on DuckDB | Parser tests (gaps, clock change, bad documents, token never logged); dbt checks pass on 17 months of real data for all areas (466,764 rows). Not yet loaded into Snowflake |
| Scheduled / Snowflake-native ingestion | Off by default | Not run |

## The hard part: mixed time grain and daylight saving

Prices were hourly until 2025-09-30 and are 15-minute from 2025-10-01. A Swedish day
has 24 hours, except the last Sunday in March (23) and October (25).
`fct_prices_15min` puts the whole history on one 15-minute grain: hourly rows become
four quarters with the hourly price and `is_upsampled_from_hourly = true`, so every day
has 96 intervals, 92 or 100 on clock-change days. Tests check that against an
independent DST calendar, plus gaps, duplicates, missing areas and missing days.
Negative prices are real and pass. The source has a real quirk on fall-back days (one
`time_end` is an hour off): see [docs/data-sources.md](data-sources.md).

## How the assistant gets its numbers

The assistant (phase 4) answers only through five read-only MCP tools: `get_prices`,
`cheapest_window`, `cost_of_my_usage`, `compare_plans`, `explain_spike`. Each result
carries the numbers it was computed from, its source tables and what it excludes
(VAT, tax, markup, grid fees). Inputs are validated, reads are capped at 2,000 rows,
and every call is audit-logged with a pseudonymous user hash. `explain_spike` adds the
day-ahead load, wind and solar forecast for that quarter and how they compare with the
30-day average, and says when it had prices only.

## Next-day forecast, and where it loses

The forecast is ported from my earlier project
[thar-26/elpris-forecast](https://github.com/thar-26/elpris-forecast) (ridge regression,
walk-forward test, bootstrap verdict) and moved from hours to quarter-hours. Price inputs
are at least 24 hours old; a test changes a day's prices and checks that day's inputs do
not move. A second version also gets ENTSO-E's day-ahead forecasts of load, wind and solar
for each quarter. Before tomorrow's prices are published (about 13:00) the web app shows the
forecast, labelled as such, with the numbers of the version it used: grid forecasts when
every quarter of tomorrow has them, otherwise prices only.

Walk-forward test, 60 days (2026-09-26 to 2026-11-24), history from 2025-06-01, mean
absolute error in öre/kWh. Each test day is forecast by a model trained only on earlier
days; a gain counts only if its 95 % bootstrap range excludes zero
([reports/forecast_backtest.json](../reports/forecast_backtest.json)):

| Area | Same quarter yesterday | Ridge, prices only | Ridge + grid forecasts | Days better | Verdict (grid version) |
|---|---|---|---|---|---|
| SE1 | 28.32 | 24.50 (−13.5 %) | **21.80 (−23.0 %)** | 42 / 60 | beats baseline |
| SE2 | 32.14 | 27.68 (−13.9 %) | **20.44 (−36.4 %)** | 42 / 60 | beats baseline |
| SE3 | 51.76 | 47.96 (−7.3 %) | **39.31 (−24.1 %)** | 40 / 60 | beats baseline |
| SE4 | 62.70 | 61.67 (−1.6 %) | **54.02 (−13.8 %)** | 37 / 60 | not proven |

Honestly: prices alone barely beat "same as yesterday" in the south (not proven in SE3 or
SE4). Knowing tomorrow's forecast wind and load makes the difference, and SE3 is now
proven. SE4 improves but is not proven over 60 days. One caveat: the rules let wind and
solar forecasts be published as late as 18:00 the day before, after prices, so this test
assumes they are available earlier than they may be. "Same quarter last week" is worse
everywhere. Weather (SMHI) is not used.

## Your consumption

`/upload` takes a CSV export from your grid company (hourly or 15-minute, Swedish formats,
including the repeated hour on the autumn clock change). It shows what you paid at spot
prices, what it would have cost with a chosen share of each day's use moved into that day's
cheapest four hours (an estimate with a stated assumption), and a monthly trend. The file is
analysed in memory and **not stored**. An invented example file is in
[fixtures/consumption](../fixtures/consumption/exempel_timvarden.csv).

## Alerts

For each published day: negative quarters, a cheap two-hour window (below half the 30-day
average) and spikes (above twice it), each shown with its numbers. Shown in the app; no
e-mail or push notifications.

## Privacy

- The public demo uses **synthetic** users and consumption only. No real meter data is
  committed or loaded.
- Stored per user: a display name, price area, meter id and address (both masked for the
  app role on Snowflake) and 15-minute consumption.
- The user is identified only from a verified, short-lived token. How isolation works,
  and its limits: [decision 0003](decisions/0003-user-isolation-and-privacy.md).
- Deleting a user: set their status to `deleted` (hidden from the app immediately by the
  application and by a Snowflake row access policy), then purge their rows from
  `raw.app_users` and `raw.consumption_readings` and rebuild. There is no self-service
  delete button yet; uploaded files are never stored, so there is nothing of theirs to delete.

## Layout

```
infra/terraform/      Snowflake: database, schemas, warehouse, monitor, roles, grants
src/elkollen_ingest/  ingestion CLI: prices, fixtures, synthetic consumption
src/elkollen_data/    read-only query layer shared by API and MCP
src/elkollen_mcp/     MCP server (official Python SDK)
src/elkollen_api/     FastAPI backend
src/elkollen_auth/    short-lived backend tokens
src/elkollen_chat/    assistant: Groq model, MCP client, grounding check
src/elkollen_forecast/ next-day forecast and backtest
web/                  Next.js app (prices, assistant, upload)
dbt/                  staging, intermediate (15-min grain), marts, tests, privacy policies
fixtures/elpris/      real API responses used by tests and CI
docs/                 data sources and terms, decision records
```
