/**
 * Register a death: the site and unit are one field that opens the shared picker sheet (unit names, the chosen row
 * ticked, a shared site named once under the list), and the queued registration keeps the same site_id and
 * org_unit_id the old per-unit buttons set. Real SQLite as native-registration-persist.test.tsx.
 */
import React from "react";
import { DatabaseSync } from "node:sqlite";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { AppState } from "react-native";

import { migrate, type Db } from "../src/drafts";

const mockRouter = { back: jest.fn(), replace: jest.fn() };
const mockAccount = { user_id: "u1", name: "U", collection_access: true };
let mockDb: Db;
type MockTarget = { key: string; label: string; projectId: string; siteId: string; orgUnitId?: string; siteName?: string; unitName?: string };
let mockTargets: MockTarget[] = [];

function memoryDb(): Db {
  const db = new DatabaseSync(":memory:");
  return {
    execAsync: async (sql) => void db.exec(sql),
    runAsync: async (sql, params) => db.prepare(sql).run(...params),
    getAllAsync: async <T,>(sql: string, params: Array<string | number | null>) => db.prepare(sql).all(...params) as T[],
    getFirstAsync: async <T,>(sql: string, params: Array<string | number | null>) => (db.prepare(sql).get(...params) as T | undefined) ?? null,
    closeAsync: async () => db.close(),
  };
}

const mockNavigation = { addListener: () => () => undefined, dispatch: () => undefined };
jest.mock("expo-router", () => ({
  useNavigation: () => mockNavigation,
  useIsFocused: () => true,
  Redirect: () => null,
  useLocalSearchParams: () => ({ userId: "u1", projectId: "P1" }),
  useRouter: () => mockRouter,
  useFocusEffect: (callback: () => void | (() => void)) => {
    const ReactActual = jest.requireActual("react") as typeof React;
    ReactActual.useEffect(() => callback(), [callback]);
  },
}));
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock("expo-crypto", () => ({ randomUUID: () => require("node:crypto").randomUUID() }));
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
jest.mock("@drguptavivek/who-2022-va", () => ({ FormThemeContext: (jest.requireActual("react") as typeof React).createContext(undefined), resolveUiMessages: () => ({}), WHO_VA_BUILT_IN_UI_TRANSLATIONS: {} }), { virtual: true });
jest.mock("../src/AppState", () => ({ useAppState: () => ({ accounts: [mockAccount], lockVersion: 0 }) }));
jest.mock("../src/deathRegistrationApi", () => ({
  getDeathRegistrationAccess: jest.fn(async () => undefined),
  getNativeRegistrationCase: jest.fn(),
  getNativeRegisteredDeaths: jest.fn(),
  patchNativeDeathRegistration: jest.fn(),
  postNativeDeathRegistration: jest.fn(),
}));
jest.mock("../src/interviewerDb", () => ({ isUnlocked: () => true, openInterviewerDb: async () => mockDb }));
jest.mock("../src/sync", () => {
  const project = { project_id: "P1", project_name: "P1", web_intake_mode: "both", sites: [{ project_id: "P1", site_id: "S1", web_intake_mode: "both" }] };
  return {
    getCachedReferenceData: async () => ({ bootstrap: {}, projects: [{ project, units: null }] }),
    getCachedIdentifierTypes: async () => [],
    refreshIdentifierTypes: async () => [],
    registersDeaths: () => true,
    targetsFrom: () => mockTargets,
  };
});
jest.mock("../src/platform", () => ({ platformServices: {} }));
jest.mock("../src/i18n", () => ({ ...require("../test-support/i18nMockExtras").i18nMockExtras, t: (key: string) => key, uiLocale: () => "en" }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  const Component = ({ children }: { children?: React.ReactNode }) => ReactActual.createElement("screen", null, children);
  return require("../test-support/uiMockExtras").withUiExtras({
    Button: ({ label, onPress, disabled }: { label: string; onPress: () => void; disabled?: boolean }) =>
      ReactActual.createElement("button", { label, onPress, disabled }),
    Row: Component,
    Card: Component,
    Separator: () => null,
    Notice: ({ children, action }: { children?: React.ReactNode; action?: React.ReactNode }) => ReactActual.createElement("notice", null, children, action),
    ChoiceRow: ({ label, onPress }: { label: string; onPress: () => void }) => ReactActual.createElement("button", { label, onPress }),
    SegmentedControl: ({ options, onChange, disabled }: { options: Array<{ value: string; label: string }>; onChange: (value: string) => void; disabled?: boolean }) =>
      ReactActual.createElement("segmented", null, options.map((option) => ReactActual.createElement("button", { key: option.value, label: option.label, disabled, onPress: () => onChange(option.value) }))),
    // The sticky footer holds Save, Cancel and Discard.
    Screen: ({ children, footer }: { children?: React.ReactNode; footer?: React.ReactNode }) => ReactActual.createElement("screen", null, children, footer),
    useUiStyles: () => ({ text: {}, muted: {}, error: {}, input: {}, card: {}, fieldLabel: {} }),
  });
});

import Register from "../src/nativeRoutes/register";

