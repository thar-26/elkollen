# 0002 — Hybrid ingestion: fetch outside or inside Snowflake, transform in Snowflake

**Status:** accepted (phase 1, 2026-11-23)

## Context

The brief asks for scheduled ingestion with Snowflake tasks. A Snowflake task can
only call an outside HTTP API from a Python procedure that uses an *external access
integration*. Snowflake's documentation (read 2026-11-23) lists external network
access among the features "not available for trial accounts", unless Snowflake
support enables it. A trial also ends after 30 days.

GitHub Actions cron is free but may start runs late; the author's earlier project
(`thar-26/elpris-forecast`) saw scheduled runs start about 7 hours late.

## Decision

Split fetching from transforming, and make the fetch location a switch:

| Step | Trial / default | Paid account (`enable_native_ingestion = true`) |
|---|---|---|
| Fetch prices → `RAW.ELPRIS_PRICES` | GitHub Actions runs `elkollen-ingest prices --sink snowflake` as the LOADER user | Snowflake task `RAW.INGEST_PRICES_DAILY` (13:20 and 16:20 Europe/Stockholm) calls procedure `RAW.INGEST_PRICES` |
| Transform and test | GitHub Actions runs `dbt build` and `dbt source freshness` on Snowflake | same |

- The procedure body is `elpris.py` + `snowflake_proc.py` from this repo, joined by
  Terraform. A test executes exactly that joined source, so the code inside Snowflake
  is the code CI tests.
- Egress is limited by a network rule to `www.elprisetjustnu.se:443`.
- The procedure and task are owned by the LOADER role, not an admin role.
- The task runs on the project warehouse, so the resource monitor's credit cap
  applies (serverless tasks are not covered by resource monitors).
- RAW is append-only and staging keeps the latest load per interval, so the two fetch
  paths can overlap during a switch-over without creating duplicates downstream.

## Consequences

- Works on a free trial today; moves fetching into Snowflake later with one variable.
- Late GitHub runs are tolerated: tomorrow's prices only need to arrive before
  midnight, there are two runs a day, and the freshness check fails loudly otherwise.
- The native path (procedure, task, grants, ownership transfer) has **not** been run
  against a real Snowflake account. `terraform validate` passes against provider
  2.23.0 and the procedure code is unit-tested with a fake Snowpark session.
- The provider marks network rules, external access integrations and Python
  procedures as preview resources; the provider version is pinned in the lock file.
