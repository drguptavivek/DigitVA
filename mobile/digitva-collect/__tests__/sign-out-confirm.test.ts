/** Sign-out wipes the store: it is refused while work is unsent, and a locked store warns twice. */
import { Alert } from "react-native";

type Kinds = { interviews: number; registrations: number; actions: number; revisions: number };
const none: Kinds = { interviews: 0, registrations: 0, actions: 0, revisions: 0 };
const mockUnsentKinds = jest.fn<Promise<Kinds | undefined>, [string]>();
jest.mock("../src/interviewerDb", () => ({ unsentWorkKinds: (userId: string) => mockUnsentKinds(userId) }));
jest.mock("../src/i18n", () => ({
  t: (key: string, vars?: Record<string, unknown>) => (vars ? `${key}:${JSON.stringify(vars)}` : key),
}));

import { confirmSignOut } from "../src/signOutConfirm";

type Buttons = Array<{ text: string; onPress?: () => void }>;
const alert = jest.spyOn(Alert, "alert").mockImplementation(() => undefined);
const press = (call: number, text: string) =>
  (alert.mock.calls[call][2] as Buttons).find((button) => button.text === text)?.onPress?.();

beforeEach(() => alert.mockClear());

it("refuses sign-out while work is unsent and names each kind", async () => {
  mockUnsentKinds.mockResolvedValue({ ...none, interviews: 2, revisions: 1 });
  const onConfirmed = jest.fn();
  await confirmSignOut("worker", onConfirmed);

  expect(alert).toHaveBeenCalledTimes(1);
  expect(alert.mock.calls[0][0]).toBe("signOutBlockedTitle");
  const list = 'unsentKindInterviews:{"count":2}\nunsentKindRevisions:{"count":1}';
  expect(alert.mock.calls[0][1]).toBe(`signOutBlockedUnsent:${JSON.stringify({ list })}`);
  const buttons = alert.mock.calls[0][2] as Buttons;
  expect(buttons.map((button) => button.text)).toEqual(["ok"]);
  buttons[0].onPress?.();
  expect(onConfirmed).not.toHaveBeenCalled();
});

it("asks twice when a locked store cannot be counted", async () => {
  mockUnsentKinds.mockResolvedValue(undefined);
  const onConfirmed = jest.fn();
  await confirmSignOut("worker", onConfirmed);

  expect(alert.mock.calls[0][1]).toBe("signOutUnknownUnsent");
  press(0, "signOutConfirm");
  press(1, "signOutDeletePermanently");
  expect(onConfirmed).toHaveBeenCalledTimes(1);
});

it("asks once when nothing is unsent", async () => {
  mockUnsentKinds.mockResolvedValue(none);
  const onConfirmed = jest.fn();
  await confirmSignOut("worker", onConfirmed);

  expect(alert).toHaveBeenCalledTimes(1);
  expect(alert.mock.calls[0][1]).toBe("pendingSignOutConfirm");
  press(0, "signOutConfirm");
  expect(onConfirmed).toHaveBeenCalledTimes(1);
});
