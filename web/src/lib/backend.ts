import { SignJWT } from "jose";

const API = process.env.ELKOLLEN_API_URL ?? "http://127.0.0.1:8000";

/** A 5-minute token for the FastAPI backend, minted on the server. The browser never
 *  sees it. Claims match elkollen_auth.verify in the Python backend. */
export async function backendToken(userId: string): Promise<string> {
  const secret = process.env.ELKOLLEN_JWT_SECRET;
  if (!secret || secret.length < 32) throw new Error("ELKOLLEN_JWT_SECRET is not set");
  return new SignJWT({ scope: "elkollen:read" })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuer("elkollen-web")
    .setAudience("elkollen-api")
    .setSubject(userId)
    .setIssuedAt()
    .setExpirationTime("5m")
    .setJti(crypto.randomUUID())
    .sign(new TextEncoder().encode(secret));
}

/** GET a public endpoint. Returns null instead of throwing, so pages render an
 *  empty state when the backend is down or has no data. */
export async function getPublic<T>(path: string, params: Record<string, string | number>): Promise<T | null> {
  const query = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]));
  try {
    const res = await fetch(`${API}${path}?${query}`, { next: { revalidate: 300 } });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

export async function postAsUser(path: string, userId: string, body: unknown): Promise<Response> {
  const token = await backendToken(userId);
  return fetch(`${API}${path}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
}
