import { Platform } from "react-native";
import { act, create } from "react-test-renderer";

const mockChoice = jest.fn();
const mockSet = jest.fn(async (_on: boolean) => undefined);
jest.mock("../src/performanceTelemetry", () => ({
  getPerformanceTelemetryChoice: () => mockChoice(),
  setPerformanceTelemetryEnabled: (on: boolean) => mockSet(on),
}));

import { TelemetryPrompt } from "../src/TelemetryPrompt";
import { t } from "../src/i18n";

const original = Object.getOwnPropertyDescriptor(Platform, "OS");
afterEach(() => {
  if (original) Object.defineProperty(Platform, "OS", original);
  jest.clearAllMocks();
});

async function render(os: string, choice: string) {
  Object.defineProperty(Platform, "OS", { value: os, configurable: true });
  mockChoice.mockResolvedValue(choice);
  let tree!: ReturnType<typeof create>;
  await act(async () => {
    tree = create(<TelemetryPrompt />);
  });
  return tree;
}
const press = (tree: ReturnType<typeof create>, label: string) =>
  tree.root.findAll((n) => n.props.accessibilityRole === "button" && n.props.accessibilityLabel === label)[0];

test("asks on native while unasked, and Turn on stores yes", async () => {
  const tree = await render("android", "unasked");
  expect(JSON.stringify(tree.toJSON())).toContain(t("telemetryPromptTitle"));
  await act(async () => press(tree, t("telemetryPromptOn")).props.onPress());
  expect(mockSet).toHaveBeenCalledWith(true);
  expect(tree.toJSON()).toBeNull();
});

test("Not now stores off and closes", async () => {
  const tree = await render("ios", "unasked");
  await act(async () => press(tree, t("telemetryPromptOff")).props.onPress());
  expect(mockSet).toHaveBeenCalledWith(false);
  expect(tree.toJSON()).toBeNull();
});

test.each(["on", "off"])("does not ask when the choice is %s", async (choice) => {
  const tree = await render("android", choice);
  expect(tree.toJSON()).toBeNull();
});

test("never asks on web", async () => {
  const tree = await render("web", "unasked");
  expect(tree.toJSON()).toBeNull();
  expect(mockChoice).not.toHaveBeenCalled();
});
