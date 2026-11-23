import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

const mockBack = jest.fn();
const mockGet = jest.fn();
const mockPatch = jest.fn();
const mockOpenDb = jest.fn();

jest.mock("expo-router", () => ({
  Redirect: () => null,
  useLocalSearchParams: () => ({ userId: "sup", deathId: "D1", by: "supervisor" }),
  useRouter: () => ({ back: mockBack }),
}));
jest.mock("../src/AppState", () => ({ useAppState: () => ({ accounts: [] }) }));
jest.mock("../src/ui", () => {
  const { createElement } = require("react");
  const group = (name: string) => ({ children }: { children?: React.ReactNode }) => createElement(name, null, children);
  return {
    Button: ({ label, onPress, disabled }: { label: string; onPress: () => void; disabled?: boolean }) => createElement("button", { "data-label": label, disabled, onClick: onPress }),
    Card: group("card"), Row: group("row"), Screen: ({ children, footer }: { children: React.ReactNode; footer?: React.ReactNode }) => createElement("screen", null, children, footer),
    Notice: ({ children }: { children: React.ReactNode }) => createElement("notice", null, children),
    FieldLabel: () => null, FieldHint: () => null, SectionLabel: () => null, Separator: () => null, TextLink: () => null,
    SegmentedControl: () => null, ChoiceRow: () => null, announce: () => undefined,
    errorText: () => "generic error",
    useUiStyles: () => ({ error: {}, muted: {}, text: {} }),
  };
});
jest.mock("../src/interviewerDb", () => ({ isUnlocked: () => true, openInterviewerDb: (...args: unknown[]) => mockOpenDb(...args) }));
jest.mock("../src/platform", () => ({ platformServices: {} }));
jest.mock("../src/sync", () => ({ getCachedReferenceData: jest.fn(), registersDeaths: () => true, targetsFrom: () => [] }));
jest.mock("../src/whoWebTheme", () => ({ useWhoFormTheme: () => ({}) }));
jest.mock("../src/MultilineInput", () => ({ MultilineInput: () => null }));
jest.mock("../src/deathRegistrationApi", () => ({
  getNativeRegistrationCase: (...args: unknown[]) => mockGet(...args),
  patchNativeDeathRegistration: (...args: unknown[]) => mockPatch(...args),
}));
jest.mock("../src/i18n", () => ({ ...require("../test-support/i18nMockExtras").i18nMockExtras, t: (key: string) => key, uiLocale: () => "en" }));
jest.mock("@drguptavivek/who-2022-va/native", () => {
  const { createElement } = require("react");
  // One stand-in per control: its field name and the answer callback, so a test types by name.
  const control = ({ question, value, onAnswer }: { question: { name: string }; value?: unknown; onAnswer: (v: unknown) => void }) =>
    createElement("field", { "data-name": question.name, "data-value": value, onAnswer });
  return { WhoVaQuestionControls: { Date: control, Integer: control, Text: control } };
}, { virtual: true });
jest.mock("@drguptavivek/who-2022-va", () => ({
  FormThemeContext: require("react").createContext({}),
  resolveUiMessages: () => ({}),
  ENGLISH_UI_MESSAGE_TEMPLATES: {},
  WHO_VA_BUILT_IN_UI_TRANSLATIONS: {},
}), { virtual: true });

import SupervisorDeathEdit from "../src/nativeRoutes/supervisorDeathEdit";
import { ApiError } from "../src/api";

const serverCase = {
  death_id: "D1", project_id: "P1", site_id: "S1", state: "registered", updated_at: "2026-10-01T10:00:00Z",
  deceased: { name: "Asha", sex: "female", date_of_death: "2026-09-01", date_of_birth: "1980-01-01", age_years: 46 },
  household_address: { address: "Old road" }, informant: { name: "Ravi", phone: "9999999999" }, remarks: null, links: {},
};

async function render(): Promise<ReactTestRenderer> {
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(<SupervisorDeathEdit />); });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  return tree;
}
const field = (tree: ReactTestRenderer, name: string) => tree.root.findAll((node) => (node.type as string) === "field" && node.props["data-name"] === name)[0];
const type = (tree: ReactTestRenderer, name: string, value: string) => act(() => { field(tree, name).props.onAnswer(value); });
const save = async (tree: ReactTestRenderer) => {
  await act(async () => { tree.root.findAll((node) => node.type === "button" && node.props["data-label"] === "save")[0].props.onClick(); });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
};

beforeEach(() => { jest.clearAllMocks(); mockGet.mockResolvedValue(serverCase); mockPatch.mockResolvedValue(serverCase); });

describe("supervisor death-report correction", () => {
  it("loads the case online, without an interviewer database or reference data", async () => {
    const tree = await render();
    expect(mockGet).toHaveBeenCalledWith("sup", "D1");
    expect(field(tree, "deceased_name").props["data-value"]).toBe("Asha");
    expect(mockOpenDb).not.toHaveBeenCalled();
  });

  it("sends only the changed fields with the loaded version, then returns to supervision", async () => {
    const tree = await render();
    type(tree, "deceased_name", "Asha Devi");
    await save(tree);
    expect(mockPatch).toHaveBeenCalledWith("sup", "D1", { deceased_name: "Asha Devi" }, "2026-10-01T10:00:00Z");
    expect(mockBack).toHaveBeenCalled();
  });

  it("sends nothing when nothing changed", async () => {
    const tree = await render();
    await save(tree);
    expect(mockPatch).not.toHaveBeenCalled();
    expect(mockBack).toHaveBeenCalled();
  });

  it("keeps the screen and says what is wrong when a required field is cleared", async () => {
    const tree = await render();
    type(tree, "deceased_name", "");
    await save(tree);
    expect(mockPatch).not.toHaveBeenCalled();
    expect(mockBack).not.toHaveBeenCalled();
    expect(JSON.stringify(tree.toJSON())).toContain("registerFixErrors");
  });

  it("reloads the latest report when it changed meanwhile", async () => {
    mockPatch.mockRejectedValue(new ApiError(409, "death_stale"));
    const tree = await render();
    type(tree, "deceased_name", "Asha Devi");
    await save(tree);
    expect(mockGet).toHaveBeenCalledTimes(2);
    expect(JSON.stringify(tree.toJSON())).toContain("supervisionDeathChanged");
    expect(field(tree, "deceased_name").props["data-value"]).toBe("Asha");
  });

  it("locks the form when the server says the report can no longer be edited", async () => {
    mockPatch.mockRejectedValue(new ApiError(409, "case_completed"));
    const tree = await render();
    type(tree, "deceased_name", "Asha Devi");
    await save(tree);
    expect(JSON.stringify(tree.toJSON())).toContain("supervisionDeathNotEditable");
    expect(tree.root.findAll((node) => node.type === "button" && node.props["data-label"] === "save")).toHaveLength(0);
  });

  it("says so when the case cannot be loaded", async () => {
    mockGet.mockRejectedValue(new Error("offline"));
    expect(JSON.stringify((await render()).toJSON())).toContain("supervisionDeathLoadFailed");
  });
});
