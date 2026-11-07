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
const mockScrollToEnd = jest.fn();
let mockTargets: MockTarget[] = [];
let mockParams: Record<string, string> = { userId: "u1" };

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
    Screen: ({ children, footer, scrollRef }: { children?: React.ReactNode; footer?: React.ReactNode; scrollRef?: React.Ref<unknown> }) => { ReactActual.useEffect(() => { (scrollRef as React.MutableRefObject<unknown>).current = { scrollToEnd: mockScrollToEnd }; }, [scrollRef]); return ReactActual.createElement("screen", null, children, footer); },
    announce: jest.fn(),
    useUiStyles: () => ({ text: {}, muted: {}, error: {}, input: {}, card: {}, fieldLabel: {} }),
  });
});

import Register from "../src/nativeRoutes/register";

const target = (projectId: string): MockTarget => ({ key: `${projectId}:S1`, label: `Site ${projectId}`, projectId, siteId: "S1" });
let tree: ReactTestRenderer;
const settle = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
const open = async (params: Record<string, string>) => {
  mockParams = { userId: "u1", ...params };
  mockTargets = [target("P1"), target("P2")];
  mockDb = memoryDb();
  await migrate(mockDb);
  await act(async () => { tree = create(<Register />); });
  await settle();
  await settle();
};
const texts = () => tree.root.findAll((node) => typeof node.type === "string" && typeof node.props.children === "string").map((node) => node.props.children);
const siteField = () => tree.root.findAll((node) => typeof node.props.accessibilityLabel === "string" && node.props.accessibilityLabel.startsWith("chooseSite: ") && typeof node.props.onPress === "function");

beforeEach(() => {
  jest.spyOn(AppState, "addEventListener").mockImplementation(() => ({ remove: () => undefined }) as ReturnType<typeof AppState.addEventListener>);
  Object.defineProperty(AppState, "currentState", { configurable: true, value: "active" });
  mockScrollToEnd.mockClear();
});
afterEach(async () => { await act(async () => tree.unmount()); });

// digitva-bl3b: the worklist passes projectId="" until a project is picked; that is not a project.
it.each([[""], ["GONE"]])("with two projects and projectId %p it asks for a project instead of saying there are no sites", async (projectId) => {
  await open({ projectId });
  expect(texts()).toContain("chooseProject");
  expect(texts()).not.toContain("noSites");
  expect(siteField()).toHaveLength(0);
});

it("picking a project then lists its sites", async () => {
  await open({ projectId: "" });
  await act(async () => tree.root.findAll((n) => n.props.label === "P2" && typeof n.props.onPress === "function")[0].props.onPress());
  expect(siteField()).toHaveLength(1);
  expect(texts()).not.toContain("noSites");
});

it("a valid projectId still selects its sites", async () => {
  await open({ projectId: "P2" });
  expect(siteField()).toHaveLength(1);
});

// digitva-frnc: a failed validation brings the message into view.
it("Save with a required field missing scrolls to the message", async () => {
  await open({ projectId: "P1" });
  await act(async () => siteField()[0].props.onPress());
  await act(async () => tree.root.findAll((n) => n.props.accessibilityLabel === "Site P1" && typeof n.props.onPress === "function")[0].props.onPress());
  jest.useFakeTimers();
  await act(async () => tree.root.findByProps({ label: "save" }).props.onPress());
  await act(async () => { jest.runAllTimers(); });
  jest.useRealTimers();
  expect(texts()).toContain("errRequired");
  expect(mockScrollToEnd).toHaveBeenCalledWith({ animated: true });
});
