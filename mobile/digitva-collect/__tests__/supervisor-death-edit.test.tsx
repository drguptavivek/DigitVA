import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

const mockBack = jest.fn();
const mockGet = jest.fn();
const mockPatch = jest.fn();
const mockOpenDb = jest.fn();
const mockCachedTypes = jest.fn();
const mockRefreshTypes = jest.fn();
const mockCachedConsent = jest.fn();
const mockRefreshConsent = jest.fn();
// The account database stand-in: every call that could write a case value lands on one of these.
const db = { runAsync: jest.fn(), execAsync: jest.fn(), getFirstAsync: jest.fn(), getAllAsync: jest.fn(), withTransactionAsync: jest.fn() };

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
jest.mock("../src/sync", () => ({
  getCachedReferenceData: jest.fn(), registersDeaths: () => true, targetsFrom: () => [],
  getCachedIdentifierTypes: (...args: unknown[]) => mockCachedTypes(...args),
  refreshIdentifierTypes: (...args: unknown[]) => mockRefreshTypes(...args),
}));
jest.mock("../src/consentStore", () => ({
  ...jest.requireActual("../src/consentStore"),
  getConsentConfig: (...args: unknown[]) => mockCachedConsent(...args),
  refreshConsentConfig: (...args: unknown[]) => mockRefreshConsent(...args),
  registrationConsentGate: (config: unknown) => ({ state: "ask", config }),
}));
// Stand-ins that expose their props, so a test drives them by name.
jest.mock("../src/PhoneInput", () => ({ PhoneNumbers: (props: object) => require("react").createElement("phones", props) }));
jest.mock("../src/IdentifierFields", () => ({
  ...jest.requireActual("../src/IdentifierFields"),
  IdentifierFields: (props: object) => require("react").createElement("ids", props),
}));
jest.mock("../src/NativeLocationCapture", () => ({ NativeLocationCapture: (props: object) => require("react").createElement("loc", props) }));
jest.mock("../src/web/StationConsentPanel", () => ({ RespondentConsentPanel: (props: object) => require("react").createElement("consent", props) }));
jest.mock("../src/whoWebTheme", () => ({ useWhoFormTheme: () => ({}) }));
jest.mock("../src/MultilineInput", () => ({ MultilineInput: () => null }));
jest.mock("../src/deathRegistrationApi", () => ({
  getNativeRegistrationCase: (...args: unknown[]) => mockGet(...args),
  patchSupervisedDeath: (...args: unknown[]) => mockPatch(...args),
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

const idType = { code: "CRN", label: "Civil number", min_length: 3, max_length: 12, char_type: null, pattern: null, example: null, required_at_report: false, sort_order: 1 };
const requiredConfig = { project_id: "P1", consent_required: true, notice_versions: [], contacts: {}, retention: {}, refusal_behaviour: "interview_without_informant_data" };
const grantedEnvelope = { client_id: "c1", client_draft_id: null, decision: "granted", notice_version_id: "n1" };
const kind = (tree: ReactTestRenderer, type: string) => tree.root.findAll((node) => (node.type as string) === type)[0];

beforeEach(() => {
  jest.resetAllMocks();
  mockGet.mockResolvedValue(serverCase);
  mockPatch.mockResolvedValue(serverCase);
  mockOpenDb.mockResolvedValue(db);
  mockCachedTypes.mockResolvedValue([]);
  mockRefreshTypes.mockResolvedValue([]);
  mockCachedConsent.mockResolvedValue(undefined);
  mockRefreshConsent.mockResolvedValue(undefined);
});

/** The account database is read for settings only: nothing a case holds may reach it. */
const expectNoDbWrite = () => { for (const call of Object.values(db)) expect(call).not.toHaveBeenCalled(); };

describe("supervisor death-report correction", () => {
  it("loads the case online and reads only the project's settings from the account database", async () => {
    const tree = await render();
    expect(mockGet).toHaveBeenCalledWith("sup", "D1");
    expect(field(tree, "deceased_name").props["data-value"]).toBe("Asha");
    expect(mockCachedTypes).toHaveBeenCalledWith(db, "P1");
    expectNoDbWrite();
  });

  it("fetches the settings live when the account has none cached", async () => {
    mockRefreshTypes.mockResolvedValue([idType]);
    mockRefreshConsent.mockResolvedValue(requiredConfig);
    const tree = await render();
    expect(mockRefreshTypes).toHaveBeenCalledWith("sup", db, "P1");
    expect(mockRefreshConsent).toHaveBeenCalledWith("sup", db, "P1");
    expect(kind(tree, "ids").props.types).toEqual([idType]);
    expectNoDbWrite();
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

  it("sends changed informant, phone, ABHA, number and location keys only", async () => {
    mockCachedTypes.mockResolvedValue([idType]);
    const tree = await render();
    type(tree, "informant_name", "Ravi K");
    type(tree, "abha_number", "12345678901234");
    type(tree, "abha_address", "ravi@abdm");
    act(() => { kind(tree, "phones").props.onChange("informant_phone_2", "8888888888"); });
    act(() => { kind(tree, "ids").props.onChange("CRN", "ab123"); });
    act(() => { kind(tree, "loc").props.onChange({ latitude: 28.5, longitude: 77.2, accuracy_m: 9 }); });
    await save(tree);
    expect(mockPatch).toHaveBeenCalledWith("sup", "D1", {
      informant_name: "Ravi K", abha_number: "12345678901234", abha_address: "ravi@abdm", informant_phone_2: "8888888888",
      identifiers: { CRN: "AB123" }, latitude: 28.5, longitude: 77.2, accuracy_m: 9,
    }, "2026-10-01T10:00:00Z");
    expectNoDbWrite();
  });

  it("does not let an untouched invalid stored phone block the save", async () => {
    mockGet.mockResolvedValue({ ...serverCase, informant: { name: "Ravi", phone: "12345" } });
    const tree = await render();
    type(tree, "deceased_name", "Asha Devi");
    await save(tree);
    expect(mockPatch).toHaveBeenCalledWith("sup", "D1", { deceased_name: "Asha Devi" }, "2026-10-01T10:00:00Z");
  });

  it("asks for a granted consent before a changed informant name where the project requires it, then sends it once", async () => {
    mockCachedConsent.mockResolvedValue(requiredConfig);
    const tree = await render();
    type(tree, "informant_name", "Ravi K");
    await save(tree);
    expect(mockPatch).not.toHaveBeenCalled();
    expect(JSON.stringify(tree.toJSON())).toContain("consentNeededBeforeSave");
    act(() => { kind(tree, "consent").props.onDecision(grantedEnvelope); });
    await save(tree);
    expect(mockPatch).toHaveBeenCalledWith("sup", "D1", { informant_name: "Ravi K", consent: grantedEnvelope }, "2026-10-01T10:00:00Z");
    expectNoDbWrite();
  });

  it("asks for no consent where the project does not require it", async () => {
    mockCachedConsent.mockResolvedValue({ ...requiredConfig, consent_required: false });
    const tree = await render();
    type(tree, "informant_name", "Ravi K");
    expect(kind(tree, "consent")).toBeUndefined();
    await save(tree);
    expect(mockPatch).toHaveBeenCalledWith("sup", "D1", { informant_name: "Ravi K" }, "2026-10-01T10:00:00Z");
  });

  it("hides the registration numbers of a badge-only case the viewer may not change", async () => {
    mockCachedTypes.mockResolvedValue([idType]);
    const badge = [{ code: "CRN", label: "Civil number", present: true }];
    mockGet.mockResolvedValue({ ...serverCase, identifiers: badge, can_edit_identifiers: false });
    expect(kind(await render(), "ids")).toBeUndefined();
    mockGet.mockResolvedValue({ ...serverCase, identifiers: badge, can_edit_identifiers: true });
    expect(kind(await render(), "ids")).toBeDefined();
  });

  it("puts a server refusal of a number on its input", async () => {
    mockCachedTypes.mockResolvedValue([idType]);
    mockPatch.mockRejectedValue(new ApiError(422, "invalid_death", undefined, undefined, { error: "Civil number is not valid.", fields: ["identifiers.CRN"] }));
    const tree = await render();
    act(() => { kind(tree, "ids").props.onChange("CRN", "AB123"); });
    await save(tree);
    expect(kind(tree, "ids").props.errors).toEqual({ CRN: "Civil number is not valid." });
    expect(JSON.stringify(tree.toJSON())).toContain("serverValidation");
  });

  it("shows a duplicate-number warning after the save instead of leaving", async () => {
    mockCachedTypes.mockResolvedValue([idType]);
    mockPatch.mockResolvedValue({ warnings: [{ code: "identifier_in_use", field: "identifiers.CRN", message: "Already on another case." }] });
    const tree = await render();
    act(() => { kind(tree, "ids").props.onChange("CRN", "AB123"); });
    const reads = mockGet.mock.calls.length;
    await save(tree);
    expect(mockBack).not.toHaveBeenCalled();
    // The full case is read again (the PATCH reply may be the trimmed supervisor row).
    expect(mockGet.mock.calls.length).toBe(reads + 1);
    expect(kind(tree, "ids").props.warnings).toEqual({ CRN: "Already on another case." });
    act(() => { kind(tree, "ids").props.onContinue(); });
    expect(mockBack).toHaveBeenCalled();
  });

  it("says why when numbers are refused on a closed case or without permission", async () => {
    mockCachedTypes.mockResolvedValue([idType]);
    mockPatch.mockRejectedValueOnce(new ApiError(409, "case_closed"));
    const tree = await render();
    act(() => { kind(tree, "ids").props.onChange("CRN", "AB123"); });
    await save(tree);
    expect(JSON.stringify(tree.toJSON())).toContain("idCaseClosed");
    mockPatch.mockRejectedValueOnce(new ApiError(403, "forbidden"));
    await save(tree);
    expect(JSON.stringify(tree.toJSON())).toContain("serverForbidden");
  });

  it("asks for consent again when the server refuses the decision", async () => {
    mockCachedConsent.mockResolvedValue(requiredConfig);
    mockPatch.mockRejectedValue(new ApiError(422, "consent_invalid"));
    const tree = await render();
    type(tree, "informant_name", "Ravi K");
    act(() => { kind(tree, "consent").props.onDecision(grantedEnvelope); });
    await save(tree);
    expect(JSON.stringify(tree.toJSON())).toContain("consentNeededBeforeSave");
    expect(kind(tree, "consent")).toBeDefined();
  });
});
