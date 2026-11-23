# 0003 — User isolation: enforced in the app, defended in Snowflake

**Status:** accepted (phase 3, 2026-11-23)

## Context

Users must never see each other's consumption, through the API or through the MCP
server the assistant uses. The brief also asks for Snowflake row access policies and
masking.

The API and the MCP server reach Snowflake as **one** service user (READER). Snowflake
therefore cannot tell which end user a query is for: a row access policy sees
`CURRENT_ROLE()` and `CURRENT_USER()`, which are the same for every web user. Policies
cannot read session variables, so passing the user id that way would not help, and
anything the client sets is not proof of identity anyway.

## Decision

**1. Isolation is enforced where identity is known, in the application, and tested.**
- The web app (Auth.js + Google) mints a short-lived HS256 token for the backend:
  one audience (`elkollen-api` or `elkollen-mcp`), issuer, scope, at most 1 hour.
- The API and MCP server take the user id **only** from the verified token's `sub`.
  No endpoint and no tool has a user parameter; the MCP tools that are per-user read
  the subject from the SDK's auth context, so the model cannot ask for another user.
- Every per-user query is `where user_id = :user_id` with a bound parameter, through one
  shared module (`elkollen_data.queries`).
- Automated tests go through the real HTTP API and the real MCP HTTP app and prove that
  user A cannot read user B, also with smuggled `user_id`/`user`/`sub` arguments. A
  deliberately broken scoping makes those tests fail.

**2. Snowflake policies are defence in depth, for what Snowflake *can* know.**
- Masking policy `mask_pii` on `dim_app_users.meter_id` and `address`: only the
  TRANSFORMER role sees full values; READER (the app) sees `****1234`.
- Row access policies hide users whose status is not `active` from the app role. A
  deletion request flips the status and the data disappears from the app at once,
  before the physical purge. The application also refuses inactive users (403).
- Policies are created and attached by a dbt post-hook (dbt rebuilds tables, which drops
  attachments). TRANSFORMER has `CREATE MASKING POLICY` / `CREATE ROW ACCESS POLICY` on
  MARTS for this, granted by Terraform.

## Consequences

- A bug in the application layer could leak data across users; the tests exist to
  catch exactly that, and run on every pull request.
- Per-end-user enforcement inside Snowflake would need one Snowflake identity per web
  user (or a trusted gateway that sets a verifiable context). Not justified for this
  project; recorded here so the trade-off is visible.
- The public demo holds only synthetic users, so a leak in the demo exposes no real
  person's data.
