/**
 * Characterization of the two HTTP transports in src/api.ts (digitva-r8nh.20 slice 2b), pinned on the
 * code before they share one fetch path: the exact fetch call, success parsing, refusal ApiError fields,
 * network/offline/timeout classification. requestJson with a bearer token is requestOnce with no
 * csrf_failed retry; requestRaw is called directly. Edge cases where the two differ today are pinned
 * on purpose (204, manual redirects, malformed bodies, 8 MiB limits, body reader).
 */
const mockFetch = jest.fn();
(global as unknown as { fetch: unknown }).fetch = mockFetch;

import { Platform } from "react-native";
import { abortClientRequests, ApiError, requestJson, requestRaw, runAsBackground } from "../src/api";
import { NetworkError, OfflineError, resetNetwork, startNetworkWatch } from "../src/network";

const expoNetwork = require("expo-network") as { getNetworkStateAsync: jest.Mock };

const SERVER = "https://server.test";

type ResponseInit = {
  status?: number;
  headers?: Record<string, string>;
  json?: () => Promise<unknown>;
  text?: () => Promise<string>;
  redirected?: boolean;
  type?: string;
  url?: string;
};

function res({ status = 200, headers = { "content-type": "application/json" }, ...rest }: ResponseInit): Response {
  const lower = Object.fromEntries(Object.entries(headers).map(([key, value]) => [key.toLowerCase(), value]));
  return {
    status,
    ok: status >= 200 && status < 300,
    redirected: false,
    type: "basic",
    url: "",
    headers: { get: (name: string) => lower[name.toLowerCase()] ?? null },
    json: async () => { throw new Error("json() not expected"); },
    text: async () => { throw new Error("text() not expected"); },
    ...rest,
  } as unknown as Response;
}

const jsonRes = (status: number, body: unknown, headers: Record<string, string> = {}) => res({
  status,
  headers: { "content-type": "application/json", ...headers },
  json: async () => body,
  text: async () => JSON.stringify(body),
});

const init = (call = 0) => mockFetch.mock.calls[call][1] as RequestInit & { headers: Record<string, string> };

async function setOffline(offline: boolean) {
  expoNetwork.getNetworkStateAsync.mockResolvedValueOnce({ isConnected: !offline, isInternetReachable: !offline });
  startNetworkWatch();
  await new Promise((resolve) => setImmediate(resolve));
}

/** fetch that settles only when its signal aborts, rejecting with *error*. */
function hangUntilAbort(error: Error) {
  mockFetch.mockImplementationOnce((_url: string, requestInit: RequestInit) => new Promise((_resolve, reject) => {
    requestInit.signal!.addEventListener("abort", () => reject(error));
  }));
}

beforeEach(() => {
  mockFetch.mockReset();
  resetNetwork();
});

