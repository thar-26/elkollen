const API = process.env.ELKOLLEN_API_URL ?? "http://127.0.0.1:8000";
const MAX_BYTES = 5_000_000;

/** Reads the uploaded file and forwards it as text for in-memory analysis. Nothing is
 *  written to disk or logged here or in the backend. */
export async function POST(request: Request) {
  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return Response.json({ detail: "expected a file upload" }, { status: 400 });
  }
  const file = form.get("file");
  if (!(file instanceof File)) return Response.json({ detail: "no file" }, { status: 400 });
  if (file.size > MAX_BYTES) {
    return Response.json({ detail: "file too large (max 5 MB)" }, { status: 413 });
  }
  const area = String(form.get("area") ?? "SE3");
  const share = Number(form.get("flexible_share") ?? 0.3);
  try {
    const res = await fetch(`${API}/consumption/analyse`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ area, csv: await file.text(), flexible_share: share }),
      cache: "no-store",
    });
    return new Response(await res.text(), {
      status: res.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    return Response.json({ detail: "analysis unavailable" }, { status: 503 });
  }
}
