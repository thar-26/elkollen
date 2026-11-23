"use client";

import { useState } from "react";

import { PriceChart } from "@/components/PriceChart";
import { localTime, longDate, ore } from "@/lib/format";
import { dict, type Locale } from "@/lib/i18n";
import { type Area, DEVICES, type DayData } from "@/lib/types";

type Props = { days: DayData[]; area: Area; locale: Locale; nowUtc: string };

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

        <h1 id="day-heading" className="text-[clamp(2rem,5vw,3.5rem)] leading-[1.02] font-semibold tracking-[-0.03em]">
          {t.chartTitle(dayLabel, area)}
        </h1>
        <p className="mt-2 text-[17px] text-muted first-letter:uppercase">{longDate(day.date, locale)}</p>

        {summary ? (
          <>
            <dl className="mt-8 flex flex-wrap items-end gap-x-10 gap-y-4">
              <div>
                <dt className="text-[15px] text-muted">{nowInterval ? t.now : t.avg}</dt>
                <dd className="text-[clamp(3rem,8vw,5.5rem)] leading-none font-semibold tracking-[-0.04em]">
                  {ore(nowInterval ? nowInterval.price_ore_per_kwh : summary.avg_ore_per_kwh, locale)}
                  <span className="ml-2 text-[18px] font-normal tracking-normal text-muted">{t.priceUnit}</span>
                </dd>
              </div>
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
              {t.chartNote} {hourly ? t.hourlyNote : ""}
            </p>
          </>
        ) : (
          <p className="mt-10 max-w-prose rounded-sm bg-raised p-6 text-[17px]">
            {dayIdx === 1 ? t.notPublished : t.noData}
          </p>
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
