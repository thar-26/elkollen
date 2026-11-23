"use client";

import { useState } from "react";

import { ore } from "@/lib/format";
import type { Locale } from "@/lib/i18n";
import { AREAS } from "@/lib/types";

type Month = { month: string; days: number; kwh: number; paid_sek: number; could_have_paid_sek: number };
type Analysis = {
  data: {
    resolution_minutes: number;
    readings: number;
    total_kwh: number;
    paid_sek: number;
    could_have_paid_sek: number;
    saving_sek: number;
    avg_paid_ore_per_kwh: number | null;
    months: Month[];
  };
  notes: string[];
};

const T = {
  sv: {
    title: "Vad betalade du, och vad kunde du ha betalat?",
    intro:
      "Ladda upp din förbrukning som CSV (export från ditt elnätsbolag, per timme eller kvart). Filen analyseras i minnet och sparas inte.",
    file: "Förbrukningsfil (CSV)",
    area: "Elområde",
    flex: (p: number) => `Flyttbar andel av förbrukningen: ${p} %`,
    flexHelp: "Till exempel disk, tvätt och laddning av bil.",
    analyse: "Analysera",
    working: "Analyserar …",
    paid: "Du betalade",
    could: "Med flytt till billigaste fyra timmarna",
    saving: "Möjlig besparing",
    month: "Månad",
    paidCol: "Betalt (kr)",
    couldCol: "Kunde ha betalat (kr)",
    legendPaid: "Betalt",
    legendCould: "Kunde ha betalat",
    avgPaid: (v: string) => `Snittpris ${v} öre/kWh`,
    readings: (n: number, m: number) => `${n} mätvärden, ett per ${m} minuter`,
    error: "Filen kunde inte analyseras.",
  },
  en: {
    title: "What did you pay, and what could you have paid?",
    intro:
      "Upload your consumption as CSV (export from your grid company, hourly or 15-minute). The file is analysed in memory and not stored.",
    file: "Consumption file (CSV)",
    area: "Price area",
    flex: (p: number) => `Share of use you could move: ${p} %`,
    flexHelp: "For example dishwasher, laundry and car charging.",
    analyse: "Analyse",
    working: "Analysing …",
    paid: "You paid",
    could: "Moving it to the cheapest four hours",
    saving: "Possible saving",
    month: "Month",
    paidCol: "Paid (SEK)",
    couldCol: "Could have paid (SEK)",
    legendPaid: "Paid",
    legendCould: "Could have paid",
    avgPaid: (v: string) => `Average price ${v} öre/kWh`,
    readings: (n: number, m: number) => `${n} readings, one every ${m} minutes`,
    error: "The file could not be analysed.",
  },
};