describe("requestJson (requestOnce) request", () => {
  it("sends a bearer JSON write with exactly these fetch options", async () => {
    mockFetch.mockResolvedValueOnce(jsonRes(200, { ok: true }));
    await requestJson(SERVER, "/api/v1/intake/deaths", { method: "POST", body: { a: 1 }, token: "tok" });
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(mockFetch.mock.calls[0][0]).toBe(`${SERVER}/api/v1/intake/deaths`);
    expect(Object.keys(init())).toEqual(["method", "credentials", "cache", "headers", "body", "signal", "redirect"]);
    expect(init()).toStrictEqual({
      method: "POST",
      credentials: "omit",
      cache: "no-store",
      headers: { Accept: "application/json", "Content-Type": "application/json", Authorization: "Bearer tok" },
      body: JSON.stringify({ a: 1 }),
      signal: expect.any(AbortSignal),
      redirect: "follow",
    });
    expect(Object.keys(init().headers)).toEqual(["Accept", "Content-Type", "Authorization"]);
  });

  it("sends a bearer GET with no body and no content type, keeping the body key", async () => {
    mockFetch.mockResolvedValueOnce(jsonRes(200, {}));
    await requestJson(SERVER, "/api/v1/me/access", { token: "tok" });
    expect(init()).toStrictEqual({
      method: "GET",
      credentials: "omit",
      cache: "no-store",
      headers: { Accept: "application/json", Authorization: "Bearer tok" },
      body: undefined,
      signal: expect.any(AbortSignal),
      redirect: "follow",
    });
    expect("body" in init()).toBe(true);
  });

  it("takes `json` when `body` is absent, and `body` over `json`", async () => {
    mockFetch.mockResolvedValue(jsonRes(200, {}));
    await requestJson(SERVER, "/p", { method: "PUT", json: { j: 1 }, token: "t" });
    await requestJson(SERVER, "/p", { method: "PUT", json: { j: 1 }, body: { b: 2 }, token: "t" });
    expect(init(0).body).toBe(JSON.stringify({ j: 1 }));
    expect(init(1).body).toBe(JSON.stringify({ b: 2 }));
  });

  it("sends a raw file body as octet-stream with its SHA-256, the same bytes object, ignoring json", async () => {
    mockFetch.mockResolvedValueOnce(jsonRes(201, { stored: true }));
    const bytes = new Uint8Array([1, 2, 3]);
    await requestJson(SERVER, "/api/v1/intake/drafts/d/attachments/f", {
      method: "PUT", rawBody: { bytes, sha256: "ab".repeat(32) }, json: { ignored: true }, token: "tok",
    });
    expect(init().headers).toStrictEqual({
      Accept: "application/json",
      "Content-Type": "application/octet-stream",
      "X-Content-SHA256": "ab".repeat(32),
      Authorization: "Bearer tok",
    });
    expect(init().body).toBe(bytes);
  });

  it("omits X-Content-SHA256 when the raw body has no hash", async () => {
    mockFetch.mockResolvedValueOnce(jsonRes(200, {}));
    await requestJson(SERVER, "/p", { method: "PUT", rawBody: { bytes: new Uint8Array([9]) }, token: "t" });
    expect(init().headers).toStrictEqual({
      Accept: "application/json", "Content-Type": "application/octet-stream", Authorization: "Bearer t",
    });
  });

  it("uses manual redirect mode when allowRedirect is set", async () => {
    mockFetch.mockResolvedValueOnce(jsonRes(200, {}));
    await requestJson(SERVER, "/p", { allowRedirect: true, token: "t" });
    expect(init().redirect).toBe("manual");
  });

  it("server cookie-less (explicit server, no token): omit credentials, snapshot CSRF, no launch token", async () => {
    (globalThis as { __DIGITVA_LAUNCH_TOKEN__?: unknown }).__DIGITVA_LAUNCH_TOKEN__ = "launch";
    try {
      mockFetch.mockResolvedValueOnce(jsonRes(200, {}, { "X-CSRFToken": "ignored-for-server" }));
      const result = await requestJson(SERVER, "/p", { csrf: { header: "X-CSRFToken", token: "snap" }, background: true });
      expect(init().credentials).toBe("omit");
      expect(init().headers).toStrictEqual({ Accept: "application/json", "X-CSRFToken": "snap", "X-DigitVA-Background": "1" });
      expect(result).toStrictEqual({ status: 200, body: {} });
    } finally {
      delete (globalThis as { __DIGITVA_LAUNCH_TOKEN__?: unknown }).__DIGITVA_LAUNCH_TOKEN__;
    }
  });
});

