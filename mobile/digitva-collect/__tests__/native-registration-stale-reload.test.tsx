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

jest.mock("expo-router", () => ({
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
  mockRouter.back.mockClear();
  mockRouter.replace.mockClear();
  mockLoad = jest.fn().mockResolvedValue({ deaths: [death], next_cursor: null });
  mockPatch = jest.fn().mockRejectedValue(new ApiError(409, "death_stale"));
});

it("does not restore a delayed stale reload after the registration screen loses focus", async () => {
  let resolveReload!: (page: { deaths: [typeof death]; next_cursor: null }) => void;
  mockLoad.mockReturnValueOnce(Promise.resolve({ deaths: [death], next_cursor: null }))
    .mockReturnValueOnce(new Promise((resolve) => { resolveReload = resolve; }));
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<Register />); });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  await act(async () => {
    tree.root.findByProps({ "data-field": "address" }).props.onChange({ target: { value: "My change" } });
  });
  await act(async () => tree.root.findByProps({ label: "save" }).props.onPress());
  await act(async () => { await Promise.resolve(); });
  expect(mockLoad).toHaveBeenCalledTimes(2);

  await act(async () => mockBlur?.());
  await act(async () => {
    resolveReload({ deaths: [{ ...death, household_address: { address: "Fresh address" } }], next_cursor: null });
    await Promise.resolve();
  });
  expect(tree.root.findByProps({ "data-field": "address" }).props["data-value"]).toBe("");
  expect(JSON.stringify(tree.toJSON())).not.toContain("Fresh address");
  await act(async () => tree.unmount());
});

it("clears a saved DOB with a changed-only patch when age remains", async () => {
  mockPatch.mockResolvedValue({ ...death, updated_at: "2026-10-06T12:05:00+00:00" });
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<Register />); });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  expect(tree.root.findAllByProps({ "data-field": "date_of_birth" })).toHaveLength(1);
  await act(async () => tree.root.findByProps({ label: "dobUnknown" }).props.onPress());
  expect(tree.root.findAllByProps({ "data-field": "date_of_birth" })).toHaveLength(0);
  await act(async () => tree.root.findByProps({ label: "save" }).props.onPress());
  expect(mockPatch).toHaveBeenCalledWith("u1", "d1", { date_of_birth: "" }, "2026-10-06T12:00:00+00:00");
  await act(async () => tree.unmount());
});
