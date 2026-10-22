/** Sign-out wipes the store: the confirmation states the unsent count and asks twice when work would be lost. */
import { Alert } from "react-native";

const mockUnsentCount = jest.fn<Promise<number | undefined>, [string]>();
jest.mock("../src/interviewerDb", () => ({ unsentWorkCount: (userId: string) => mockUnsentCount(userId) }));
jest.mock("../src/i18n", () => ({
  t: (key: string, vars?: Record<string, unknown>) => (vars ? `${key}:${JSON.stringify(vars)}` : key),
}));

import { confirmSignOut } from "../src/signOutConfirm";

type Buttons = Array<{ text: string; onPress?: () => void }>;
const alert = jest.spyOn(Alert, "alert").mockImplementation(() => undefined);
const press = (call: number, text: string) =>
  (alert.mock.calls[call][2] as Buttons).find((button) => button.text === text)?.onPress?.();

beforeEach(() => alert.mockClear());

it("states the unsent count and signs out only after a second confirmation", async () => {
  mockUnsentCount.mockResolvedValue(3);
  const onConfirmed = jest.fn();
  await confirmSignOut("worker", onConfirmed);

  expect(alert.mock.calls[0][1]).toBe('signOutUnsentCount:{"count":3}');
  press(0, "signOutConfirm");
  expect(onConfirmed).not.toHaveBeenCalled();
  expect(alert.mock.calls[1][1]).toBe('signOutUnsentFinal:{"count":3}');
  press(1, "signOutDeletePermanently");
  expect(onConfirmed).toHaveBeenCalledTimes(1);
});

it("asks twice when a locked store cannot be counted", async () => {
  mockUnsentCount.mockResolvedValue(undefined);
  const onConfirmed = jest.fn();
  await confirmSignOut("worker", onConfirmed);

  expect(alert.mock.calls[0][1]).toBe("signOutUnknownUnsent");
  press(0, "signOutConfirm");
  press(1, "signOutDeletePermanently");
  expect(onConfirmed).toHaveBeenCalledTimes(1);
});

it("asks once when nothing is unsent", async () => {
  mockUnsentCount.mockResolvedValue(0);
  const onConfirmed = jest.fn();
  await confirmSignOut("worker", onConfirmed);

  expect(alert).toHaveBeenCalledTimes(1);
  expect(alert.mock.calls[0][1]).toBe("pendingSignOutConfirm");
  press(0, "signOutConfirm");
  expect(onConfirmed).toHaveBeenCalledTimes(1);
});