describe("requestJson (requestOnce) responses", () => {
  it("returns status and the object body, without csrf for bearer calls", async () => {
    mockFetch.mockResolvedValueOnce(jsonRes(201, { id: "x" }, { "X-CSRFToken": "not-read" }));
    await expect(requestJson(SERVER, "/p", { token: "t" })).resolves.toStrictEqual({ status: 201, body: { id: "x" } });
  });

  it("returns 204 with an undefined body without reading it", async () => {
    mockFetch.mockResolvedValueOnce(res({ status: 204, headers: {} }));
    await expect(requestJson(SERVER, "/p", { token: "t" })).resolves.toStrictEqual({ status: 204, body: undefined });
  });

  it("accepts a JSON list only with allowList", async () => {
    mockFetch.mockResolvedValueOnce(jsonRes(200, [1, 2]));
    await expect(requestJson(SERVER, "/p", { token: "t", allowList: true })).resolves.toStrictEqual({ status: 200, body: [1, 2] });
    mockFetch.mockResolvedValueOnce(jsonRes(200, [1, 2]));
    await expect(requestJson(SERVER, "/p", { token: "t" })).rejects.toMatchObject({ status: 200, code: "malformed_response" });
  });

  it("refuses unparsable JSON on success as malformed_response", async () => {
    mockFetch.mockResolvedValueOnce(res({ json: async () => { throw new SyntaxError("bad"); } }));
    const error = await requestJson(SERVER, "/api/v1/cases/12345", { token: "t" }).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 200, code: "malformed_response", path: "/api/v1/cases/:id", method: "GET", redirectUrl: undefined });
  });

  it("refuses a non-JSON success (an HTML page) as redirected_response after reading text", async () => {
    const text = jest.fn(async () => "<html>");
    mockFetch.mockResolvedValueOnce(res({ headers: { "content-type": "text/html" }, text }));
    await expect(requestJson(SERVER, "/p", { method: "POST", token: "t" })).rejects.toMatchObject({
      status: 200, code: "redirected_response", path: "/p", method: "POST",
    });
    expect(text).toHaveBeenCalledTimes(1);
  });

  it("matches the JSON content type case-sensitively", async () => {
    mockFetch.mockResolvedValueOnce(res({ headers: { "content-type": "Application/JSON" }, text: async () => "{}" }));
    await expect(requestJson(SERVER, "/p", { token: "t" })).rejects.toMatchObject({ code: "redirected_response" });
  });

  it("refuses a followed redirect as redirected_response", async () => {
    mockFetch.mockResolvedValueOnce(res({ redirected: true, url: `${SERVER}/login`, json: async () => ({}) }));
    await expect(requestJson(SERVER, "/p", { token: "t" })).rejects.toMatchObject({ status: 200, code: "redirected_response" });
  });

  it("returns a manual redirect (allowRedirect) as its status with the parsed body", async () => {
    mockFetch.mockResolvedValueOnce(res({ status: 0, type: "opaqueredirect", headers: {}, text: async () => "" }));
    await expect(requestJson(SERVER, "/p", { token: "t", allowRedirect: true })).resolves.toStrictEqual({ status: 0, body: {} });
    mockFetch.mockResolvedValueOnce(jsonRes(302, { moved: true }));
    await expect(requestJson(SERVER, "/p", { token: "t", allowRedirect: true })).resolves.toStrictEqual({ status: 302, body: { moved: true } });
  });

  it("maps a JSON refusal to ApiError with status, code, payload and masked route", async () => {
    const payload = { error: "Not allowed", code: "no_allocation", extra: 1 };
    mockFetch.mockResolvedValueOnce(jsonRes(409, payload));
    const error = await requestJson(SERVER, "/api/v1/intake/drafts/0123456789abcdef?x=1", { method: "PATCH", token: "t" })
      .catch((caught: unknown) => caught) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.name).toBe("ApiError");
    expect(error.message).toBe("HTTP 409 no_allocation");
    expect(error).toMatchObject({ status: 409, code: "no_allocation", payload, path: "/api/v1/intake/drafts/:id", method: "PATCH" });
    expect(error.csrf).toBeUndefined();
    expect(error.redirectUrl).toBeUndefined();
  });

  it("gives a refusal without a string code an undefined code and its payload", async () => {
    mockFetch.mockResolvedValueOnce(jsonRes(500, { code: 7 }));
    const error = await requestJson(SERVER, "/p", { token: "t" }).catch((caught: unknown) => caught) as ApiError;
    expect(error).toMatchObject({ status: 500, code: undefined, payload: { code: 7 } });
    expect(error.message).toBe("HTTP 500");
  });

  it("refuses an unparsable or list refusal body with an empty payload", async () => {
    mockFetch.mockResolvedValueOnce(res({ status: 400, json: async () => { throw new SyntaxError("x"); } }));
    await expect(requestJson(SERVER, "/p", { token: "t" })).rejects.toMatchObject({ status: 400, code: undefined, payload: {} });
    mockFetch.mockResolvedValueOnce(jsonRes(400, ["a"]));
    await expect(requestJson(SERVER, "/p", { token: "t", allowList: true })).rejects.toMatchObject({ status: 400, code: undefined, payload: {} });
  });

  it("refuses a non-JSON refusal (an HTML error page) as redirected_response", async () => {
    mockFetch.mockResolvedValueOnce(res({ status: 502, headers: { "content-type": "text/html" }, text: async () => "<html>" }));
    await expect(requestJson(SERVER, "/p", { token: "t" })).rejects.toMatchObject({ status: 502, code: "redirected_response" });
  });
});

