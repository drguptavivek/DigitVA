import React from "react";
import { act, create } from "react-test-renderer";

jest.mock("../src/client/session", () => ({ loadBrowserSession: jest.fn() }));
jest.mock("../src/web/interviewAssetCache", () => ({ setInterviewAssetWarmEligibility: jest.fn() }));
jest.mock("../src/preferences", () => ({
  ...jest.requireActual("../src/preferences"),
  getUiLocalePreference: async () => "en",
  setUiLocalePreference: async () => undefined,
}));
jest.mock("../src/i18n", () => ({ setUiLocale: (value: string) => value, t: (key: string) => key }));
jest.mock("../src/web/attachmentBufferSession", () => ({
  unsentWebAttachmentCount: jest.fn(),
  wipeWebAttachments: jest.fn(async () => undefined),
  wipeOtherUsersWebAttachments: jest.fn(async () => undefined),
}));

import { AppStateProvider, useAppState } from "../src/AppState.web";
import { ConfirmDialog } from "../src/ConfirmDialog";
import { loadBrowserSession } from "../src/client/session";
import { unsentWebAttachmentCount, wipeOtherUsersWebAttachments, wipeWebAttachments } from "../src/web/attachmentBufferSession";

let state: ReturnType<typeof useAppState>;
function Consumer() { state = useAppState(); return null; }
const bootstrap = {
  user: { user_id: "u1", name: "Worker" }, csrf: { header: "X-CSRFToken", token: "csrf" },
  capabilities: { intake: true, registerDeath: false, registeredDeaths: false, coding: false, reviewing: false }, links: { login: "/vaauth/valogin?next=%2Fapp%2F", logout: "/vaauth/valogout" },
  access: { user: { user_id: "u1", name: "Worker" }, is_admin: false, demo_coding: { available: false, project_ids: [] }, projects: [] }
};
const session = { authenticated: true, bootstrap };
const signedOut = { authenticated: false as const, loginUrl: "/vaauth/valogin?next=%2Fapp%2F" };
const assign = jest.fn();
const redirect = { status: 0, type: "opaqueredirect", ok: false, redirected: false, headers: { get: () => null }, text: async () => "" } as unknown as Response;

beforeEach(() => {
  jest.clearAllMocks();
  Object.defineProperty(window, "addEventListener", { configurable: true, value: jest.fn() });
  Object.defineProperty(window, "removeEventListener", { configurable: true, value: jest.fn() });
  Object.defineProperty(globalThis, "document", { configurable: true, value: {
    visibilityState: "visible", addEventListener: jest.fn(), removeEventListener: jest.fn()
  } });
  (loadBrowserSession as jest.Mock).mockResolvedValue(session);
  Object.defineProperty(window, "location", { configurable: true, value: { assign } });
});

async function mount() {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<AppStateProvider><Consumer /></AppStateProvider>); });
  return tree;
}

it("deletes what another user left in this browser when a user signs in, once per user", async () => {
  const tree = await mount();
  expect(wipeOtherUsersWebAttachments).toHaveBeenCalledWith("u1");
  await act(async () => { await state.reload(); });
  expect(wipeOtherUsersWebAttachments).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());
});

it("warns about unsent files before signing out; Cancel keeps them and the session", async () => {
  (unsentWebAttachmentCount as jest.Mock).mockResolvedValue(2);
  const fetch = jest.spyOn(globalThis, "fetch").mockResolvedValue(redirect);
  const tree = await mount();
  let done!: Promise<void>;
  await act(async () => { done = state.logout(); });
  const dialog = tree.root.findByType(ConfirmDialog);
  expect(dialog.props.message).toBe("webAttachmentsSignOutMessage");
  await act(async () => { dialog.props.onCancel(); await done; });
  expect(tree.root.findAllByType(ConfirmDialog)).toHaveLength(0);
  expect(wipeWebAttachments).not.toHaveBeenCalled();
  expect(fetch).not.toHaveBeenCalledWith("/vaauth/valogout", expect.anything());
  expect(assign).not.toHaveBeenCalled();
  fetch.mockRestore();
  await act(async () => tree.unmount());
});

it("deletes the files and signs out once the user confirms", async () => {
  (unsentWebAttachmentCount as jest.Mock).mockResolvedValue(1);
  const fetch = jest.spyOn(globalThis, "fetch").mockResolvedValue(redirect);
  const tree = await mount();
  (loadBrowserSession as jest.Mock).mockResolvedValue(signedOut);
  let done!: Promise<void>;
  await act(async () => { done = state.logout(); });
  await act(async () => { tree.root.findByType(ConfirmDialog).props.onConfirm(); await done; });
  expect(wipeWebAttachments).toHaveBeenCalledWith("u1");
  const logoutCall = fetch.mock.calls.findIndex(([url]) => url === "/vaauth/valogout");
  expect((wipeWebAttachments as jest.Mock).mock.invocationCallOrder[0]).toBeLessThan(fetch.mock.invocationCallOrder[logoutCall]);
  expect(fetch).toHaveBeenCalledWith("/vaauth/valogout", expect.objectContaining({ method: "POST" }));
  expect(assign).toHaveBeenCalledWith("/vaauth/valogin?next=%2Fapp%2F");
  fetch.mockRestore();
  await act(async () => tree.unmount());
});

it("signs out without asking when nothing is waiting, still clearing the buffer", async () => {
  (unsentWebAttachmentCount as jest.Mock).mockResolvedValue(0);
  const fetch = jest.spyOn(globalThis, "fetch").mockResolvedValue(redirect);
  const tree = await mount();
  (loadBrowserSession as jest.Mock).mockResolvedValue(signedOut);
  await act(async () => { await state.logout(); });
  expect(tree.root.findAllByType(ConfirmDialog)).toHaveLength(0);
  expect(wipeWebAttachments).toHaveBeenCalledWith("u1");
  expect(assign).toHaveBeenCalledWith("/vaauth/valogin?next=%2Fapp%2F");
  fetch.mockRestore();
  await act(async () => tree.unmount());
});
