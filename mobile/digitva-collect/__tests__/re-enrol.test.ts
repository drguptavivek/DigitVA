/** Re-enrolling signs every interviewer out: refused while a signed-in one has or may have unsent work, and the device record goes last. */
import { Alert } from "react-native";

const mockUnsentCount = jest.fn<Promise<number | undefined>, [string]>();
const mockCalls: string[] = [];
jest.mock("../src/interviewerDb", () => ({ unsentWorkCount: (userId: string) => mockUnsentCount(userId) }));
jest.mock("../src/auth", () => ({
  signOut: async (userId: string) => void mockCalls.push(`signOut:${userId}`),
  forgetDevice: async () => void mockCalls.push("forgetDevice"),
}));
jest.mock("../src/i18n", () => ({
  t: (key: string, vars?: Record<string, unknown>) => (vars ? `${key}:${JSON.stringify(vars)}` : key),
}));

import { confirmReEnrol, reEnrolDevice } from "../src/reEnrolConfirm";

type Buttons = Array<{ text: string; onPress?: () => void }>;
const alert = jest.spyOn(Alert, "alert").mockImplementation(() => undefined);
const accounts = [
  { user_id: "a", name: "Asha" },
  { user_id: "b", name: "Bina" },
];
const counts = (byUser: Record<string, number | undefined>) =>
  mockUnsentCount.mockImplementation(async (userId) => byUser[userId]);

beforeEach(() => {
  alert.mockClear();
  mockCalls.length = 0;
});

it("refuses while an interviewer has unsent work or a locked store, naming each", async () => {
  counts({ a: 2, b: undefined });
  const onConfirmed = jest.fn();
  await confirmReEnrol(accounts, onConfirmed);

  expect(alert).toHaveBeenCalledTimes(1);
  const [, message, buttons] = alert.mock.calls[0];
  expect(message).toContain("reEnrolBlocked");
  expect(message).toContain('reEnrolUnsentName:{"name":"Asha","count":2}');
  expect(message).toContain('reEnrolLockedName:{"name":"Bina"}');
  expect((buttons as Buttons).map((button) => button.text)).toEqual(["reEnrolClose"]);
  expect(onConfirmed).not.toHaveBeenCalled();
  const lock = jest.fn(async () => true);
  await expect(reEnrolDevice(accounts, lock)).rejects.toThrow("unsent_work");
  // Counted while the stores were open: nothing locked, nobody signed out.
  expect(lock).not.toHaveBeenCalled();
  expect(mockCalls).toEqual([]);
});

it("asks once when nothing is unsent, then signs everyone out before forgetting the device", async () => {
  counts({ a: 0, b: 0 });
  const onConfirmed = jest.fn();
  await confirmReEnrol(accounts, onConfirmed);

  expect(alert.mock.calls[0][1]).toBe("reEnrolConfirm");
  (alert.mock.calls[0][2] as Buttons).find((button) => button.text === "reEnrol")?.onPress?.();
  expect(onConfirmed).toHaveBeenCalledTimes(1);
  await reEnrolDevice(accounts, async () => (mockCalls.push("lock"), true));
  expect(mockCalls).toEqual(["lock", "signOut:a", "signOut:b", "forgetDevice"]);
});

it("re-enrols a phone with no interviewers", async () => {
  await confirmReEnrol([], jest.fn());
  expect(alert.mock.calls[0][1]).toBe("reEnrolConfirm");
  await reEnrolDevice([], async () => true);
  expect(mockCalls).toEqual(["forgetDevice"]);
});

it("stops before signing anyone out when the stores cannot be locked", async () => {
  counts({ a: 0, b: 0 });
  await expect(reEnrolDevice(accounts, async () => false)).rejects.toThrow("lock_failed");
  expect(mockCalls).toEqual([]);
});

describe("signed-out profiles (owner decision 2026-10-27: warn, then allow)", () => {
  const withSignedOut = [
    { user_id: "a", name: "Asha" },
    { user_id: "s", name: "Sita", signed_out: true, needs_sign_in: true },
  ];

  it("names a signed-out locked profile in the confirmation instead of refusing", async () => {
    counts({ a: 0, s: undefined });
    const onConfirmed = jest.fn();
    await confirmReEnrol(withSignedOut, onConfirmed);

    expect(alert).toHaveBeenCalledTimes(1);
    const [, message, buttons] = alert.mock.calls[0];
    expect(message).toContain("reEnrolConfirm");
    expect(message).toContain('reEnrolKeptSignedOut:{"list":"Sita"}');
    expect(message).not.toContain("reEnrolBlocked");
    (buttons as Buttons).find((button) => button.text === "reEnrol")?.onPress?.();
    expect(onConfirmed).toHaveBeenCalledTimes(1);

    await reEnrolDevice(withSignedOut, async () => (mockCalls.push("lock"), true));
    expect(mockCalls).toEqual(["lock", "signOut:a", "signOut:s", "forgetDevice"]);
  });

  it("still refuses for a signed-in profile with unsent work or a locked store beside a signed-out one", async () => {
    for (const a of [3, undefined]) {
      alert.mockClear();
      mockCalls.length = 0;
      counts({ a, s: undefined });
      await confirmReEnrol(withSignedOut, jest.fn());
      const message = alert.mock.calls[0][1] as string;
      expect(message).toContain("reEnrolBlocked");
      expect(message).toContain(a === undefined ? 'reEnrolLockedName:{"name":"Asha"}' : 'reEnrolUnsentName:{"name":"Asha","count":3}');
      expect(message).not.toContain("Sita");
      await expect(reEnrolDevice(withSignedOut, async () => true)).rejects.toThrow("unsent_work");
      expect(mockCalls).toEqual([]);
    }
  });

  it("shows the plain confirmation when no profile is signed out", async () => {
    counts({ a: 0, b: 0 });
    await confirmReEnrol(accounts, jest.fn());
    expect(alert.mock.calls[0][1]).toBe("reEnrolConfirm");
  });
});
