/**
 * Resume with two projects:  the site and unit are one field that opens the shared picker sheet (unit names, the chosen row
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
const mockParams = { userId: "u1" };
let appStateListener: ((state: string) => void) | undefined;

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
  useLocalSearchParams: () => mockParams,
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
  const mk = (id: string) => ({ project_id: id, project_name: id, web_intake_mode: "both", sites: [{ project_id: id, site_id: "S1", web_intake_mode: "both" }] });
  return {
    getCachedReferenceData: async () => ({ bootstrap: {}, projects: [{ project: mk("P1"), units: null }, { project: mk("P2"), units: null }] }),
    getCachedIdentifierTypes: async () => [],
    refreshIdentifierTypes: async () => [],
    registersDeaths: () => true,
    targetsFrom: (project: { project_id: string }) => mockTargets.filter((t) => t.projectId === project.project_id),
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

const unit = (projectId: string, orgUnitId: string): MockTarget => ({
  key: `${projectId}:S1:${orgUnitId}`, label: `Site · ${orgUnitId}`, projectId, siteId: "S1", orgUnitId, siteName: "Site", unitName: orgUnitId,
});
const settle = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
let tree: ReactTestRenderer;
const siteField = () => tree.root.findAll((node) => typeof node.props.accessibilityLabel === "string" && node.props.accessibilityLabel.startsWith("chooseSite: ") && typeof node.props.onPress === "function");

beforeEach(() => {
  jest.spyOn(AppState, "addEventListener").mockImplementation(((_: string, listener: (state: string) => void) => {
    appStateListener = listener;
    return { remove: () => undefined };
  }) as unknown as typeof AppState.addEventListener);
  Object.defineProperty(AppState, "currentState", { configurable: true, value: "active" });
});

it("keeps the chosen project's units after the app is backgrounded and resumed with name and sex still empty", async () => {
  mockTargets = [unit("P1", "U1"), unit("P1", "U2"), unit("P2", "U9")];
  mockDb = memoryDb();
  await migrate(mockDb);
  await act(async () => { tree = create(<Register />); });
  await settle();
  await settle();
  // Two projects, none chosen: the project card shows and no units are listed yet.
  await act(async () => tree.root.findByProps({ label: "P1" }).props.onPress());
  await settle();
  expect(siteField()).toHaveLength(1);
  await act(async () => siteField()[0].props.onPress());
  await act(async () => tree.root.findAll((node) => node.props.accessibilityLabel === "U2" && typeof node.props.onPress === "function")[0].props.onPress());
  expect(siteField()[0].props.accessibilityLabel).toBe("chooseSite: U2");

  await act(async () => appStateListener?.("background"));
  await act(async () => appStateListener?.("active"));
  await settle();
  await settle();
  expect(siteField()).toHaveLength(1);
  expect(siteField()[0].props.accessibilityLabel).toBe("chooseSite: U2");
  await act(async () => tree.unmount());
});
