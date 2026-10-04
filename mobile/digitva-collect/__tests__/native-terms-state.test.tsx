import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

const mockSecure = new Map<string, string>();
jest.mock("expo-secure-store", () => ({
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 0,
  getItemAsync: jest.fn(async (key: string) => mockSecure.get(key) ?? null),
  setItemAsync: jest.fn(
    async (key: string, value: string) => void mockSecure.set(key, value),
  ),
  deleteItemAsync: jest.fn(async (key: string) => void mockSecure.delete(key)),
}));
const mockRouter = { replace: jest.fn() };
jest.mock("expo-router", () => ({ useRouter: () => mockRouter }));
jest.mock("expo-localization", () => ({
  getLocales: () => [{ languageCode: "en" }],
}));
jest.mock("../src/interviewerDb", () => ({
  anyUnlocked: () => false,
  lockAll: jest.fn(),
  deleteInterviewerDb: jest.fn(),
}));
jest.mock("../src/autoLock", () => ({
  createAutoLock: () => ({
    activity: jest.fn(),
    appStateChanged: jest.fn(),
    stop: jest.fn(),
  }),
}));
jest.mock("../src/i18n", () => ({ setUiLocale: () => "en" }));
import { AppStateProvider, useAppState } from "../src/AppState";
import { acceptDeviceTerms, authedRequest } from "../src/auth";

function Probe() {
  const state = useAppState();
  return (
    <React.Fragment>
      {JSON.stringify({
        ready: state.ready,
        terms: state.accounts[0]?.terms_required === true,
      })}
    </React.Fragment>
  );
}

it("updates mounted native state immediately when a bearer response requires terms", async () => {
  mockSecure.set(
    "device",
    JSON.stringify({
      device_id: "d",
      server: "https://example.test",
      project_id: "p",
      project_name: "P",
    }),
  );
  mockSecure.set(
    "accounts",
    JSON.stringify([{ user_id: "worker", name: "Worker" }]),
  );
  mockSecure.set(
    "tokens.worker",
    JSON.stringify({ access_token: "a", refresh_token: "r" }),
  );
  globalThis.fetch = jest.fn(async (url: RequestInfo | URL) => {
    const accepted = String(url).endsWith("/terms");
    return {
      ok: accepted,
      status: accepted ? 200 : 403,
      headers: { get: () => "application/json" },
      json: async () => (accepted ? {} : { code: "terms_required" }),
      text: async () =>
        JSON.stringify(accepted ? {} : { code: "terms_required" }),
    } as unknown as Response;
  });
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(
      <AppStateProvider>
        <Probe />
      </AppStateProvider>,
    );
  });
  expect(tree.toJSON()).toBe(JSON.stringify({ ready: true, terms: false }));
  await act(async () => {
    await expect(
      authedRequest("worker", "/api/v1/intake/cases"),
    ).rejects.toMatchObject({ code: "terms_required" });
  });
  expect(tree.toJSON()).toBe(JSON.stringify({ ready: true, terms: true }));
  await act(async () => {
    await acceptDeviceTerms("worker");
  });
  expect(tree.toJSON()).toBe(JSON.stringify({ ready: true, terms: false }));
  await act(async () => {
    tree.unmount();
  });
});
