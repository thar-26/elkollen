"use server";

import { cookies } from "next/headers";

import type { Locale } from "./i18n";

const YEAR = 60 * 60 * 24 * 365;

export type Theme = "system" | "light" | "dark";

export async function setLocale(locale: Locale) {
  (await cookies()).set("lang", locale === "en" ? "en" : "sv", { maxAge: YEAR, sameSite: "lax" });
}

export async function setTheme(theme: Theme) {
  const value = ["light", "dark"].includes(theme) ? theme : "system";
  (await cookies()).set("theme", value, { maxAge: YEAR, sameSite: "lax" });
}

export async function readPrefs(): Promise<{ locale: Locale; theme: Theme }> {
  const jar = await cookies();
  const lang = jar.get("lang")?.value;
  const theme = jar.get("theme")?.value;
  return {
    locale: lang === "en" ? "en" : "sv",
    theme: theme === "light" || theme === "dark" ? theme : "system",
  };
}
