# 0001 — Run the same dbt project on DuckDB locally and in CI, Snowflake in production

**Status:** accepted (phase 1)

## Context

Production runs on Snowflake. CI on a public repo cannot hold Snowflake credentials
for pull requests from forks, and every CI run against Snowflake costs credits.
Reviewers should be able to run the whole pipeline on a laptop with no account.

## Decision

- One dbt project with two targets: `local` (DuckDB file) and `snowflake`.
- SQL is written to work on both. The few engine differences live in dispatched
  macros (`dbt/macros/time.sql`). Timestamps are parsed from the source's own ISO
  offset, so DST handling does not depend on either engine's timezone database.
- CI loads real API responses committed under `fixtures/elpris/` (DST days and the
  hourly → 15-minute switch) and runs `dbt build` on DuckDB.

## Consequences

- CI proves logic and tests; it does **not** prove Snowflake-specific behaviour
  (grants, row access policies, masking). Those are verified by a manual
  `DBT_TARGET=snowflake` build and, from phase 3, by security tests run against
  a Snowflake account.
- New SQL must avoid engine-only functions or add a dispatched macro.
