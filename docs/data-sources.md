# Data sources

Every source is checked for terms and rate limits **before** the pipeline relies on it.
"Verified" means someone read the page on the date given. "Unverified" means it has not
been read yet and the source must not be used until it has.

| Source | Used for | Status | Checked |
|---|---|---|---|
| elprisetjustnu.se API | Day-ahead spot prices SE1–SE4 | In use (phase 1) | 2026-11-23 |
| ENTSO-E Transparency Platform | Day-ahead load, wind and solar forecasts | In use (ENTSO-E step) | 2026-11-24 (partly, see below) |
| SMHI open data | Weather observations/forecasts | **Unverified**, not used yet | — |

## elprisetjustnu.se

- **Page read:** https://www.elprisetjustnu.se/elpris-api (2026-11-23)
- **Endpoint:** `GET https://www.elprisetjustnu.se/api/v1/prices/{YYYY}/{MM}-{DD}_{SE1..SE4}.json`
- **Operator:** Beneficial Apps AS (Norway).
- **Terms:** described as a completely open and free API, available to anyone for any
  purpose. No formal licence text is published. Attribution is *requested* when data is
  used publicly ("refer to us as the source"), not required. Elkollen credits it in the
  UI footer and README.
- **Upstream:** the API takes prices from the ENTSO-E Transparency Platform (EUR) and
  converts with exchange rates from exchangeratesapi.io. Prices exclude VAT, energy tax,
  certificates and grid fees.
- **Publication time:** tomorrow's prices arrive at the earliest at 13:00 Stockholm time.
  Before that the endpoint returns 404, which ingestion treats as "not published yet".
- **Rate limits:** none published. Self-imposed politeness: sequential requests, 0.25 s
  pause, descriptive `User-Agent`, at most 3 retries with exponential backoff on
  429/5xx, and a hard cap of 1100 days per run.
- **Resolution:** hourly up to 2025-09-30, 15 minutes from 2025-10-01 (verified against
  the API: 24 rows on 2025-09-30, 96 rows on 2025-10-01).
- **History:** the API serves data from 2022-11-01.

### Known quirks (observed, with fixtures in `fixtures/elpris/`)

1. **Wrong `time_end` on the autumn clock-change day.** The interval just before the
   change declares its end in the new offset, one hour too late:
   - 2025-10-26: `02:45+02:00 → 03:00+01:00` (should be `03:00+02:00`, a 75-min interval)
   - 2024-10-27: `02:00+02:00 → 03:00+01:00` (should be `03:00+02:00`, a 2-hour interval)

   Seen in all four areas. Interval starts are correct and contiguous. Ingestion
   validates on starts, logs a warning and keeps the raw value. Staging recomputes
   `interval_end_utc = start + resolution` and sets `has_source_end_mismatch = true`.
2. **Negative prices** are real (e.g. SE1 2025-10-02 18:45: −1.04304 SEK/kWh) and pass
   all checks.

## ENTSO-E Transparency Platform

- **What we fetch:** day-ahead total load forecast (documentType A65, processType A01)
  and day-ahead wind and solar forecast (A69, A01; psrType B16 solar, B18 wind offshore,
  B19 wind onshore) for SE1-SE4, from `https://web-api.tp.entsoe.eu/api`.
- **Token:** free. Register, ask ENTSO-E for RESTful API access, then generate a token
  under My Account Settings. It lives in `ENTSOE_API_TOKEN` (git-ignored `.env`) and is
  never logged: the CLI silences httpx request logging and client errors drop the URL
  (both tested).
- **Rate limit:** 400 requests per minute per token (ENTSO-E help centre, "API Rate
  Limit", read 2026-11-24). We pause 0.25 s between requests, retry 429/5xx at most 3
  times with backoff, and ask for at most 31 days per request.
- **Reuse:** ENTSO-E announced on 2019-02-01 that TSOs release their data on the
  platform "under an open data licence", so permission is no longer needed to reuse it
  ([announcement](https://www.entsoe.eu/news/2019/02/01/tsos-increase-number-of-open-data-available-through-entso-e-s-transparency-platform/)). **Not verified:** the licence name, the
  exact attribution wording and the platform's current terms page (it did not load
  outside a browser on 2026-11-24). Until that is read, Elkollen commits **no real
  ENTSO-E data**: `fixtures/entsoe/` holds invented values in the real XML format, and
  real data stays in the git-ignored local or Snowflake warehouse. Credited as
  "ENTSO-E Transparency Platform" in the README.
- **These are forecasts made the day before, not measurements.** The rules allow wind
  and solar forecasts to be published as late as 18:00 the day before, after prices
  (about 13:00), so the backtest assumes they are available earlier than they may be.

### Observed behaviour (2026-11-24)

1. **Repeated values are left out** (curve type A03): a 96-quarter day can arrive with
   95 points. The parser fills a missing position with the previous value; a gap in a
   regular (A01) series is refused.
2. **Resolution changes:** SE3 load is hourly (PT60M) in 2024 and 2025 and 15-minute
   later; wind and solar are 15-minute. dbt expands hourly values to four quarters and
   flags them (`is_load_upsampled_from_hourly`).
3. **"No data" is an Acknowledgement document**, sometimes with HTTP 400; it is read as
   an empty result, not an error.
4. 2025-06-01 to 2026-11-25, all four areas: 466,764 rows, and every dbt check passes
   (96/92/100 quarters per day, no gaps, no duplicates).

## SMHI open data (not yet used)

The terms page returned 404 and the portal needs a browser on 2026-11-23. Before use,
confirm the licence (commonly stated as CC BY 4.0 — **not confirmed here**), the
required attribution wording, and any fair-use limits for the metobs/metfcst APIs.
