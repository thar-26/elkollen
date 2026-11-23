import type { Metadata, Viewport } from "next";
import { Schibsted_Grotesk } from "next/font/google";

import "./globals.css";

const schibsted = Schibsted_Grotesk({
  variable: "--font-schibsted",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Elkollen — spotpriset kvart för kvart",
  description:
    "Svenska spotpriser per kvart för SE1–SE4, billigaste tiden att köra disk eller ladda bilen, och en assistent som bara svarar med siffror ur databasen.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fbfbf8" },
    { media: "(prefers-color-scheme: dark)", color: "#121518" },
  ],
};

/* Runs before first paint: applies the saved theme and language from cookies, so the
   static shell never flashes the wrong colours. Values are whitelisted. */
const PREFS_SCRIPT = `(function(){try{var c=document.cookie;var t=(c.match(/(?:^|; )theme=(light|dark)/)||[])[1];if(t)document.documentElement.dataset.theme=t;var l=(c.match(/(?:^|; )lang=(sv|en)/)||[])[1];if(l)document.documentElement.lang=l;}catch(e){}})();`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="sv" suppressHydrationWarning className={`${schibsted.variable} h-full antialiased`}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: PREFS_SCRIPT }} />
      </head>
      <body className="min-h-full">{children}</body>
    </html>
  );
}
