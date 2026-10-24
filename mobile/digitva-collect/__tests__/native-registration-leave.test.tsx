import React from "react";
import { act, create } from "react-test-renderer";
import { AppState } from "react-native";

let mockParams: Record<string, string> = {};
let mockBlur: (() => void) | undefined;
let mockUnlocked = true;
let mockLoad: jest.Mock;
let mockPatch: jest.Mock;
const mockRouter = { back: jest.fn(), replace: jest.fn() };
const mockAccount = { user_id: "u1", collection_access: true, registered_deaths_access: true };

const mockListeners: Array<(event: { data: { action: { type: string } }; preventDefault: () => void }) => void> = [];
const mockNavigation = {
  addListener: (_name: string, callback: (typeof mockListeners)[number]) => {
    mockListeners.push(callback);
    return () => { mockListeners.splice(mockListeners.indexOf(callback), 1); };
  },
  dispatch: jest.fn(),
};
let mockConfirmProps: Record<string, unknown> | undefined;
jest.mock("../src/ConfirmDialog", () => ({
  ConfirmDialog: (props: Record<string, unknown>) => {
    mockConfirmProps = props;
    return (jest.requireActual("react") as typeof React).createElement("section", { "data-confirm": true });
  },
}));
jest.mock("expo-router", () => ({
  useNavigation: () => mockNavigation,
  useIsFocused: () => true,
  Redirect: () => null,
  useLocalSearchParams: () => mockParams,
  useRouter: () => mockRouter,
  useFocusEffect: (callback: () => void | (() => void)) => {
    const ReactActual = jest.requireActual("react") as typeof React;
    ReactActual.useEffect(() => {
      const cleanup = callback();
      mockBlur = cleanup || undefined;
      return cleanup;
    }, [callback]);
  },
}));
jest.mock("@drguptavivek/who-2022-va/native", () => {
  const ReactActual = require("react") as typeof React;
  const control = ({ question, value, onAnswer }: { question: { name: string }; value?: unknown; onAnswer: (value: unknown) => void }) =>
    ReactActual.createElement("input", {
      "data-field": question.name,
      "data-value": value ?? "",
      onChange: (event: { target: { value: string } }) => onAnswer(event.target.value),
    });
  return { WhoVaQuestionControls: { Date: control, Integer: control, Text: control } };
}, { virtual: true });
jest.mock("@drguptavivek/who-2022-va", () => ({ resolveUiMessages: () => ({}), WHO_VA_BUILT_IN_UI_TRANSLATIONS: {} }), { virtual: true });
jest.mock("../src/AppState", () => ({ useAppState: () => ({ accounts: [mockAccount], lockVersion: 0 }) }));
jest.mock("../src/deathRegistrationApi", () => ({
  getDeathRegistrationAccess: jest.fn(async () => ({ projects: [] })),
  getNativeRegistrationCase: jest.fn(),
  getNativeRegisteredDeaths: (...args: unknown[]) => mockLoad(...args),
  patchNativeDeathRegistration: (...args: unknown[]) => mockPatch(...args),
  postNativeDeathRegistration: jest.fn(),
}));
jest.mock("../src/api", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    code: string;
    constructor(statusValue: number, codeValue: string) {
      super(codeValue);
      this.status = statusValue;
      this.code = codeValue;
    }
  },
  hasInterviewRegistrationAccess: () => false,
  intakeContextFromAccess: () => [],
}));
jest.mock("../src/interviewerDb", () => ({ isUnlocked: () => mockUnlocked, openInterviewerDb: jest.fn(async () => ({})) }));
jest.mock("../src/sync", () => ({ getCachedReferenceData: jest.fn(async () => undefined), registersDeaths: () => true, targetsFrom: () => [] }));
jest.mock("../src/platform", () => ({ platformServices: {} }));
jest.mock("../src/i18n", () => ({ t: (key: string) => key, uiLocale: () => "en" }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  const Component = ({ children }: { children?: React.ReactNode }) => ReactActual.createElement("screen", null, children);
  return {
    Button: ({ label, onPress }: { label: string; onPress: () => void }) => ReactActual.createElement("button", { label, onPress }),
    Row: Component,
    Screen: Component,
    useUiStyles: () => ({ text: {}, muted: {}, error: {}, input: {}, card: {} }),
  };
});

import Register from "../src/nativeRoutes/register";
import { ApiError } from "../src/api";

const death = {
  death_id: "d1", project_id: "P1", site_id: "S1", org_unit_id: null, status: "registered",
  updated_at: "2026-10-06T12:00:00+00:00",
  deceased: { name: "Asha", sex: "female", date_of_death: "2026-09-30", date_of_birth: "1987-04-12", age_years: 39 },
  household_address: { address: "Old address" }, informant: {},
};

beforeEach(() => {
  Object.defineProperty(AppState, "currentState", { configurable: true, value: "active" });
  mockParams = { userId: "u1", deathId: "d1", registrationSource: "mine" };
  mockBlur = undefined;
  mockUnlocked = true;
  mockListeners.length = 0;
  mockConfirmProps = undefined;
  mockNavigation.dispatch.mockClear();
  mockRouter.back.mockClear();
  mockLoad = jest.fn().mockResolvedValue({ deaths: [death], next_cursor: null });
  mockPatch = jest.fn().mockResolvedValue({ ...death, updated_at: "2026-10-06T12:05:00+00:00" });
});

const back = () => {
  const event = { data: { action: { type: "GO_BACK" } }, preventDefault: jest.fn() };
  mockListeners.forEach((listener) => listener(event));
  return event;
};
async function open() {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<Register />); });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  return tree;
}
const type = (tree: ReturnType<typeof create>) =>
  act(async () => tree.root.findAllByProps({ accessibilityLabel: "fieldAddress" })[0].props.onChangeText("My change"));

it("leaves a saved registration at once while nothing has been changed", async () => {
  const tree = await open();
  const event = back();
  expect(event.preventDefault).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
});

it("asks before discarding typed changes on back or a tab; Stay keeps them, Discard goes on", async () => {
  const tree = await open();
  await type(tree);
  let event!: ReturnType<typeof back>;
  await act(async () => { event = back(); });
  expect(event.preventDefault).toHaveBeenCalled();
  expect(mockConfirmProps).toMatchObject({ title: "discardChangesTitle", cancelLabel: "stay" });
  await act(async () => { (mockConfirmProps!.onCancel as () => void)(); });
  expect(tree.root.findAllByProps({ "data-confirm": true })).toHaveLength(0);
  expect(mockNavigation.dispatch).not.toHaveBeenCalled();
  expect(tree.root.findAllByProps({ accessibilityLabel: "fieldAddress" })[0].props.value).toBe("My change");

  await act(async () => { back(); });
  await act(async () => { (mockConfirmProps!.onConfirm as () => void)(); });
  expect(mockNavigation.dispatch).toHaveBeenCalledWith({ type: "GO_BACK" });
  await act(async () => tree.unmount());
});

it("a saved edit no longer asks", async () => {
  const tree = await open();
  await type(tree);
  await act(async () => tree.root.findByProps({ label: "save" }).props.onPress());
  await act(async () => { await Promise.resolve(); });
  expect(mockPatch).toHaveBeenCalled();
  expect(mockRouter.back).toHaveBeenCalled();
  const event = back();
  expect(event.preventDefault).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
});
