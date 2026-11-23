"use client";

import { useState } from "react";

import { dict, type Locale } from "@/lib/i18n";
import { setTheme, type Theme } from "@/lib/prefs";

const NEXT: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" };

export function ThemeToggle({ initial, locale }: { initial: Theme; locale: Locale }) {
  const [theme, set] = useState<Theme>(initial);
  return (
    <button
      type="button"
      className="underline-offset-4 hover:underline"
      onClick={() => {
        const next = NEXT[theme];
        set(next);
        if (next === "system") delete document.documentElement.dataset.theme;
        else document.documentElement.dataset.theme = next;
        void setTheme(next);
      }}
    >
      {dict[locale].theme[theme]}
    </button>
  );
}
