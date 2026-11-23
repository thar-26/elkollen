import { Suspense } from "react";

import { auth } from "@/auth";
import { Header } from "@/components/Header";
import { HtmlLang } from "@/components/HtmlLang";
import { UploadForm } from "@/components/UploadForm";
import { readPrefs } from "@/lib/prefs";

async function UploadContent() {
  const [{ locale, theme }, session] = await Promise.all([readPrefs(), auth()]);
  return (
    <>
      <HtmlLang locale={locale} />
      <Header area="SE3" locale={locale} theme={theme} userName={session?.user?.name} />
      <main className="mx-auto max-w-6xl px-4 pt-6 pb-24 sm:px-8">
        <UploadForm locale={locale} />
      </main>
    </>
  );
}

export default function UploadPage() {
  return (
    <Suspense fallback={<p className="mx-auto max-w-6xl px-4 py-10 text-muted sm:px-8">…</p>}>
      <UploadContent />
    </Suspense>
  );
}
