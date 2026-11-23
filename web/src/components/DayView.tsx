"use client";

import { useState } from "react";

import { PriceChart } from "@/components/PriceChart";
import { localTime, longDate, ore } from "@/lib/format";
import { dict, type Locale } from "@/lib/i18n";
import { type Area, DEVICES, type DayData, type Interval } from "@/lib/types";

type Props = { days: DayData[]; area: Area; locale: Locale; nowUtc: string };

/** The next twelve quarter-hours as one row: time on top, price below, a bar whose
 *  height is the price on a zero baseline shared by the row. Makes the 15-minute
 *  rhythm visible at a glance; the current quarter is inverted. */
function UpcomingQuarters({ intervals, nowUtc, locale }: { intervals: Interval[]; nowUtc: string; locale: Locale }) {
  const t = dict[locale];
  const start = intervals.findIndex((i) => i.start_utc <= nowUtc && nowUtc < i.end_utc);
  const next = intervals.slice(start, start + 12);
  const top = Math.max(...next.map((i) => Math.abs(i.price_ore_per_kwh)), 1);
  return (
    <section aria-labelledby="upcoming-heading" className="mt-10">
      <h2 id="upcoming-heading" className="text-[15px] text-muted">
        {t.upcoming}
      </h2>
      <ol className="mt-3 grid grid-cols-4 gap-1 sm:grid-cols-6 md:grid-cols-12">
        {next.map((iv, i) => (
          <li
            key={iv.start_utc}
            aria-current={i === 0 ? "time" : undefined}
            className={`${i >= 8 ? "hidden sm:flex" : "flex"} flex-col justify-between rounded-sm px-2 pt-2 pb-0 ${
              i === 0 ? "bg-ink text-ground" : "bg-raised"
            }`}
          >
            <span className="text-[13px] opacity-80">{localTime(iv.start_utc)}</span>
            <span className="mt-1 text-[17px] font-semibold">{ore(iv.price_ore_per_kwh, locale, 0)}</span>
            <span className="mt-2 flex h-10 items-end" aria-hidden>
              <span
                className={`w-full rounded-t-[2px] ${iv.price_ore_per_kwh < 0 ? "bg-cheap" : i === 0 ? "bg-ground" : "bg-bar"}`}
                style={{ height: `${Math.max(4, (Math.abs(iv.price_ore_per_kwh) / top) * 40)}px` }}
              />
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function DayView({ days, area, locale, nowUtc }: Props) {
  const t = dict[locale];
  const [dayIdx, setDayIdx] = useState(0);
  const [deviceIdx, setDeviceIdx] = useState(0);
  const day = days[dayIdx];
  const device = DEVICES[deviceIdx];
  const intervals = day.prices?.data.intervals ?? [];
  const summary = day.prices?.data.summary ?? null;
  const win = day.windows[device.minutes]?.data ?? null;
  const dayLabel = dayIdx === 0 ? t.today : t.tomorrow;
  const nowInterval = dayIdx === 0 ? intervals.find((i) => i.start_utc <= nowUtc && nowUtc < i.end_utc) : undefined;
  const hourly = intervals.some((i) => i.upsampled_from_hourly);

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-x-16 gap-y-12 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <section aria-labelledby="day-heading">
        <div role="tablist" aria-label={t.chartTitle("", area)} className="mb-8 flex gap-2">
          {days.map((d, i) => (
            <button
              key={d.date}
              role="tab"
              type="button"
              aria-selected={i === dayIdx}
              onClick={() => setDayIdx(i)}
              className={`rounded-full px-4 py-2 text-[15px] ${
                i === dayIdx ? "bg-ink text-ground" : "bg-raised text-ink hover:bg-grid"
              }`}
            >
              {i === 0 ? t.today : t.tomorrow}
            </button>
          ))}
        </div>

        <p className="text-[17px] text-muted first-letter:uppercase">
          {area} · {longDate(day.date, locale)}
        </p>
        <h1
          id="day-heading"
          className="mt-3 max-w-[18ch] text-[clamp(2rem,5vw,3.5rem)] leading-[1.02] font-semibold tracking-[-0.03em]"
        >
          {nowInterval
            ? t.quarterNow(localTime(nowInterval.start_utc), localTime(nowInterval.end_utc))
            : summary
              ? t.dayHeadline(intervals.length)
              : t.chartTitle(dayLabel, area)}
        </h1>

        {summary ? (
          <>
            {nowInterval && (
              <p className="mt-4 text-[clamp(3.5rem,10vw,7rem)] leading-none font-semibold tracking-[-0.045em]">
                {ore(nowInterval.price_ore_per_kwh, locale)}
                <span className="ml-3 text-[20px] font-normal tracking-normal text-muted">
                  {t.priceUnit}
                </span>
              </p>
            )}
            {nowInterval && (
              <UpcomingQuarters
                intervals={[...intervals, ...(days[1]?.prices?.data.intervals ?? [])]}
                nowUtc={nowUtc}
                locale={locale}
              />
            )}
            <p className="mt-8 max-w-prose text-[17px]">{t.switchNote}</p>
            <dl className="mt-8 flex flex-wrap items-end gap-x-10 gap-y-4">
              {[
                [t.min, summary.min_ore_per_kwh],
                [t.avg, summary.avg_ore_per_kwh],
                [t.max, summary.max_ore_per_kwh],
              ].map(([label, value]) => (
                <div key={label as string}>
                  <dt className="text-[15px] text-muted">{label}</dt>
                  <dd className="text-[22px] font-medium">{ore(value as number, locale)}</dd>
                </div>
              ))}
            </dl>
            {(day.alerts ?? []).length > 0 && (
              <ul aria-label="Alerts" className="mt-8 max-w-prose space-y-2">
                {(day.alerts ?? []).map((a) => (
                  <li key={a.kind} className="flex gap-3 text-[16px]">
                    <span
                      aria-hidden
                      className={`mt-2 inline-block h-2.5 w-2.5 shrink-0 rounded-full ${a.kind === "spike" ? "bg-dear" : "bg-cheap"}`}
                    />
                    <span>
                      {a.kind === "negative_prices" &&
                        t.alertNegative(a.n_quarters ?? 0, ore(a.lowest_ore_per_kwh ?? 0, locale))}
                      {a.kind === "cheap_window" &&
                        t.alertCheap(localTime(a.start_utc!), localTime(a.end_utc!), ore(a.avg_ore_per_kwh ?? 0, locale))}
                      {a.kind === "spike" &&
                        t.alertSpike(
                          localTime(a.start_utc!),
                          ore(a.price_ore_per_kwh ?? 0, locale),
                          ore(a.avg_30d_ore_per_kwh ?? 0, locale),
                        )}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <div className="mt-10">
              <PriceChart
                intervals={intervals}
                cheapest={win?.cheapest ?? null}
                dearest={win?.dearest ?? null}
                locale={locale}
                title={t.chartTitle(dayLabel, area)}
                nowUtc={dayIdx === 0 ? nowUtc : undefined}
              />
            </div>
            <p className="mt-4 max-w-prose text-[14px] text-muted">
              {t.chartNote} {hourly ? t.hourlyNote : ""} {t.sourceLine}
            </p>
          </>
        ) : (
          <>
            <p className="mt-10 max-w-prose rounded-sm bg-raised p-6 text-[17px]">
              {dayIdx === 1 ? t.notPublished : t.noData}
            </p>
            {day.forecast && day.forecast.intervals.length > 0 && (
              <section aria-labelledby="forecast-heading" className="mt-10">
                <h2 id="forecast-heading" className="text-[22px] font-semibold tracking-[-0.01em]">
                  {t.forecastTitle}
                </h2>
                {day.forecast.backtest && (
                  <p className="mt-2 max-w-prose text-[15px] text-muted">
                    {t.forecastNote(
                      ore(day.forecast.backtest.gain_pct, locale),
                      t.verdicts[day.forecast.backtest.verdict] ?? day.forecast.backtest.verdict,
                      day.forecast.backtest.days,
                    )}
                  </p>
                )}
                <div className="mt-6">
                  <PriceChart
                    intervals={day.forecast.intervals.map((f) => ({
                      start_utc: f.start_utc,
                      end_utc: new Date(Date.parse(`${f.start_utc}Z`) + 15 * 60_000).toISOString().slice(0, 19),
                      start_local: f.start_utc,
                      price_ore_per_kwh: f.forecast_ore_per_kwh,
                      upsampled_from_hourly: false,
                    }))}
                    cheapest={null}
                    dearest={null}
                    locale={locale}
                    title={`${t.forecastTitle}, ${area}`}
                  />
                </div>
              </section>
            )}
          </>
        )}
      </section>

      <section aria-labelledby="best-heading" className="lg:pt-[3.75rem]">
        <h2 id="best-heading" className="text-[22px] font-semibold tracking-[-0.01em]">
          {t.bestTime}
        </h2>
        <div role="radiogroup" aria-label={t.bestTime} className="mt-4 flex flex-wrap gap-2">
          {DEVICES.map((d, i) => (
            <button
              key={d.id}
              type="button"
              role="radio"
              aria-checked={i === deviceIdx}
              onClick={() => setDeviceIdx(i)}
              className={`rounded-full px-4 py-2 text-[15px] ${
                i === deviceIdx ? "bg-cheap text-on-accent" : "bg-raised hover:bg-grid"
              }`}
            >
              {t.devices[d.id]} · {t.hours(d.minutes / 60)}
            </button>
          ))}
        </div>
        {win?.cheapest ? (
          <div className="mt-8">
            <p className="text-[15px] text-muted">{dayLabel}</p>
            <p className="text-[clamp(2.25rem,5vw,3rem)] leading-none font-semibold tracking-[-0.03em] tabular">
              {localTime(win.cheapest.start_utc)}–{localTime(win.cheapest.end_utc)}
            </p>
            <p className="mt-3 text-[17px]">
              {t.avg} {ore(win.cheapest.avg_ore_per_kwh, locale)} {t.priceUnit}
            </p>
            <ul className="mt-4 space-y-1 text-[15px] text-muted">
              {win.saving_vs_day_avg_ore_per_kwh !== undefined && (
                <li>{t.vsDayAverage(ore(win.saving_vs_day_avg_ore_per_kwh, locale))}</li>
              )}
              {win.saving_vs_dearest_ore_per_kwh !== undefined && (
                <li>{t.vsDearest(ore(win.saving_vs_dearest_ore_per_kwh, locale))}</li>
              )}
            </ul>
          </div>
        ) : (
          <p className="mt-8 text-[17px] text-muted">{dayIdx === 1 ? t.notPublished : t.noData}</p>
        )}
      </section>
    </div>
  );
}