const unit = (siteId: string, siteName: string, orgUnitId: string, unitName: string): MockTarget => ({
  key: `P1:${siteId}:${orgUnitId}`, label: `${siteName} · ${unitName}`, projectId: "P1", siteId, orgUnitId, siteName, unitName,
});

let tree: ReactTestRenderer;
const settle = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
const field = (name: string) => tree.root.find((node) => node.type === "input" && node.props["data-field"] === name);
const type = (name: string, value: string) => act(async () => field(name).props.onChange({ target: { value } }));
const press = (label: string) => act(async () => tree.root.findByProps({ label }).props.onPress());
const pressable = (label: string) => tree.root.findAll((node) => node.props.accessibilityLabel === label && typeof node.props.onPress === "function");
const siteField = () => tree.root.findAll((node) => typeof node.props.accessibilityLabel === "string" && node.props.accessibilityLabel.startsWith("chooseSite: ") && typeof node.props.onPress === "function");
// Host text nodes that read exactly *value* (the open Modal makes toJSON circular).
const shown = (value: string) => tree.root.findAll((node) => typeof node.type === "string" && node.props.children === value).length;
const open = async (targets: MockTarget[]) => {
  mockTargets = targets;
  mockDb = memoryDb();
  await migrate(mockDb);
  await act(async () => { tree = create(<Register />); });
  await settle();
  await settle();
};

beforeEach(() => {
  jest.spyOn(AppState, "addEventListener").mockImplementation(() => ({ remove: () => undefined }) as ReturnType<typeof AppState.addEventListener>);
  Object.defineProperty(AppState, "currentState", { configurable: true, value: "active" });
  mockRouter.back.mockClear();
});
afterEach(async () => { await act(async () => tree.unmount()); });

it("shows one field instead of a button per unit, and the picked unit is what the registration saves", async () => {
  await open([unit("S1", "Hamirpur", "U1", "Ward 1"), unit("S1", "Hamirpur", "U2", "Ward 2")]);
  expect(siteField()).toHaveLength(1);
  expect(siteField()[0].props.accessibilityLabel).toBe("chooseSite: siteUnitNotChosen");
  expect(tree.root.findAll((node) => node.props.label === "Hamirpur · Ward 2")).toHaveLength(0);

  await act(async () => siteField()[0].props.onPress());
  // Unit names only; the one shared site is named once, under the list.
  expect(pressable("Ward 1")).toHaveLength(1);
  expect(pressable("Ward 2")).toHaveLength(1);
  expect(shown("Hamirpur")).toBe(1);
  await act(async () => pressable("Ward 2")[0].props.onPress());
  expect(pressable("Ward 1")).toHaveLength(0); // the sheet closed
  expect(siteField()[0].props.accessibilityLabel).toBe("chooseSite: Ward 2");

  await act(async () => siteField()[0].props.onPress());
  expect(pressable("Ward 2")[0].props.accessibilityState).toEqual({ selected: true });
  expect(pressable("Ward 1")[0].props.accessibilityState).toEqual({ selected: false });
  await act(async () => pressable("pickerClose")[0].props.onPress());

  await type("deceased_name", "Asha");
  await type("date_of_death", "2026-01-15");
  await type("date_of_birth", "1980-01-01");
  await press("sexFemale");
  await press("save");
  await settle();
  const rows = await mockDb.getAllAsync<{ site_id: string; org_unit_id: string | null }>("SELECT site_id, org_unit_id FROM registrations", []);
  expect(rows).toEqual([{ site_id: "S1", org_unit_id: "U2" }]);
});

it("groups units under site headers across several sites, with no shared-site note", async () => {
  await open([unit("S1", "Hamirpur", "U1", "Ward 1"), unit("S2", "Kangra", "U3", "Ward 3")]);
  await act(async () => siteField()[0].props.onPress());
  expect(pressable("Ward 3")).toHaveLength(1);
  const headers = tree.root.findAll((node) => node.props.accessibilityRole === "header" && typeof node.props.children === "string").map((node) => node.props.children);
  expect(headers).toEqual(expect.arrayContaining(["Hamirpur", "Kangra"]));
  expect(shown("Hamirpur")).toBe(1); // the header only, no note
});

it("still chooses the only unit by itself", async () => {
  await open([unit("S1", "Hamirpur", "U1", "Ward 1")]);
  expect(siteField()[0].props.accessibilityLabel).toBe("chooseSite: Ward 1");
});

it("labels the date-of-birth field only by the chosen precision row, never by a repeated sub-label", async () => {
  await open([unit("S1", "Hamirpur", "U1", "Ward 1")]);
  for (const [mode, fieldName, subLabel] of [["dobExact", "date_of_birth", "dobExact"], ["dobMonthYear", "date_of_birth_partial", "dobMonthYear"], ["dobYear", "date_of_birth_partial", "dobYearField"]] as const) {
    if (mode !== "dobExact") await press(mode);
    expect(tree.root.findAll((node) => node.props["data-field"] === fieldName).length).toBeGreaterThan(0);
    // The precision text shows once (its choice row), not again as the field's label.
    expect(tree.root.findAll((node) => node.props.label === subLabel && node.props.onPress === undefined)).toHaveLength(0);
    if (mode === "dobYear") expect(shown("dobYearField")).toBe(0);
  }
});