export function UploadForm({ locale }: { locale: Locale }) {
  const t = T[locale];
  const [share, setShare] = useState(30);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Analysis | null>(null);
  const kr = (v: number) => ore(v, locale, 0);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const form = new FormData(e.currentTarget);
    form.set("flexible_share", String(share / 100));
    try {
      const res = await fetch("/api/upload", { method: "POST", body: form });
      const body = await res.json();
      if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : t.error);
      setResult(body as Analysis);
    } catch (err) {
      setResult(null);
      setError(err instanceof Error ? err.message : t.error);
    } finally {
      setBusy(false);
    }
  }

  const months = result?.data.months ?? [];
  const top = Math.max(1, ...months.map((m) => m.paid_sek));

  return (
    <div>
      <h1 className="max-w-[20ch] text-[clamp(2rem,5vw,3.5rem)] leading-[1.02] font-semibold tracking-[-0.03em]">
        {t.title}
      </h1>
      <p className="mt-4 max-w-prose text-[17px]">{t.intro}</p>

      <form onSubmit={submit} className="mt-10 grid max-w-xl gap-6">
        <label className="grid gap-2 text-[15px]">
          {t.file}
          <input
            name="file"
            type="file"
            accept=".csv,.txt,text/csv"
            required
            className="rounded-sm bg-raised px-3 py-3 text-[15px] file:mr-4 file:rounded-full file:border-0 file:bg-ink file:px-4 file:py-2 file:text-ground"
          />
        </label>
        <label className="grid gap-2 text-[15px]">
          {t.area}
          <select name="area" defaultValue="SE3" className="rounded-sm bg-raised px-3 py-3 text-[16px]">
            {AREAS.map((a) => (
              <option key={a}>{a}</option>
            ))}
          </select>
        </label>
        <label className="grid gap-2 text-[15px]">
          {t.flex(share)}
          <input
            type="range"
            min={0}
            max={100}
            step={5}
            value={share}
            onChange={(e) => setShare(Number(e.target.value))}
            className="accent-[var(--cheap)]"
          />
          <span className="text-muted">{t.flexHelp}</span>
        </label>
        <button
          type="submit"
          disabled={busy}
          className="justify-self-start rounded-full bg-cheap px-6 py-3 text-[16px] font-medium text-on-accent disabled:opacity-50"
        >
          {busy ? t.working : t.analyse}
        </button>
      </form>

      {error && (
        <p role="alert" className="mt-6 text-[16px] text-dear">
          {error}
        </p>
      )}

      {result && (
        <section aria-live="polite" className="mt-16">
          <dl className="flex flex-wrap gap-x-14 gap-y-6">
            <div>
              <dt className="text-[15px] text-muted">{t.paid}</dt>
              <dd className="text-[clamp(2.75rem,7vw,4.5rem)] leading-none font-semibold tracking-[-0.04em]">
                {kr(result.data.paid_sek)} kr
              </dd>
            </div>
            <div>
              <dt className="text-[15px] text-muted">{t.could}</dt>
              <dd className="text-[clamp(2rem,5vw,3rem)] leading-none font-semibold tracking-[-0.03em]">
                {kr(result.data.could_have_paid_sek)} kr
              </dd>
            </div>
            <div>
              <dt className="text-[15px] text-muted">{t.saving}</dt>
              <dd className="text-[clamp(2rem,5vw,3rem)] leading-none font-semibold tracking-[-0.03em] text-cheap">
                {kr(result.data.saving_sek)} kr
              </dd>
            </div>
          </dl>
          <p className="mt-4 text-[15px] text-muted">
            {result.data.avg_paid_ore_per_kwh !== null &&
              `${t.avgPaid(ore(result.data.avg_paid_ore_per_kwh, locale))} · `}
            {t.readings(result.data.readings, result.data.resolution_minutes)}
          </p>

          <div className="mt-10 flex gap-5 text-[14px] text-muted">
            <span className="flex items-center gap-2">
              <span aria-hidden className="inline-block h-3 w-3 rounded-[2px] bg-bar" /> {t.legendPaid}
            </span>
            <span className="flex items-center gap-2">
              <span aria-hidden className="inline-block h-3 w-3 rounded-[2px] bg-cheap" /> {t.legendCould}
            </span>
          </div>
          <table className="mt-3 w-full max-w-3xl text-[15px]">
            <thead>
              <tr className="text-left text-muted">
                <th scope="col" className="py-2 font-normal">{t.month}</th>
                <th scope="col" className="py-2 text-right font-normal">kWh</th>
                <th scope="col" className="py-2 text-right font-normal">{t.paidCol}</th>
                <th scope="col" className="py-2 text-right font-normal">{t.couldCol}</th>
                <th scope="col" className="w-2/5 py-2 pl-6 font-normal">
                  <span className="sr-only">{t.legendPaid}</span>
                </th>
              </tr>
            </thead>
            <tbody className="tabular">
              {months.map((m) => (
                <tr key={m.month} className="border-t border-grid">
                  <td className="py-2">{m.month}</td>
                  <td className="py-2 text-right">{ore(m.kwh, locale, 0)}</td>
                  <td className="py-2 text-right">{kr(m.paid_sek)}</td>
                  <td className="py-2 text-right">{kr(m.could_have_paid_sek)}</td>
                  <td className="py-2 pl-6" aria-hidden>
                    <span className="block h-2 rounded-r-[2px] bg-bar" style={{ width: `${(m.paid_sek / top) * 100}%` }} />
                    <span
                      className="mt-1 block h-2 rounded-r-[2px] bg-cheap"
                      style={{ width: `${(m.could_have_paid_sek / top) * 100}%` }}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <ul className="mt-6 max-w-prose space-y-1 text-[14px] text-muted">
            {result.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
