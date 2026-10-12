const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export async function api<T>(path: string, options: RequestInit = {}, workspaceId?: string): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (workspaceId) headers.set("X-Workspace-ID", workspaceId);
  let response: Response;
  try {
    response = await fetch(`${BASE}/api${path}`, { ...options, headers, credentials: "include", cache: "no-store" });
  } catch {
    throw new ApiError("Cannot reach the backend. Check that the API is running.", 0);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;
    const message = typeof detail === "string" ? detail : Array.isArray(detail)
      ? detail.map((item: { msg: string }) => item.msg).join("; ") : "Request failed. Please retry.";
    throw new ApiError(message, response.status);
  }
  return response.status === 204 ? undefined as T : response.json();
}
