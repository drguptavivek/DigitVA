/** Sign-out keeps the store: it asks once, says the data stays, and lists what is not sent yet. */
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
const press = (text: string) =>
  (alert.mock.calls[0][2] as Buttons).find((button) => button.text === text)?.onPress?.();

beforeEach(() => alert.mockClear());

it("asks once, says the data stays, and lists each kind not sent yet", async () => {
  mockUnsentKinds.mockResolvedValue({ ...none, interviews: 2, revisions: 1 });
  const onConfirmed = jest.fn();
  await confirmSignOut("worker", onConfirmed);

  expect(alert).toHaveBeenCalledTimes(1);
  const list = 'unsentKindInterviews:{"count":2}\nunsentKindRevisions:{"count":1}';
  expect(alert.mock.calls[0][1]).toBe(`signOutKeepsData\n\nsignOutKeptUnsent:${JSON.stringify({ list })}`);
  expect((alert.mock.calls[0][2] as Buttons).map((button) => button.text)).toEqual(["cancel", "signOutConfirm"]);
  press("signOutConfirm");
  expect(onConfirmed).toHaveBeenCalledTimes(1);
});

it("asks once with no list when nothing is unsent or the store is locked", async () => {
  for (const kinds of [none, undefined]) {
    alert.mockClear();
    mockUnsentKinds.mockResolvedValue(kinds);
    const onConfirmed = jest.fn();
    await confirmSignOut("worker", onConfirmed);
    expect(alert).toHaveBeenCalledTimes(1);
    expect(alert.mock.calls[0][1]).toBe("signOutKeepsData");
    press("cancel");
    expect(onConfirmed).not.toHaveBeenCalled();
  }
});
