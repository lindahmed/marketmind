import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function proxy(request: NextRequest) {
  const configured = process.env.BACKEND_API_URL;
  if (!configured && process.env.DEPLOYMENT_ENVIRONMENT === "production") {
    return Response.json({ detail: "API connection is not configured" }, { status: 503 });
  }
  let target: URL;
  try {
    const base = new URL(configured || "http://127.0.0.1:8000");
    if (!["http:", "https:"].includes(base.protocol) || base.username || base.password
        || base.pathname !== "/" || base.search || base.hash) throw new Error("Invalid backend URL");
    target = new URL(base.origin);
    target.pathname = request.nextUrl.pathname;
    target.search = request.nextUrl.search;
  } catch {
    return Response.json({ detail: "API connection is not configured" }, { status: 503 });
  }
  const headers = new Headers();
  // Preserve the browser Origin for backend CSRF checks. Never invent an
  // allowed Origin or forward client-controlled host/proxy headers.
  for (const name of ["content-type", "cookie", "origin", "x-workspace-id", "authorization"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const safe = ["GET", "HEAD"].includes(request.method);
  // Bound memory even when a client omits Content-Length. Existing CSV files
  // are limited to 2 MiB; this leaves room for multipart framing.
  const maximum = 3 * 1024 * 1024;
  let body: Uint8Array | undefined;
  if (!safe && request.body) {
    const reader = request.body.getReader();
    const parts: Uint8Array[] = [];
    let size = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maximum) {
        await reader.cancel();
        return Response.json({ detail: "Request body is too large" }, { status: 413 });
      }
      parts.push(value);
    }
    body = new Uint8Array(size);
    let offset = 0;
    for (const part of parts) { body.set(part, offset); offset += part.byteLength; }
  }
  try {
    const upstream = await fetch(target, {
      method: request.method, headers, redirect: "manual", cache: "no-store",
      body: body as BodyInit | undefined,
      signal: AbortSignal.timeout(120_000),
    });
    // Do not relay redirects to arbitrary upstream URLs with credentials.
    if (upstream.status >= 300 && upstream.status < 400) {
      return Response.json({ detail: "Unexpected API redirect" }, { status: 502 });
    }
    const outgoing = new Headers({ "Cache-Control": "no-store" });
    const contentType = upstream.headers.get("content-type");
    if (contentType) outgoing.set("Content-Type", contentType);
    const retryAfter = upstream.headers.get("retry-after");
    if (retryAfter) outgoing.set("Retry-After", retryAfter);
    for (const cookie of upstream.headers.getSetCookie()) outgoing.append("Set-Cookie", cookie);
    return new Response(upstream.body, { status: upstream.status, headers: outgoing });
  } catch {
    console.error("api_proxy_failed");
    return Response.json({ detail: "Cannot reach the API. Please retry." }, { status: 502 });
  }
}

export const GET = proxy;
export const HEAD = proxy;
export const POST = proxy;
export const PUT = proxy;
export const DELETE = proxy;
export const OPTIONS = proxy;
