/** Offline gate (digitva-5u65): no server call while offline, calm handling, one error-log entry per spell. */
const mockFetch = jest.fn();
(global as unknown as { fetch: unknown }).fetch = mockFetch;

import { requestJson } from "../src/api";
import { describeError, pendingErrors, recordError, resetErrorLog } from "../src/errorLog";
import { OfflineError, assertOnline, noteRequestOk, resetNetwork, startNetworkWatch } from "../src/network";
import { checkForUpdate } from "../src/updateCheck";
import { recheckPhoneClock } from "../src/phoneClock";

const expoNetwork = require("expo-network") as { getNetworkStateAsync: jest.Mock };

async function setState(state: { isConnected: boolean; isInternetReachable: boolean | null }) {
  expoNetwork.getNetworkStateAsync.mockResolvedValueOnce(state);
  startNetworkWatch();
  await new Promise((resolve) => setImmediate(resolve));
}

beforeEach(() => {
  mockFetch.mockReset();
  resetNetwork();
  resetErrorLog();
});

it("offline: API, update check and clock re-check make no request", async () => {
  await setState({ isConnected: false, isInternetReachable: false });
  await expect(requestJson("/api/v1/me/access", { token: "t" } as never)).rejects.toBeInstanceOf(OfflineError);
  expect(await checkForUpdate("https://example.test")).toEqual({ status: "unknown" });
  expect(await recheckPhoneClock("https://example.test")).toBe(false);
  expect(mockFetch).not.toHaveBeenCalled();
});

it("connected but internet unreachable is offline too", async () => {
  await setState({ isConnected: true, isInternetReachable: false });
  expect(() => assertOnline()).toThrow(OfflineError);
});

it("unknown reachability does not block calls", async () => {
  await setState({ isConnected: true, isInternetReachable: null });
  mockFetch.mockResolvedValue({
    ok: true, status: 200, redirected: false, type: "basic",
    headers: { get: (name: string) => (name.toLowerCase() === "content-type" ? "application/json" : null) },
    json: async () => ({}),
  });
  await requestJson("/api/v1/me/access", { token: "t" } as never);
  expect(mockFetch).toHaveBeenCalledTimes(1);
});

it("an offline refusal is never filed in the error log", () => {
  expect(describeError(new OfflineError())).toBe("offline");
  recordError(describeError(new OfflineError()));
  expect(pendingErrors()).toHaveLength(0);
});

it("a real network failure is filed once per spell, again after a good response", () => {
  const failure = describeError(new TypeError("Network request failed"));
  recordError(failure);
  recordError(failure);
  expect(pendingErrors()).toHaveLength(1);
  noteRequestOk();
  jest.spyOn(Date, "now").mockReturnValue(Date.now() + 120_000);
  recordError(failure);
  expect(pendingErrors()).toHaveLength(2);
});