describe("requestJson (requestOnce) network and timeouts", () => {
  it("passes a fetch TypeError through unchanged", async () => {
    const failure = new TypeError("Network request failed");
    mockFetch.mockRejectedValueOnce(failure);
    await expect(requestJson(SERVER, "/p", { token: "t" })).rejects.toBe(failure);
  });

  it("turns a plain Error from fetch into NetworkError", async () => {
    mockFetch.mockRejectedValueOnce(new Error("fetch failed: Could not connect"));
    const error = await requestJson(SERVER, "/p", { token: "t" }).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(NetworkError);
    expect(error).toBeInstanceOf(TypeError);
    expect((error as Error).message).toBe("fetch failed: Could not connect");
  });

  it("throws OfflineError without calling fetch while offline", async () => {
    await setOffline(true);
    await expect(requestJson(SERVER, "/p", { token: "t" })).rejects.toBeInstanceOf(OfflineError);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("aborts at timeoutMs and surfaces the abort rejection as is", async () => {
    const aborted = new Error("aborted");
    hangUntilAbort(aborted);
    await expect(requestJson(SERVER, "/p", { token: "t", timeoutMs: 5 })).rejects.toBe(aborted);
    expect(init().signal!.aborted).toBe(true);
  });

  it("keeps the timeout over the body read: a hung json() is aborted", async () => {
    const aborted = new Error("body aborted");
    mockFetch.mockImplementationOnce(async (_url: string, requestInit: RequestInit) => res({
      json: () => new Promise((_resolve, reject) => requestInit.signal!.addEventListener("abort", () => reject(aborted))),
    }));
    await expect(requestJson(SERVER, "/p", { token: "t", timeoutMs: 5 })).rejects.toBe(aborted);
  });

  it("aborts when the caller's signal aborts, with the caller's reason", async () => {
    const caller = new AbortController();
    let seenReason: unknown;
    mockFetch.mockImplementationOnce((_url: string, requestInit: RequestInit) => new Promise((_resolve, reject) => {
      requestInit.signal!.addEventListener("abort", () => {
        seenReason = requestInit.signal!.reason;
        reject(new Error("caller aborted"));
      });
    }));
    const pending = requestJson(SERVER, "/p", { token: "t", signal: caller.signal });
    caller.abort("left the screen");
    await expect(pending).rejects.toThrow("caller aborted");
    expect(seenReason).toBe("left the screen");
  });

  it("starts already aborted when the caller's signal is aborted", async () => {
    const caller = new AbortController();
    caller.abort("gone");
    mockFetch.mockImplementationOnce(async (_url: string, requestInit: RequestInit) => {
      expect(requestInit.signal!.aborted).toBe(true);
      expect(requestInit.signal!.reason).toBe("gone");
      throw new TypeError("aborted");
    });
    await expect(requestJson(SERVER, "/p", { token: "t", signal: caller.signal })).rejects.toThrow("aborted");
  });

  it("detaches from the caller's signal once settled", async () => {
    const caller = new AbortController();
    const remove = jest.spyOn(caller.signal, "removeEventListener");
    mockFetch.mockResolvedValueOnce(jsonRes(200, {}));
    await requestJson(SERVER, "/p", { token: "t", signal: caller.signal });
    expect(remove).toHaveBeenCalledWith("abort", expect.any(Function));
  });

  it("records the server Date only on success", async () => {
    const phoneClock = require("../src/phoneClock") as typeof import("../src/phoneClock");
    const record = jest.spyOn(phoneClock, "recordServerDate");
    mockFetch.mockResolvedValueOnce(jsonRes(200, {}, { Date: "Tue, 24 Nov 2026 10:00:00 GMT" }));
    await requestJson(SERVER, "/p", { token: "t" });
    mockFetch.mockResolvedValueOnce(jsonRes(500, {}, { Date: "Tue, 24 Nov 2026 11:00:00 GMT" }));
    await requestJson(SERVER, "/p", { token: "t" }).catch(() => undefined);
    mockFetch.mockResolvedValueOnce(res({ headers: { "content-type": "application/json", Date: "Tue, 24 Nov 2026 12:00:00 GMT" }, text: async () => "{}" }));
    await requestRaw(SERVER, "/p", { token: "t" });
    expect(record.mock.calls).toEqual([["Tue, 24 Nov 2026 10:00:00 GMT"], ["Tue, 24 Nov 2026 12:00:00 GMT"]]);
    record.mockRestore();
  });
});

describe("requestRaw request", () => {
  it("sends a bearer GET with conditional and gzip headers and no body key", async () => {
    mockFetch.mockResolvedValueOnce(jsonRes(200, { definition: true }));
    const etag = `"${"a".repeat(64)}"`;
    await requestRaw(SERVER, "/api/v1/forms/def", { token: "tok", ifNoneMatch: etag, acceptGzip: true });
    expect(mockFetch.mock.calls[0][0]).toBe(`${SERVER}/api/v1/forms/def`);
    expect(Object.keys(init())).toEqual(["method", "credentials", "cache", "headers", "signal", "redirect"]);
    const gzip: Record<string, string> = Platform.OS !== "web" ? { "Accept-Encoding": "gzip" } : {};
    expect(init()).toStrictEqual({
      method: "GET",
      credentials: "omit",
      cache: "no-store",
      headers: { Accept: "application/json", Authorization: "Bearer tok", "If-None-Match": etag, ...gzip },
      signal: expect.any(AbortSignal),
      redirect: "follow",
    });
    expect(Object.keys(init().headers)).toEqual(["Accept", "Authorization", "If-None-Match", ...Object.keys(gzip)]);
  });

  it("never sends a body or content type, even when given json, rawBody or a method", async () => {
    mockFetch.mockResolvedValueOnce(jsonRes(200, {}));
    await requestRaw(SERVER, "/p", {
      method: "POST", json: { a: 1 }, rawBody: { bytes: new Uint8Array([1]), sha256: "f".repeat(64) }, token: "t",
    });
    expect(init().method).toBe("POST");
    expect("body" in init()).toBe(false);
    expect(init().headers).toStrictEqual({ Accept: "application/json", Authorization: "Bearer t" });
  });

  it("refuses a malformed If-None-Match with 400 invalid_request before going online or calling fetch", async () => {
    await setOffline(true);
    const error = await requestRaw(SERVER, "/api/v1/x/12345", { token: "t", ifNoneMatch: "W/\"x\"", method: "GET" })
      .catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 400, code: "invalid_request", path: "/api/v1/x/:id", method: "GET" });
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("labels requests made inside runAsBackground, for non-bearer calls only", async () => {
    mockFetch.mockResolvedValue(jsonRes(200, {}));
    await runAsBackground(async () => {
      await requestRaw(SERVER, "/p", {});
      await requestRaw(SERVER, "/p", { token: "t" });
      await requestJson(SERVER, "/p", {});
      await requestJson(SERVER, "/p", { token: "t" });
    });
    expect(init(0).headers).toStrictEqual({ Accept: "application/json", "X-DigitVA-Background": "1" });
    expect(init(1).headers).toStrictEqual({ Accept: "application/json", Authorization: "Bearer t" });
    expect(init(2).headers).toStrictEqual({ Accept: "application/json", "X-DigitVA-Background": "1" });
    expect(init(3).headers).toStrictEqual({ Accept: "application/json", Authorization: "Bearer t" });
  });

  it("adds training=1 when the CSRF snapshot is a training one, unless the path has it", async () => {
    mockFetch.mockResolvedValue(jsonRes(200, {}));
    const training = { header: "X-CSRFToken", token: "s", training: true } as never;
    await requestRaw(SERVER, "/p", { csrf: training });
    await requestRaw(SERVER, "/p?a=1", { csrf: training });
    await requestRaw(SERVER, "/p?training=0", { csrf: training });
    await requestJson(SERVER, "/q", { csrf: training });
    expect(mockFetch.mock.calls.map((call) => call[0])).toEqual([
      `${SERVER}/p?training=1`, `${SERVER}/p?a=1&training=1`, `${SERVER}/p?training=0`, `${SERVER}/q?training=1`,
    ]);
  });
});

describe("requestRaw responses", () => {
  it("returns the body text and the definition headers, reading text() only", async () => {
    const json = jest.fn();
    mockFetch.mockResolvedValueOnce(res({
      headers: { "content-type": "application/json", ETag: '"e"', "X-Definition-SHA256": "c".repeat(64), "Content-Encoding": "gzip" },
      text: async () => '{"a":1}',
      json,
    }));
    await expect(requestRaw(SERVER, "/p", { token: "t" })).resolves.toStrictEqual({
      status: 200,
      body: '{"a":1}',
      headers: { etag: '"e"', definitionSha256: "c".repeat(64), contentEncoding: "gzip" },
    });
    expect(json).not.toHaveBeenCalled();
  });

  it("returns non-JSON text on success as is (no JSON parse)", async () => {
    mockFetch.mockResolvedValueOnce(res({ text: async () => "not json" }));
    await expect(requestRaw(SERVER, "/p", { token: "t" })).resolves.toMatchObject({ status: 200, body: "not json" });
  });

  it("accepts the JSON content type case-insensitively", async () => {
    mockFetch.mockResolvedValueOnce(res({ headers: { "content-type": "Application/JSON" }, text: async () => "{}" }));
    await expect(requestRaw(SERVER, "/p", { token: "t" })).resolves.toMatchObject({ status: 200, body: "{}" });
  });

  it("returns 304 with a null body without reading it, with or without a content type", async () => {
    mockFetch.mockResolvedValueOnce(res({ status: 304, headers: { ETag: '"e"' } }));
    await expect(requestRaw(SERVER, "/p", { token: "t" })).resolves.toStrictEqual({
      status: 304, body: null, headers: { etag: '"e"', definitionSha256: null, contentEncoding: null },
    });
    mockFetch.mockResolvedValueOnce(res({ status: 304 }));
    await expect(requestRaw(SERVER, "/p", { token: "t" })).resolves.toMatchObject({ status: 304, body: null });
  });

  it("refuses 204 without a content type as redirected_response", async () => {
    mockFetch.mockResolvedValueOnce(res({ status: 204, headers: {} }));
    await expect(requestRaw(SERVER, "/p", { token: "t" })).rejects.toMatchObject({ status: 204, code: "redirected_response" });
  });

  it("refuses any redirect, manual or followed, as redirected_response", async () => {
    mockFetch.mockResolvedValueOnce(res({ status: 0, type: "opaqueredirect", headers: {} }));
    await expect(requestRaw(SERVER, "/p", { token: "t", allowRedirect: true })).rejects.toMatchObject({ status: 0, code: "redirected_response" });
    expect(init().redirect).toBe("manual");
    mockFetch.mockResolvedValueOnce(res({ redirected: true, text: async () => "{}" }));
    await expect(requestRaw(SERVER, "/p", { token: "t" })).rejects.toMatchObject({ status: 200, code: "redirected_response" });
  });

  it("refuses a declared body over 8 MiB before reading it", async () => {
    mockFetch.mockResolvedValueOnce(res({ headers: { "content-type": "application/json", "Content-Length": String(8 * 1024 * 1024 + 1) } }));
    await expect(requestRaw(SERVER, "/p", { method: "POST", token: "t" })).rejects.toMatchObject({
      status: 200, code: "response_too_large", path: "/p", method: "POST",
    });
  });

  it("refuses a decoded body over 8 MiB of UTF-8", async () => {
    mockFetch.mockResolvedValueOnce(res({ text: async () => "é".repeat(4 * 1024 * 1024 + 1) }));
    await expect(requestRaw(SERVER, "/p", { token: "t" })).rejects.toMatchObject({ code: "response_too_large" });
    mockFetch.mockResolvedValueOnce(res({ text: async () => "é".repeat(4 * 1024 * 1024) }));
    await expect(requestRaw(SERVER, "/p", { token: "t" })).resolves.toMatchObject({ status: 200 });
  });

  it("refuses a failed body read as malformed_response", async () => {
    mockFetch.mockResolvedValueOnce(res({ text: async () => { throw new Error("stream broke"); } }));
    await expect(requestRaw(SERVER, "/p", { token: "t" })).rejects.toMatchObject({ status: 200, code: "malformed_response" });
  });

  it("maps a JSON refusal to ApiError with code and payload", async () => {
    mockFetch.mockResolvedValueOnce(jsonRes(404, { error: "gone", code: "not_found" }));
    const error = await requestRaw(SERVER, "/api/v1/forms/0123456789abcdef", { token: "t" }).catch((caught: unknown) => caught) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.message).toBe("HTTP 404 not_found");
    expect(error).toMatchObject({ status: 404, code: "not_found", payload: { error: "gone", code: "not_found" }, path: "/api/v1/forms/:id", method: "GET" });
  });

  it("keeps an empty payload and no code for an unparsable or list refusal body", async () => {
    mockFetch.mockResolvedValueOnce(res({ status: 500, text: async () => "oops" }));
    await expect(requestRaw(SERVER, "/p", { token: "t" })).rejects.toMatchObject({ status: 500, code: undefined, payload: {} });
    mockFetch.mockResolvedValueOnce(res({ status: 500, text: async () => "[1]" }));
    await expect(requestRaw(SERVER, "/p", { token: "t" })).rejects.toMatchObject({ status: 500, code: undefined, payload: {} });
  });

  it("refuses a non-JSON refusal as redirected_response", async () => {
    mockFetch.mockResolvedValueOnce(res({ status: 403, headers: { "content-type": "text/html" } }));
    await expect(requestRaw(SERVER, "/p", { token: "t" })).rejects.toMatchObject({ status: 403, code: "redirected_response" });
  });
});

describe("requestRaw network and timeouts", () => {
  it("passes a fetch TypeError through and wraps a plain Error as NetworkError", async () => {
    const failure = new TypeError("Network request failed");
    mockFetch.mockRejectedValueOnce(failure);
    await expect(requestRaw(SERVER, "/p", { token: "t" })).rejects.toBe(failure);
    mockFetch.mockRejectedValueOnce(new Error("fetch failed"));
    await expect(requestRaw(SERVER, "/p", { token: "t" })).rejects.toBeInstanceOf(NetworkError);
  });

  it("throws OfflineError without calling fetch while offline", async () => {
    await setOffline(true);
    await expect(requestRaw(SERVER, "/p", { token: "t" })).rejects.toBeInstanceOf(OfflineError);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("aborts at timeoutMs and surfaces the abort rejection as is", async () => {
    const aborted = new Error("aborted");
    hangUntilAbort(aborted);
    await expect(requestRaw(SERVER, "/p", { token: "t", timeoutMs: 5 })).rejects.toBe(aborted);
  });

  it("keeps the timeout over the body read: a hung text() is aborted and rethrown as is", async () => {
    const aborted = new Error("body aborted");
    mockFetch.mockImplementationOnce(async (_url: string, requestInit: RequestInit) => res({
      text: () => new Promise((_resolve, reject) => requestInit.signal!.addEventListener("abort", () => reject(aborted))),
    }));
    await expect(requestRaw(SERVER, "/p", { token: "t", timeoutMs: 5 })).rejects.toBe(aborted);
  });
});

describe("cookie session (same origin, no server, no token)", () => {
  afterEach(() => {
    delete (globalThis as { __DIGITVA_LAUNCH_TOKEN__?: unknown }).__DIGITVA_LAUNCH_TOKEN__;
  });

  it("includes credentials, the snapshot CSRF, the launch token and the background label", async () => {
    (globalThis as { __DIGITVA_LAUNCH_TOKEN__?: unknown }).__DIGITVA_LAUNCH_TOKEN__ = " launch ";
    mockFetch.mockResolvedValue(jsonRes(200, {}));
    const csrf = { header: "X-CSRFToken", token: "snap" };
    await requestJson("", "/api/v1/x", { method: "POST", json: {}, csrf, background: true });
    await requestRaw("", "/api/v1/y", { csrf, background: true });
    expect(init(0)).toStrictEqual({
      method: "POST", credentials: "include", cache: "no-store",
      headers: {
        Accept: "application/json", "Content-Type": "application/json",
        "X-CSRFToken": "snap", "X-DigitVA-Launch-Token": "launch", "X-DigitVA-Background": "1",
      },
      body: "{}", signal: expect.any(AbortSignal), redirect: "follow",
    });
    expect(init(1)).toStrictEqual({
      method: "GET", credentials: "include", cache: "no-store",
      headers: { Accept: "application/json", "X-CSRFToken": "snap", "X-DigitVA-Launch-Token": "launch", "X-DigitVA-Background": "1" },
      signal: expect.any(AbortSignal), redirect: "follow",
    });
  });

  it("abortClientRequests aborts in-flight cookie requests of both transports, not bearer ones", async () => {
    const outcomes: string[] = [];
    mockFetch.mockImplementation((url: string, requestInit: RequestInit) => new Promise((resolve, reject) => {
      requestInit.signal!.addEventListener("abort", () => reject(new Error(`aborted ${url}`)));
      if (url.includes("bearer")) setTimeout(() => resolve(jsonRes(200, {})), 20);
    }));
    const pending = [
      requestJson("", "/cookie-json", {}).then(() => outcomes.push("json ok"), (e: Error) => outcomes.push(e.message)),
      requestRaw("", "/cookie-raw", {}).then(() => outcomes.push("raw ok"), (e: Error) => outcomes.push(e.message)),
      requestJson(SERVER, "/bearer-json", { token: "t" }).then(() => outcomes.push("bearer ok"), (e: Error) => outcomes.push(e.message)),
    ];
    await new Promise((resolve) => setImmediate(resolve));
    abortClientRequests();
    await Promise.all(pending);
    expect(outcomes.sort()).toEqual(["aborted /cookie-json", "aborted /cookie-raw", "bearer ok"]);
  });

  it("signals access-stale and session events from refusals the same way per transport", async () => {
    const events: string[] = [];
    const target = window as unknown as { dispatchEvent?: unknown };
    const original = target.dispatchEvent;
    target.dispatchEvent = (event: Event) => events.push(event.type) > 0;
    try {
      const html403 = () => res({ status: 403, headers: { "content-type": "text/html" }, text: async () => "<html>" });
      mockFetch.mockResolvedValueOnce(html403());
      await requestJson("", "/a", {}).catch(() => undefined);
      expect(events).toEqual([]);
      mockFetch.mockResolvedValueOnce(html403());
      await requestRaw("", "/a", {}).catch(() => undefined);
      expect(events).toEqual(["digitva-access-stale"]);
      events.length = 0;
      for (const send of [requestJson, requestRaw] as const) {
        mockFetch.mockResolvedValueOnce(jsonRes(403, { code: "terms_required" }));
        await send("", "/a", {}).catch(() => undefined);
        mockFetch.mockResolvedValueOnce(jsonRes(403, { code: "forbidden" }));
        await send("", "/a", {}).catch(() => undefined);
        mockFetch.mockResolvedValueOnce(jsonRes(403, { code: "terms_required" }));
        await send("", "/api/v1/me/access", {}).catch(() => undefined);
        mockFetch.mockResolvedValueOnce(jsonRes(403, { code: "terms_required" }));
        await send(SERVER, "/a", {}).catch(() => undefined);
        mockFetch.mockResolvedValueOnce(jsonRes(403, { code: "terms_required" }));
        await send(SERVER, "/a", { token: "t" }).catch(() => undefined);
        mockFetch.mockResolvedValueOnce(jsonRes(401, { code: "session_idle" }));
        await send("", "/a", {}).catch(() => undefined);
        mockFetch.mockResolvedValueOnce(jsonRes(401, { code: "session_expired" }));
        await send("", "/a", {}).catch(() => undefined);
        mockFetch.mockResolvedValueOnce(jsonRes(401, { code: "session_idle" }));
        await send(SERVER, "/a", {}).catch(() => undefined);
      }
      expect(events).toEqual([
        "digitva-access-stale", "digitva-access-stale", "digitva-session-idle", "digitva-session-expired",
        "digitva-access-stale", "digitva-access-stale", "digitva-session-idle", "digitva-session-expired",
      ]);
    } finally {
      target.dispatchEvent = original;
    }
  });

  it("returns and then sends the newest X-CSRFToken, and attaches it to a refusal (both transports)", async () => {
    mockFetch.mockResolvedValueOnce(jsonRes(200, { a: 1 }, { "X-CSRFToken": "fresh1" }));
    await expect(requestJson("", "/p", {})).resolves.toStrictEqual({
      status: 200, body: { a: 1 }, csrf: { header: "X-CSRFToken", token: "fresh1" },
    });
    mockFetch.mockResolvedValueOnce(res({ text: async () => "{}", headers: { "content-type": "application/json", "X-CSRFToken": "fresh2" } }));
    await expect(requestRaw("", "/p", { csrf: { header: "X-CSRFToken", token: "old" } })).resolves.toMatchObject({
      csrf: { header: "X-CSRFToken", token: "fresh2" },
    });
    expect(init(1).headers["X-CSRFToken"]).toBe("fresh1");
    mockFetch.mockResolvedValueOnce(jsonRes(422, { code: "invalid" }, { "X-CSRFToken": "fresh3" }));
    await expect(requestRaw("", "/p", {})).rejects.toMatchObject({ status: 422, code: "invalid", csrf: { header: "X-CSRFToken", token: "fresh3" } });
    expect(init(2).headers["X-CSRFToken"]).toBe("fresh2");
    mockFetch.mockResolvedValueOnce(jsonRes(422, { code: "invalid" }));
    await expect(requestJson("", "/p", { token: undefined })).rejects.toMatchObject({ status: 422, code: "invalid", csrf: undefined });
    expect(init(3).headers["X-CSRFToken"]).toBe("fresh3");
  });
});
