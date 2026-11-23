"use client";

import { useEffect } from "react";

/** Keeps <html lang> in step with the chosen language (screen readers rely on it). */
export function HtmlLang({ locale }: { locale: string }) {
  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);
  return null;
}
