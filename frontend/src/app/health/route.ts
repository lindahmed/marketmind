export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const configured = process.env.BACKEND_API_URL;
    if (!configured && process.env.DEPLOYMENT_ENVIRONMENT === "production") throw new Error("Missing API URL");
    const base = new URL(configured || "http://127.0.0.1:8000");
    if (!["http:", "https:"].includes(base.protocol) || base.username || base.password
        || base.pathname !== "/" || base.search || base.hash) throw new Error("Invalid API URL");
    const response = await fetch(`${base.origin}/health`, {
      cache: "no-store", redirect: "manual", signal: AbortSignal.timeout(5_000),
    });
    if (!response.ok) throw new Error("API unavailable");
    return Response.json({ status: "ok" }, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ status: "unavailable" }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}
