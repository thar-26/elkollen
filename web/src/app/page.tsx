import { connection } from "next/server";
import { Suspense } from "react";

import { auth, demoLoginEnabled } from "@/auth";
import { ChatPanel } from "@/components/ChatPanel";
import { DayView } from "@/components/DayView";
import { Header } from "@/components/Header";
import { HtmlLang } from "@/components/HtmlLang";
import { getPublic } from "@/lib/backend";
import { stockholmDate } from "@/lib/format";
import { dict } from "@/lib/i18n";
import { readPrefs } from "@/lib/prefs";
import {
  AREAS,
  type Area,
  type DayData,
  DEVICES,
  type PricesResult,
  type WindowResult,
} from "@/lib/types";

/** The start of the current quarter-hour, as naive UTC ("2026-11-23T18:45:00"). */
function currentQuarterUtc(now = new Date()): string {
  const q = new Date(now);
  q.setUTCMinutes(Math.floor(q.getUTCMinutes() / 15) * 15, 0, 0);
  return q.toISOString().slice(0, 19);
}

async function loadDay(area: Area, date: string, fromUtc?: string): Promise<DayData> {
  const [prices, ...windows] = await Promise.all([
    getPublic<PricesResult>("/prices", { area, start_date: date, end_date: date }),
    ...DEVICES.map((d) =>
      getPublic<WindowResult>("/prices/cheapest-window", {
        area,
        day: date,
        duration_minutes: d.minutes,
        // Today: only windows that have not started yet are worth recommending.
        ...(fromUtc ? { earliest_start_utc: fromUtc } : {}),
      }),
    ),
  ]);
  const hasPrices = !!prices?.data.summary;
  return {
    date,
    prices: hasPrices ? prices : null,
    windows: Object.fromEntries(DEVICES.map((d, i) => [d.minutes, hasPrices ? windows[i] : null])),
  };
}

async function HomeContent({ searchParams }: { searchParams: PageProps<"/">["searchParams"] }) {
  await connection(); // per request: prices for "today", the clock and the session
  const params = await searchParams;
  const requested = typeof params.area === "string" ? params.area.toUpperCase() : "SE3";
  const area: Area = (AREAS as string[]).includes(requested) ? (requested as Area) : "SE3";
  const [{ locale, theme }, session] = await Promise.all([readPrefs(), auth()]);
  const t = dict[locale];
  const nowQuarter = currentQuarterUtc();
  const days = await Promise.all([
    loadDay(area, stockholmDate(0), nowQuarter),
    loadDay(area, stockholmDate(1)),
  ]);
  const nowUtc = new Date().toISOString().slice(0, 19);

  return (
    <>
      <HtmlLang locale={locale} />
      <Header area={area} locale={locale} theme={theme} userName={session?.user?.name} />
      <main className="mx-auto max-w-6xl px-4 pb-24 sm:px-8">
        <p className="mb-10 text-[17px] text-muted">{t.tagline}</p>
        <DayView days={days} area={area} locale={locale} nowUtc={nowUtc} />
        <div className="-mx-4 mt-28 bg-raised px-4 py-16 sm:-mx-8 sm:px-10">
          <ChatPanel locale={locale} signedIn={!!session} demoLogin={demoLoginEnabled} />
        </div>
      </main>
      <footer className="mx-auto max-w-6xl px-4 pb-12 text-[14px] text-muted sm:px-8">
        <p className="text-[clamp(2.5rem,9vw,6rem)] leading-none font-semibold tracking-[-0.04em] text-ink">
          {t.title}
        </p>
        <p className="mt-4">{t.source}</p>
      </footer>
    </>
  );
}

function Loading() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-6 sm:px-8" aria-busy="true">
      <p className="text-[22px] font-semibold tracking-[-0.02em]">Elkollen</p>
      <p className="mt-16 text-[17px] text-muted" role="status">
        Hämtar dagens priser … / Loading today&apos;s prices …
      </p>
      <div className="mt-8 h-[300px] max-w-3xl rounded-sm bg-raised" />
    </div>
  );
}

export default function Home({ searchParams }: PageProps<"/">) {
  return (
    <Suspense fallback={<Loading />}>
      <HomeContent searchParams={searchParams} />
    </Suspense>
  );
}
