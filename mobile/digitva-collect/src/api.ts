/**
 * JSON calls to the DigitVA device API (`/api/v1/device`). Errors follow the
 * contract `{"error": "<message>", "code": "<machine_code>"}`; the message is
 * never logged, only the status and code.
 */

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string | undefined
  ) {
    super(`HTTP ${status}${code ? ` ${code}` : ""}`);
    this.name = "ApiError";
  }
}

export const DEVICE_API = "/api/v1/device";

/**
 * Send one request and parse its JSON body. Non-2xx throws ApiError; a
 * network failure throws the fetch TypeError unchanged (the caller treats it
 * as "offline" and keeps local data).
 */
export async function requestJson<T>(
  server: string,
  path: string,
  init: { method?: string; body?: unknown; token?: string } = {}
): Promise<{ status: number; body: T }> {
  const headers: Record<string, string> = { accept: "application/json" };
  if (init.body !== undefined) headers["content-type"] = "application/json";
  if (init.token) headers.authorization = `Bearer ${init.token}`;
  const response = await fetch(`${server}${path}`, {
    method: init.method ?? "GET",
    headers,
    body: init.body === undefined ? undefined : JSON.stringify(init.body)
  });
  const text = await response.text();
  let body: unknown = undefined;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = undefined;
    }
  }
  if (!response.ok) {
    const code = typeof (body as { code?: unknown })?.code === "string" ? (body as { code: string }).code : undefined;
    throw new ApiError(response.status, code);
  }
  return { status: response.status, body: body as T };
}
