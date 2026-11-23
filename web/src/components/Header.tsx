import Link from "next/link";

import { ThemeToggle } from "@/components/ThemeToggle";
import { signOutAction } from "@/lib/auth-actions";
import { dict, type Locale } from "@/lib/i18n";
import { setLocale, type Theme } from "@/lib/prefs";
import { AREAS, type Area } from "@/lib/types";

type Props = { area: Area; locale: Locale; theme: Theme; userName?: string | null };

export function Header({ area, locale, theme, userName }: Props) {
  const t = dict[locale];
  return (
    <header className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-8 gap-y-4 px-4 py-6 sm:px-8">
      <Link href="/" className="text-[22px] font-semibold tracking-[-0.02em]">
        {t.title}
      </Link>
      <nav aria-label={t.area} className="order-3 w-full sm:order-none sm:w-auto">
        <ul className="flex gap-1 rounded-full bg-raised p-1">
          {AREAS.map((a) => (
            <li key={a}>
              <Link
                href={`/?area=${a}`}
                aria-current={a === area ? "page" : undefined}
                className={`block rounded-full px-4 py-2 text-[15px] ${
                  a === area ? "bg-ink text-ground" : "hover:bg-grid"
                }`}
              >
                {a}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      <div className="ml-auto flex items-center gap-4 text-[15px]">
        <form action={setLocale.bind(null, locale === "sv" ? "en" : "sv")}>
          <button className="underline-offset-4 hover:underline" lang={locale === "sv" ? "en" : "sv"}>
            {t.language}
          </button>
        </form>
        <ThemeToggle initial={theme} locale={locale} />
        {userName && (
          <form action={signOutAction}>
            <button className="underline-offset-4 hover:underline" title={userName}>
              {t.signOut}
            </button>
          </form>
        )}
      </div>
    </header>
  );
}
