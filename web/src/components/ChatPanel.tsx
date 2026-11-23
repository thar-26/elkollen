"use client";

import { useRef, useState } from "react";

import { signInAsDemo, signInWithGoogle } from "@/lib/auth-actions";
import { dict, type Locale } from "@/lib/i18n";
import type { ChatAnswer } from "@/lib/types";

type Turn = { role: "user" | "assistant"; content: string; meta?: ChatAnswer };
type Props = { locale: Locale; signedIn: boolean; demoLogin: boolean };

/** Pull the few numbers worth showing from a tool result. */
function keyNumbers(result: unknown): [string, string][] {
  const data = (result as { data?: Record<string, unknown> })?.data;
  if (!data || typeof data !== "object") return [];
  const out: [string, string][] = [];
  for (const [k, v] of Object.entries(data)) {
    if (typeof v === "number") out.push([k, String(v)]);
    else if (v && typeof v === "object" && !Array.isArray(v) && "avg_ore_per_kwh" in v) {
      out.push([`${k}.avg_ore_per_kwh`, String((v as { avg_ore_per_kwh: number }).avg_ore_per_kwh)]);
    } else if (k === "summary" && v && typeof v === "object") {
      for (const [sk, sv] of Object.entries(v)) if (typeof sv === "number") out.push([sk, String(sv)]);
    }
  }
  return out.slice(0, 8);
}

export function ChatPanel({ locale, signedIn, demoLogin }: Props) {
  const t = dict[locale];
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  async function ask(question: string) {
    const q = question.trim();
    if (!q || busy) return;
    setError(null);
    setBusy(true);
    const history = turns.map(({ role, content }) => ({ role, content }));
    setTurns((all) => [...all, { role: "user", content: q }]);
    setText("");
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: q, history, locale }),
      });
      if (res.status === 429) throw new Error(t.rateLimited);
      if (!res.ok) throw new Error(t.chatError);
      const body = (await res.json()) as ChatAnswer;
      setTurns((all) => [
        ...all,
        { role: "assistant", content: body.answer || body.error || t.chatError, meta: body },
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : t.chatError);
    } finally {
      setBusy(false);
      input.current?.focus();
    }
  }

  return (
    <section aria-labelledby="chat-heading" className="mx-auto max-w-3xl">
      <h2 id="chat-heading" className="text-[clamp(1.75rem,4vw,2.5rem)] font-semibold tracking-[-0.02em]">
        {t.chat}
      </h2>
      <p className="mt-3 max-w-prose text-[17px] text-muted">{t.chatIntro}</p>

      {!signedIn ? (
        <div className="mt-8 flex flex-wrap items-center gap-3">
          <p className="w-full text-[17px]">{t.signInToChat}</p>
          <form action={signInWithGoogle}>
            <button className="rounded-full bg-cheap px-5 py-3 text-[16px] font-medium text-on-accent hover:opacity-90">
              {t.signIn}
            </button>
          </form>
          {demoLogin &&
            [
              ["demo-anna", "Anna (demo)"],
              ["demo-erik", "Erik (demo)"],
            ].map(([id, name]) => (
              <form key={id} action={signInAsDemo}>
                <input type="hidden" name="user" value={id} />
                <button className="rounded-full bg-raised px-5 py-3 text-[16px] hover:bg-grid">
                  {t.signInDemo(name)}
                </button>
              </form>
            ))}
        </div>
      ) : (
        <>
          <ol className="mt-8 space-y-8" aria-live="polite" aria-busy={busy}>
            {turns.map((turn, i) => (
              <li key={i} className={turn.role === "user" ? "pl-0" : ""}>
                {turn.role === "user" ? (
                  <p className="inline-block rounded-2xl bg-raised px-4 py-3 text-[17px]">{turn.content}</p>
                ) : (
                  <div>
                    <p className="max-w-prose text-[17px] leading-relaxed whitespace-pre-line">
                      {turn.content.replace(/\*\*/g, "")}
                    </p>
                    {turn.meta && (
                      <>
                        <p className={`mt-3 text-[14px] ${turn.meta.grounding.ok ? "text-muted" : "text-dear"}`}>
                          {turn.meta.grounding.ok
                            ? t.verified
                            : `${t.unverified} ${[...turn.meta.grounding.ungrounded, ...turn.meta.grounding.unverified_dates].join(", ")}`}
                        </p>
                        {turn.meta.tool_calls.length > 0 && (
                          <details className="mt-3 rounded-sm bg-raised px-4 py-3 text-[14px]">
                            <summary className="cursor-pointer font-medium">{t.howAnswered}</summary>
                            <ul className="mt-3 space-y-4">
                              {turn.meta.tool_calls.map((call, j) => (
                                <li key={j}>
                                  <p>
                                    <span className="font-medium">{t.tools[call.tool] ?? call.tool}</span>{" "}
                                    <span className="text-muted">
                                      ({call.tool}, {call.ok ? t.toolOk : t.toolFailed})
                                    </span>
                                  </p>
                                  <p className="mt-1 text-muted break-words">
                                    {Object.entries(call.arguments)
                                      .map(([k, v]) => `${k}: ${String(v)}`)
                                      .join(" · ")}
                                  </p>
                                  {keyNumbers(call.result).length > 0 && (
                                    <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 tabular">
                                      {keyNumbers(call.result).map(([k, v]) => (
                                        <div key={k} className="contents">
                                          <dt className="text-muted">{k}</dt>
                                          <dd>{v}</dd>
                                        </div>
                                      ))}
                                    </dl>
                                  )}
                                </li>
                              ))}
                            </ul>
                            <p className="mt-3 text-muted">model: {turn.meta.model}</p>
                          </details>
                        )}
                      </>
                    )}
                  </div>
                )}
              </li>
            ))}
            {busy && <li className="text-[16px] text-muted">{t.thinking}</li>}
          </ol>

          {turns.length === 0 && (
            <div className="mt-6 flex flex-wrap gap-2">
              {t.examples.map((q) => (
                <button
                  key={q}
                  type="button"
                  onClick={() => ask(q)}
                  className="rounded-full bg-raised px-4 py-2 text-left text-[15px] hover:bg-grid"
                >
                  {q}
                </button>
              ))}
            </div>
          )}

          {error && (
            <p role="alert" className="mt-4 text-[15px] text-dear">
              {error}
            </p>
          )}

          <form
            className="mt-6 flex items-end gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              ask(text);
            }}
          >
            <label htmlFor="chat-input" className="sr-only">
              {t.chat}
            </label>
            <textarea
              id="chat-input"
              ref={input}
              rows={2}
              maxLength={1000}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  ask(text);
                }
              }}
              placeholder={t.placeholder}
              className="min-h-[3.5rem] flex-1 resize-y rounded-sm bg-raised px-4 py-3 text-[17px] placeholder:text-muted"
            />
            <button
              type="submit"
              disabled={busy || !text.trim()}
              className="rounded-full bg-cheap px-5 py-3 text-[16px] font-medium text-on-accent disabled:opacity-50"
            >
              {t.ask}
            </button>
          </form>
        </>
      )}
    </section>
  );
}
