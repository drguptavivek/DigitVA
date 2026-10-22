import React from "react";
import { act, create } from "react-test-renderer";

jest.mock("../src/client/session", () => ({ loadBrowserSession: jest.fn() }));
jest.mock("../src/preferences", () => ({
  ...jest.requireActual("../src/preferences"),
  getUiLocalePreference: async () => "en", setUiLocalePreference: async () => undefined,
}));

import { AppStateProvider, useAppState } from "../src/AppState.web";
import { loadBrowserSession } from "../src/client/session";
import { requestClientJson, requestJson } from "../src/api";
import { browserErrorText } from "../src/web/common";
import en from "../src/strings/en.json";

const stale = { header: "X-CSRFToken", token: "stale" };

function response(body: unknown, status = 200, csrfToken?: string): Response {
  return {
    status, ok: status >= 200 && status < 300, redirected: false,
    headers: { get: (name: string) => name.toLowerCase() === "content-type" ? "application/json"
      : name.toLowerCase() === "x-csrftoken" ? csrfToken ?? null : null },
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

const sentToken = (fetchMock: jest.SpyInstance, call: number) =>
  (fetchMock.mock.calls[call][1]?.headers as Record<string, string>)["X-CSRFToken"];

afterEach(() => jest.restoreAllMocks());

describe("CSRF token freshness", () => {
  it("sends the token from the newest response, not the caller's snapshot", async () => {
    const fetchMock = jest.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response({ ok: true }, 200, "fresh"))
      .mockResolvedValueOnce(response({ saved: true }));
    await requestClientJson("/api/v1/me/access", { csrf: stale });
    await requestClientJson("/api/v1/intake/drafts/d1", { method: "PATCH", json: {}, csrf: stale });
    expect(sentToken(fetchMock, 1)).toBe("fresh");
  });

  it("refreshes the token once on csrf_failed and retries the write", async () => {
    const fetchMock = jest.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response({ error: "The CSRF token has expired.", code: "csrf_failed" }, 400))
      .mockResolvedValueOnce(response({ user: {} }, 200, "renewed"))
      .mockResolvedValueOnce(response({ saved: true }));
    await expect(requestClientJson("/api/v1/intake/deaths", { method: "POST", json: { a: 1 }, csrf: stale }))
      .resolves.toEqual({ saved: true });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/me/access");
    expect(fetchMock.mock.calls[2][1]?.body).toBe(JSON.stringify({ a: 1 }));
    expect(sentToken(fetchMock, 2)).toBe("renewed");
  });

  it("fails with the token-refreshed message when the retry is refused again", async () => {
    const refusal = () => response({ error: "The CSRF token is invalid.", code: "csrf_failed" }, 400);
    const fetchMock = jest.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(refusal())
      .mockResolvedValueOnce(response({ user: {} }, 200, "renewed"))
      .mockResolvedValueOnce(refusal());
    const error = await requestClientJson("/api/v1/intake/deaths", { method: "POST", json: {} }).catch((caught: unknown) => caught);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(error).toMatchObject({ status: 400, code: "csrf_failed" });
    expect(browserErrorText(error)).toBe(en.csrfRefreshed);
    expect(browserErrorText(error)).not.toBe(en.serverValidation);
  });

  it("does not retry a bearer request refused for CSRF", async () => {
    const fetchMock = jest.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response({ code: "csrf_failed" }, 400));
    await expect(requestJson("https://digitva.test", "/api/v1/x", { method: "POST", token: "t" }))
      .rejects.toMatchObject({ code: "csrf_failed" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("access-stale signal", () => {
  let dispatch: jest.Mock;
  const previousWindow = globalThis.window;
  beforeEach(() => {
    dispatch = jest.fn();
    Object.defineProperty(globalThis, "window", { configurable: true, value: { dispatchEvent: dispatch } });
  });
  afterEach(() => Object.defineProperty(globalThis, "window", { configurable: true, value: previousWindow }));

  it.each(["forbidden", "no_allocation", "allocation_exists"])("ignores the business refusal %s", async (code) => {
    jest.spyOn(globalThis, "fetch").mockResolvedValueOnce(response({ code }, 403));
    await expect(requestClientJson("/api/v1/intake/deaths/d1", { method: "PATCH", json: {} })).rejects.toMatchObject({ code });
    expect(dispatch).not.toHaveBeenCalled();
  });

  it.each(["project_forbidden", "terms_required"])("signals %s, which means access changed", async (code) => {
    jest.spyOn(globalThis, "fetch").mockResolvedValueOnce(response({ code }, 403));
    await expect(requestClientJson("/api/v1/intake/projects/P1/form-options")).rejects.toMatchObject({ code });
    expect(dispatch).toHaveBeenCalledTimes(1);
  });
});

describe("bootstrap identity across access re-reads", () => {
  let state: ReturnType<typeof useAppState>;
  function Consumer() { state = useAppState(); return null; }
  const bootstrap = (token: string) => ({
    user: { user_id: "u1", name: "Worker" }, csrf: { header: "X-CSRFToken", token },
    capabilities: { intake: true, registerDeath: true, registeredDeaths: false, coding: false, reviewing: false },
    links: { login: "/vaauth/valogin?next=%2Fapp%2F", logout: "/vaauth/valogout", intakeCases: "/c", intakeDrafts: "/d" },
    access: { user: { user_id: "u1", name: "Worker" }, is_admin: false, roles: [], demo_coding: { available: false, project_ids: [] }, projects: [] },
  });
  let handlers: Record<string, Array<() => void>>;
  const fire = (type: string) => handlers[type].forEach((listener) => listener());

  beforeEach(() => {
    handlers = {};
    const add = jest.fn((type: string, listener: () => void) => { (handlers[type] ??= []).push(listener); });
    Object.defineProperty(window, "addEventListener", { configurable: true, value: add });
    Object.defineProperty(window, "removeEventListener", { configurable: true, value: jest.fn() });
    Object.defineProperty(globalThis, "document", { configurable: true, value: {
      visibilityState: "visible", addEventListener: add, removeEventListener: jest.fn(),
    } });
  });

  it("keeps the same bootstrap object on a tab resume that changed only the token", async () => {
    (loadBrowserSession as jest.Mock).mockResolvedValue({ authenticated: true, bootstrap: bootstrap("one") });
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<AppStateProvider><Consumer /></AppStateProvider>); });
    const first = state.bootstrap;
    expect(first).toBeDefined();
    (loadBrowserSession as jest.Mock).mockResolvedValue({ authenticated: true, bootstrap: bootstrap("two") });
    await act(async () => { fire("visibilitychange"); });
    expect(loadBrowserSession).toHaveBeenCalledTimes(2);
    expect(state.bootstrap).toBe(first);
    const changed = { ...bootstrap("three"), capabilities: { ...bootstrap("three").capabilities, intake: false } };
    (loadBrowserSession as jest.Mock).mockResolvedValue({ authenticated: true, bootstrap: changed });
    await act(async () => { fire("visibilitychange"); });
    expect(state.bootstrap).not.toBe(first);
    expect(state.bootstrap?.capabilities.intake).toBe(false);
    await act(async () => tree.unmount());
  });
});
