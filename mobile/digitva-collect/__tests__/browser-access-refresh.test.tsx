import React from "react";
import { act, create } from "react-test-renderer";

jest.mock("../src/client/session", () => ({ loadBrowserSession: jest.fn() }));
jest.mock("../src/preferences", () => ({ getUiLocalePreference: async () => "en", setUiLocalePreference: async () => undefined }));
jest.mock("../src/i18n", () => ({ setUiLocale: (value: string) => value }));

import { AppStateProvider, useAppState } from "../src/AppState.web";
import { loadBrowserSession } from "../src/client/session";
import { ApiError } from "../src/api";

let state: ReturnType<typeof useAppState>;
function Consumer() { state = useAppState(); return null; }
const bootstrap = {
  user: { user_id: "u1", name: "Worker" }, csrf: { header: "X-CSRFToken", token: "csrf" },
  capabilities: { intake: true, coding: false, reviewing: false }, links: { login: "/vaauth/valogin?next=%2Fapp%2F", logout: "/vaauth/valogout" },
  access: { user: { user_id: "u1", name: "Worker" }, is_admin: false, demo_coding: { available: false, project_ids: [] }, projects: [] }
};
const session = { authenticated: true, bootstrap };
let handlers: Record<string, () => void>;

beforeEach(() => {
  jest.clearAllMocks();
  handlers = {};
  const add = jest.fn((type: string, listener: () => void) => { handlers[type] = listener; });
  Object.defineProperty(window, "addEventListener", { configurable: true, value: add });
  Object.defineProperty(window, "removeEventListener", { configurable: true, value: jest.fn() });
  Object.defineProperty(globalThis, "document", { configurable: true, value: {
    visibilityState: "visible", addEventListener: add, removeEventListener: jest.fn()
  } });
  (loadBrowserSession as jest.Mock).mockResolvedValue(session);
});

it("refreshes access after refusal and app resume, coalescing concurrent events", async () => {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<AppStateProvider><Consumer /></AppStateProvider>); });
  expect(loadBrowserSession).toHaveBeenCalledTimes(1);
  let resolve!: (value: typeof session) => void;
  (loadBrowserSession as jest.Mock).mockImplementation(() => new Promise((done) => { resolve = done; }));
  await act(async () => { handlers["digitva-access-stale"](); handlers.visibilitychange(); handlers.pageshow(); });
  expect(loadBrowserSession).toHaveBeenCalledTimes(2);
  const changed = { authenticated: true, bootstrap: { ...bootstrap, capabilities: { ...bootstrap.capabilities, intake: false } } };
  await act(async () => { resolve(changed); });
  expect(state.bootstrap?.capabilities.intake).toBe(false);
  await act(async () => tree.unmount());
});

it("clears browser identity when access itself is refused", async () => {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<AppStateProvider><Consumer /></AppStateProvider>); });
  expect(state.authenticated).toBe(true);
  (loadBrowserSession as jest.Mock).mockRejectedValue(new ApiError(403, "terms_required"));
  await act(async () => { handlers["digitva-access-stale"](); });
  expect(state.authenticated).toBe(false);
  expect(state.bootstrap).toBeUndefined();
  await act(async () => tree.unmount());
});

it("removes cached browser definitions when interviewer actions disappear", async () => {
  const project = (projectId: string, interview: boolean) => ({
    project_id: projectId,
    grants: [{ role: "interviewer", active: true, source: "assigned" }],
    actions: { interview: interview ? [{ site_id: "S1" }] : [] }
  });
  const initial = {
    ...bootstrap,
    access: { ...bootstrap.access, projects: [project("P1", true), project("P2", true)] }
  };
  const next = {
    ...bootstrap,
    access: {
      ...bootstrap.access,
      projects: [project("P1", true), { ...project("P2", false), grants: [{ role: "interviewer", active: false, source: "assigned" }] }]
    }
  };
  (loadBrowserSession as jest.Mock).mockResolvedValueOnce({ authenticated: true, bootstrap: initial });
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<AppStateProvider><Consumer /></AppStateProvider>); });
  const removeProject = jest.spyOn(state.definitionCache!, "removeProject");
  (loadBrowserSession as jest.Mock).mockResolvedValue({ authenticated: true, bootstrap: next });

  await act(async () => { handlers["digitva-access-stale"](); });

  expect(removeProject).toHaveBeenCalledWith("P2");
  expect(state.bootstrap?.access.projects.map(({ project_id }) => project_id)).toEqual(["P1", "P2"]);
  await act(async () => tree.unmount());
});

it("signs out using the browser route with the current cookie CSRF token", async () => {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<AppStateProvider><Consumer /></AppStateProvider>); });
  const fetch = jest.spyOn(globalThis, "fetch").mockResolvedValue({
    status: 0, type: "opaqueredirect", ok: false, redirected: false,
    headers: { get: () => null }, text: async () => ""
  } as unknown as Response);
  await act(async () => { await state.logout(); });
  expect(fetch).toHaveBeenCalledWith("/vaauth/valogout", expect.objectContaining({
    method: "POST", credentials: "include", redirect: "manual",
    headers: expect.objectContaining({ "X-CSRFToken": "csrf" })
  }));
  expect(loadBrowserSession).toHaveBeenCalledTimes(2);
  fetch.mockRestore();
  await act(async () => tree.unmount());
});
