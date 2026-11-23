import { auth } from "@/auth";
import { postAsUser } from "@/lib/backend";

/** Backend-for-frontend: the browser sends a question; this server-side route adds the
 *  signed-in user's identity as a short-lived backend token and forwards it to the
 *  FastAPI /chat endpoint. The browser never holds a backend token. */
export async function POST(request: Request) {
  const session = (await auth()) as { uid?: string } | null;
  if (!session?.uid) return Response.json({ detail: "sign in required" }, { status: 401 });

  let body: { message?: unknown; history?: unknown; locale?: unknown };
  try {
    body = await request.json();
  } catch {
    return Response.json({ detail: "invalid JSON" }, { status: 400 });
  }
  const payload = {
    message: typeof body.message === "string" ? body.message.slice(0, 1000) : "",
    history: Array.isArray(body.history) ? body.history.slice(-10) : [],
    locale: body.locale === "en" ? "en" : "sv",
  };
  try {
    const res = await postAsUser("/chat", session.uid, payload);
    return new Response(await res.text(), {
      status: res.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    return Response.json({ detail: "assistant unavailable" }, { status: 503 });
  }
}
