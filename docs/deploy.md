# Deploying the public demo

Live since 2026-11-24: web app https://elkollen-rose.vercel.app, backend
https://elkollen-api.onrender.com (`/health`).

The demo runs on three free services plus Snowflake:

| Piece | Where | Cost |
|---|---|---|
| Web app (Next.js) | Vercel, Hobby plan | Free (non-commercial use) |
| API + MCP server (one Docker container) | Render, free web service | Free, no card. Sleeps after 15 min without visitors; the first visit after that waits about 1 minute |
| Data (prices, ENTSO-E forecasts, invented users) | Snowflake trial | Trial credits; the account's resource monitor caps use at 5 credits a month |
| Daily refresh (prices, ENTSO-E, dbt) | GitHub Actions, `.github/workflows/ingest-prices.yml` | Free for a public repo; each run wakes the XS warehouse briefly |
| Assistant model | Groq | Free tier |

Secrets are typed into each service's dashboard by you. None are in this repository.
`.env.example` lists every setting.

## 1. One shared secret

The web app signs short-lived tokens that the API and MCP server check. Both sides need
the same value. Generate it once and keep it in your password manager:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

It goes into Render and Vercel as `ELKOLLEN_JWT_SECRET`.

## 2. Snowflake: data in, refreshed daily

1. **ENTSO-E history** (once, so the forecast and `explain_spike` have grid data). From
   your PC, with the LOADER settings in `.env`:

   ```powershell
   elkollen-ingest entsoe --sink snowflake --start 2026-09-01 --end 2026-11-26
   ```

   Then run dbt on Snowflake (`$env:DBT_TARGET = "snowflake"; dbt build --project-dir dbt --profiles-dir dbt --select source:entsoe+`).
2. **Daily job.** In GitHub: Settings → Secrets and variables → Actions.
   - Secrets: `ELKOLLEN_SF_ACCOUNT`, `ELKOLLEN_SF_LOADER_USER`,
     `ELKOLLEN_SF_LOADER_PRIVATE_KEY`, `ELKOLLEN_SF_TRANSFORMER_USER`,
     `ELKOLLEN_SF_TRANSFORMER_PRIVATE_KEY` (the full key file contents),
     `ENTSOE_API_TOKEN`.
   - Variable: `SNOWFLAKE_INGEST_ENABLED` = `true`.
   - Run it once by hand (Actions → Ingest prices → Run workflow) and check it is green.

## 3. Render: the backend

1. Sign in to Render with GitHub. New → **Blueprint** → choose this repository. Render
   reads `render.yaml` and asks for the values marked `sync: false`:
   - `ELKOLLEN_SF_ACCOUNT`, `ELKOLLEN_SF_READER_USER`: from your `.env`.
   - `ELKOLLEN_JWT_SECRET`: the value from step 1.
   - `GROQ_API_KEY`: from your `.env`.
   - `ELKOLLEN_WEB_ORIGIN`, `ELKOLLEN_AUTH_ISSUER`: leave a placeholder for now; set
     both to the Vercel address in step 5.
2. In the service: Environment → **Secret Files** → add `reader.p8` with the contents of
   the READER private key file.
3. Open `https://<service>.onrender.com/health`. Expected:
   `{"status":"ok","warehouse":"snowflake"}`.

## 4. Vercel: the web app

1. Sign in to Vercel with GitHub. Add New → Project → this repository.
2. **Root Directory: `web`.** Framework: Next.js (detected).
3. Environment variables:
   - `AUTH_SECRET`: a new random value (`npx auth secret` prints one).
   - `AUTH_GOOGLE_ID`, `AUTH_GOOGLE_SECRET`: from `web/.env.local`.
   - `ELKOLLEN_API_URL`: `https://<service>.onrender.com`
   - `ELKOLLEN_JWT_SECRET`: the value from step 1.
   - `ELKOLLEN_DEMO_LOGIN`: `true` lets visitors try the assistant as an invented demo
     user without a Google account. Leave it out to allow Google sign-in only.
4. Deploy and note the address, e.g. `https://<project>.vercel.app`.

## 5. Connect the pieces

1. **Google Cloud console** → your OAuth client:
   - Authorised JavaScript origin: `https://<project>.vercel.app`
   - Authorised redirect URI: `https://<project>.vercel.app/api/auth/callback/google`
2. **Render** → Environment: set `ELKOLLEN_WEB_ORIGIN` and `ELKOLLEN_AUTH_ISSUER` to
   `https://<project>.vercel.app`. Render redeploys.

## 6. Check it

- [ ] `/health` on Render answers `ok` with `snowflake`.
- [ ] The start page shows today's quarter-hour prices for SE3, and the area switch works.
- [ ] Tomorrow shows prices and alerts (after about 13:00) or a labelled forecast (before).
- [ ] Sign in (Google, and the demo login if enabled) and ask the assistant a question.
- [ ] Upload `fixtures/consumption/exempel_timvarden.csv` on the Upload page.
- [ ] Light/dark and Swedish/English switches work on a phone.

## Before 20 December: Snowflake trial ends

The trial ends around 23 December 2026. Before then, either move to a paid Snowflake plan
or switch the demo to DuckDB (`ELKOLLEN_WAREHOUSE=duckdb`). The code already supports
both; **not built yet** is the DuckDB data for the container (fetching prices, ENTSO-E
and the invented users into a DuckDB file and running dbt, at start-up or daily).
