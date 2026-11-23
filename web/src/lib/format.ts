import type { Locale } from "./i18n";

const TZ = "Europe/Stockholm";

/** API timestamps are naive UTC ("2026-11-24T01:15:00"). */
export function utc(naive: string): Date {
  return new Date(naive.endsWith("Z") ? naive : `${naive}Z`);
}

/** HH:MM in Swedish local time, correct across clock changes. */
export function localTime(naiveUtc: string): string {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: TZ, hour: "2-digit", minute: "2-digit" }).format(
    utc(naiveUtc),
  );
}

export function stockholmDate(offsetDays = 0, now = new Date()): string {
  const today = new Intl.DateTimeFormat("sv-SE", { timeZone: TZ }).format(now); // YYYY-MM-DD
  const d = new Date(`${today}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + offsetDays);
  return d.toISOString().slice(0, 10);
}

export function longDate(isoDate: string, locale: Locale): string {
  return new Intl.DateTimeFormat(locale === "sv" ? "sv-SE" : "en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
    timeZone: "UTC",
  }).format(new Date(`${isoDate}T12:00:00Z`));
}

export function ore(value: number, locale: Locale, digits = 1): string {
  return new Intl.NumberFormat(locale === "sv" ? "sv-SE" : "en-GB", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}
