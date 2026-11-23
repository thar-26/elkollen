"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";

import { windowIndexes, yDomain } from "@/lib/chart";
import { localTime, ore } from "@/lib/format";
import { dict, type Locale } from "@/lib/i18n";
import type { Interval, Window } from "@/lib/types";

type Props = {
  intervals: Interval[];
  cheapest: Window | null;
  dearest: Window | null;
  locale: Locale;
  title: string;
  nowUtc?: string;
};

const PAD = { left: 48, right: 8, top: 22, bottom: 30 };

export function PriceChart({ intervals, cheapest, dearest, locale, title, nowUtc }: Props) {
  const t = dict[locale];
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(720);
  const [active, setActive] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);
  const tableId = useId();

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) =>
      setWidth(Math.max(280, Math.floor(entry.contentRect.width))),
    );
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const starts = useMemo(() => intervals.map((i) => i.start_utc), [intervals]);
  const { min, max, ticks } = useMemo(
    () => yDomain(intervals.map((i) => i.price_ore_per_kwh)),
    [intervals],
  );
  const cheapSet = windowIndexes(starts, cheapest?.start_utc, cheapest?.end_utc);
  const dearSet = windowIndexes(starts, dearest?.start_utc, dearest?.end_utc);

  const narrow = width < 560;
  const height = narrow ? 230 : 300;
  const plotW = width - PAD.left - PAD.right;
  const plotH = height - PAD.top - PAD.bottom;
  const n = intervals.length;
  const band = plotW / Math.max(n, 1);
  const barW = Math.max(1, Math.min(24, band - 2)); // 2px surface gap between bars
  const y = (v: number) => PAD.top + ((max - v) / (max - min || 1)) * plotH;
  const x = (i: number) => PAD.left + i * band + (band - barW) / 2;
  const zeroY = y(0);
  const nowIdx = nowUtc
    ? intervals.findIndex((iv) => iv.start_utc <= nowUtc && nowUtc < iv.end_utc)
    : -1;
  const every = narrow ? 6 : 3;
  const xLabels = intervals
    .map((iv, i) => ({ i, label: localTime(iv.start_utc) }))
    .filter(({ label }) => label.endsWith(":00") && Number(label.slice(0, 2)) % every === 0);

  const fill = (i: number) =>
    cheapSet.has(i) ? "var(--cheap)" : dearSet.has(i) ? "var(--dear)" : "var(--bar)";
  const kind = (i: number) => (cheapSet.has(i) ? t.cheapest : dearSet.has(i) ? t.dearest : "");
  const describe = (i: number) => {
    const iv = intervals[i];
    const k = kind(i);
    return `${localTime(iv.start_utc)}–${localTime(iv.end_utc)}: ${ore(iv.price_ore_per_kwh, locale)} ${t.priceUnit}${k ? ` (${k.toLowerCase()})` : ""}`;
  };

  function bracket(set: Set<number>, color: string) {
    if (!set.size) return null;
    const idx = [...set];
    const a = Math.min(...idx);
    const b = Math.max(...idx);
    return (
      <rect
        x={PAD.left + a * band}
        y={PAD.top - 14}
        width={(b - a + 1) * band}
        height={4}
        rx={2}
        fill={color}
      />
    );
  }

  function onKey(e: React.KeyboardEvent) {
    if (!n) return;
    const cur = active ?? (nowIdx >= 0 ? nowIdx : 0);
    const moves: Record<string, number> = {
      ArrowRight: cur + 1,
      ArrowLeft: cur - 1,
      Home: 0,
      End: n - 1,
      PageUp: cur - 4,
      PageDown: cur + 4,
    };
    if (!(e.key in moves)) return;
    e.preventDefault();
    setActive(Math.max(0, Math.min(n - 1, moves[e.key])));
  }

  function onPointer(e: React.PointerEvent<SVGSVGElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const i = Math.floor((e.clientX - rect.left - PAD.left) / band);
    setActive(i >= 0 && i < n ? i : null);
  }

  return (
    <figure className="m-0">
      <div ref={wrap} className="relative w-full">
        <div
          role="group"
          tabIndex={0}
          aria-label={`${title}. ${t.chartNote}`}
          onKeyDown={onKey}
          onBlur={() => setActive(null)}
          className="rounded-sm"
        >
          <svg
            width={width}
            height={height}
            role="img"
            aria-label={title}
            onPointerMove={onPointer}
            onPointerLeave={() => setActive(null)}
            className="block touch-pan-y"
          >
            {ticks.map((v) => (
              <g key={v}>
                <line
                  x1={PAD.left}
                  x2={width - PAD.right}
                  y1={y(v)}
                  y2={y(v)}
                  stroke={v === 0 ? "var(--muted)" : "var(--grid)"}
                  strokeWidth={1}
                />
                <text
                  x={PAD.left - 8}
                  y={y(v)}
                  dy="0.32em"
                  textAnchor="end"
                  className="tabular fill-muted text-[12px]"
                >
                  {ore(v, locale, 0)}
                </text>
              </g>
            ))}
            {intervals.map((iv, i) => {
              const top = Math.min(y(iv.price_ore_per_kwh), zeroY);
              const h = Math.max(1, Math.abs(y(iv.price_ore_per_kwh) - zeroY));
              return (
                <rect
                  key={iv.start_utc}
                  x={x(i)}
                  y={top}
                  width={barW}
                  height={h}
                  rx={Math.min(2, barW / 2)}
                  fill={fill(i)}
                  opacity={active === null || active === i ? 1 : 0.55}
                />
              );
            })}
            {bracket(cheapSet, "var(--cheap)")}
            {bracket(dearSet, "var(--dear)")}
            {nowIdx >= 0 && (
              <g>
                <line
                  x1={x(nowIdx) + barW / 2}
                  x2={x(nowIdx) + barW / 2}
                  y1={PAD.top - 4}
                  y2={height - PAD.bottom}
                  stroke="var(--ink)"
                  strokeWidth={2}
                />
                <text
                  x={x(nowIdx) + barW / 2 + 4}
                  y={PAD.top + 8}
                  className="fill-ink text-[12px] font-semibold"
                >
                  {t.now}
                </text>
              </g>
            )}
            {xLabels.map(({ i, label }) => (
              <text
                key={label + i}
                x={PAD.left + i * band}
                y={height - 8}
                className="tabular fill-muted text-[12px]"
              >
                {label}
              </text>
            ))}
            <text x={4} y={12} className="fill-muted text-[12px]">
              {t.priceUnit}
            </text>
          </svg>
        </div>
        {active !== null && intervals[active] && (
          <div
            className="pointer-events-none absolute top-0 rounded-sm bg-ink px-2 py-1 text-[13px] text-ground tabular"
            style={{ left: Math.min(Math.max(0, x(active) - 60), width - 190) }}
          >
            {describe(active)}
          </div>
        )}
      </div>
      <p aria-live="polite" className="sr-only">
        {active !== null && intervals[active] ? describe(active) : ""}
      </p>

      <figcaption className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-[14px] text-muted">
        {cheapest && (
          <span className="flex items-center gap-2">
            <span aria-hidden className="inline-block h-3 w-3 rounded-[2px] bg-cheap" />
            {t.cheapest} {localTime(cheapest.start_utc)}–{localTime(cheapest.end_utc)}
          </span>
        )}
        {dearest && (
          <span className="flex items-center gap-2">
            <span aria-hidden className="inline-block h-3 w-3 rounded-[2px] bg-dear" />
            {t.dearest} {localTime(dearest.start_utc)}–{localTime(dearest.end_utc)}
          </span>
        )}
        <span className="flex items-center gap-2">
          <span aria-hidden className="inline-block h-3 w-3 rounded-[2px] bg-bar" />
          {t.otherQuarters}
        </span>
        <button
          type="button"
          onClick={() => setShowTable((s) => !s)}
          aria-expanded={showTable}
          aria-controls={tableId}
          className="ml-auto underline underline-offset-4 hover:text-ink"
        >
          {showTable ? t.hideTable : t.showTable}
        </button>
      </figcaption>

      <div id={tableId} hidden={!showTable} className="mt-4 max-h-96 overflow-y-auto">
        <table className="w-full text-[14px] tabular">
          <caption className="sr-only">{title}</caption>
          <thead>
            <tr className="text-left text-muted">
              <th scope="col" className="py-1 font-normal">
                {t.time}
              </th>
              <th scope="col" className="py-1 text-right font-normal">
                {t.price} ({t.priceUnit})
              </th>
              <th scope="col" className="py-1 pl-4 font-normal">
                <span className="sr-only">Status</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {intervals.map((iv, i) => (
              <tr key={iv.start_utc} className="border-t border-grid">
                <td className="py-1">
                  {localTime(iv.start_utc)}–{localTime(iv.end_utc)}
                </td>
                <td className="py-1 text-right">{ore(iv.price_ore_per_kwh, locale, 2)}</td>
                <td className="py-1 pl-4 text-muted">{kind(i)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </figure>
  );
}
