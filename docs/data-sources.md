# Data sources

Every source is checked for terms and rate limits **before** the pipeline relies on it.
"Verified" means someone read the page on the date given. "Unverified" means it has not
been read yet and the source must not be used until it has.

| Source | Used for | Status | Checked |
|---|---|---|---|
| elprisetjustnu.se API | Day-ahead spot prices SE1–SE4 | In use (phase 1) | 2026-11-23 |
| ENTSO-E Transparency Platform | Load, generation, wind forecast | **Unverified**, not used yet | — |
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

## ENTSO-E Transparency Platform (not yet used)

Terms page and API guide could not be fetched from the build environment (HTTP 400/403)
on 2026-11-23. Before phase 2 uses it, read and record here: how to request a security
token, the request rate limit, the reuse licence and the attribution wording.

## SMHI open data (not yet used)

The terms page returned 404 and the portal needs a browser on 2026-11-23. Before use,
confirm the licence (commonly stated as CC BY 4.0 — **not confirmed here**), the
required attribution wording, and any fair-use limits for the metobs/metfcst APIs.
