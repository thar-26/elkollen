# Demo script (about 5 minutes)

For a live demo or a screen recording. Everything shown uses public prices and
**invented** demo users; no real personal data.

Before you start (5 minutes earlier):
- Open the web app once. A ping every 10 minutes keeps the free backend awake, but if
  GitHub ran it late the backend may be asleep and take about a minute to wake up.
- Have [fixtures/consumption/exempel_timvarden.csv](../fixtures/consumption/exempel_timvarden.csv)
  ready to upload (invented hourly readings for one month, including the clock change).
- Check the questions in step 4 still give a good answer today; prices change every day.

## 1. The problem (30 s)

"Since October 2025 the Swedish electricity price changes every 15 minutes, not every
hour. Elkollen makes that usable: what does power cost now, when is it cheapest, what
will tomorrow look like, and why."

## 2. Today, quarter by quarter (60 s)

- Start page: the price **right now** for the current quarter-hour, then the next twelve
  quarters as a row of bars. Point out that neighbouring quarters can differ a lot.
- Switch the area (SE3 → SE1) and mention that the four Swedish areas get different
  prices when the grid between them is full.
- Pick **Dishwasher / Washing machine / Car**: the cheapest window for that job and how much
  it saves compared with the day's average.

## 3. Tomorrow (45 s)

- **After about 13:00:** the Tomorrow tab shows the published prices and alerts
  (negative prices, very cheap windows, spikes) with their numbers.
- **Before 13:00:** the Tomorrow tab shows a **forecast**, clearly labelled, with its
  track record next to it ("tested on 60 days, beats 'same as yesterday' by …").
  The honest part: in SE4 the gain is not proven, and the app says so.

## 4. Ask the assistant (90 s)

Sign in (Google, or the demo login if it is enabled), then ask for example:

1. "When is it cheapest to charge the car tonight?"
2. "Why is the price so high at 17:00 today?" → it uses forecast load and wind for that
   quarter and compares with the last 30 days.
3. "What did my electricity cost last week?" → answered for the signed-in demo user only.

Points to make:
- The model **cannot query the database**. It can only call five read-only tools, and the
  tools take the user from the signed-in session, never from the question.
- Every number in the answer is **checked against the tool results** before it is shown.

## 5. Upload a consumption file (45 s)

Open **Upload**, choose the example file and the price area:
- What you paid at spot prices, what you could have paid by moving a chosen share of use to
  the cheapest hours, and a monthly trend.
- "The file is analysed in memory and not stored."

## 6. Under the hood (30–60 s, for technical audiences)

Open the repository:
- The diagram in the [README](../README.md).
- CI: Python tests, dbt build with tests, web build, Terraform validate, on every pull
  request.
- One test to show: user A cannot read user B through the API or the MCP server
  (`tests/api/test_api_security.py`, `tests/mcp/test_mcp_security.py`).
- One data test to show: every day must have 96 quarters, or 92/100 on clock-change days
  (`dbt/tests/generic/expected_intervals_per_day.sql`).

## If something goes wrong

- **Page loads slowly or shows an error first:** the backend was asleep; reload after a
  minute.
- **Assistant says it is busy:** the free LLM quota or the rate limit (20 questions per
  10 minutes) was reached; show the rest and come back to it.
- **No forecast shown:** tomorrow's prices are already published (after about 13:00); show
  the published prices and alerts instead.
