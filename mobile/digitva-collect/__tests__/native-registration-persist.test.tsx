/**
 * A new native registration survives the app being hidden: the typed values
 * and their client death id stay in the encrypted store, the visible fields
 * are cleared while hidden and restored on return, and only Save or a
 * confirmed Discard removes the copy (one registration, never a duplicate).
 */
import React from "react";
import { DatabaseSync } from "node:sqlite";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { Alert, AppState, type AppStateStatus } from "react-native";

import { getMeta, migrate, type Db } from "../src/drafts";

const mockRouter = { back: jest.fn(), replace: jest.fn() };
const mockAccount = { user_id: "u1", name: "U", collection_access: true };
let mockDb: Db;

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

jest.mock("expo-router", () => ({
  Redirect: () => null,
  useLocalSearchParams: () => ({ userId: "u1", projectId: "P1" }),
  useRouter: () => mockRouter,
  useFocusEffect: (callback: () => void | (() => void)) => {
    const ReactActual = jest.requireActual("react") as typeof React;
    ReactActual.useEffect(() => callback(), [callback]);
  },
}));
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
jest.mock("@drguptavivek/who-2022-va", () => ({ resolveUiMessages: () => ({}), WHO_VA_BUILT_IN_UI_TRANSLATIONS: {} }), { virtual: true });
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
  const target = { key: "P1:S1", label: "S1", projectId: "P1", siteId: "S1" };
  return {
    getCachedReferenceData: async () => ({ bootstrap: {}, projects: [{ project, units: null }] }),
    getCachedIdentifierTypes: async () => [],
    refreshIdentifierTypes: async () => [],
    registersDeaths: () => true,
    targetsFrom: () => [target],
  };
});
jest.mock("../src/platform", () => ({ platformServices: {} }));
jest.mock("../src/i18n", () => ({ t: (key: string) => key, uiLocale: () => "en" }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  const Component = ({ children }: { children?: React.ReactNode }) => ReactActual.createElement("screen", null, children);
  return {
    Button: ({ label, onPress, disabled }: { label: string; onPress: () => void; disabled?: boolean }) =>
      ReactActual.createElement("button", { label, onPress, disabled }),
    Row: Component,
    Screen: Component,
    useUiStyles: () => ({ text: {}, muted: {}, error: {}, input: {}, card: {} }),
  };
});

import Register from "../src/nativeRoutes/register";

let appStateListener: ((state: AppStateStatus) => void) | undefined;
let tree: ReactTestRenderer;
const alert = jest.spyOn(Alert, "alert").mockImplementation(() => undefined);
const settle = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
const field = (name: string) => tree.root.find((node) => node.type === "input" && node.props["data-field"] === name);
const type = (name: string, value: string) => act(async () => field(name).props.onChange({ target: { value } }));
const press = (label: string) => act(async () => tree.root.findByProps({ label }).props.onPress());
const appState = async (state: AppStateStatus) => {
  await act(async () => appStateListener?.(state));
  await settle();
};
const savedCopy = () => getMeta<{ clientDeathId: string; fields: Record<string, string> }>(mockDb, "registration-in-progress");

beforeEach(async () => {
  Object.defineProperty(AppState, "currentState", { configurable: true, value: "active" });
  jest.spyOn(AppState, "addEventListener").mockImplementation((_event, listener) => {
    appStateListener = listener as (state: AppStateStatus) => void;
    return { remove: () => undefined } as ReturnType<typeof AppState.addEventListener>;
  });
  mockDb = memoryDb();
  await migrate(mockDb);
  mockRouter.back.mockClear();
  alert.mockClear();
  await act(async () => { tree = create(<Register />); });
  await settle();
});

afterEach(async () => {
  await act(async () => tree.unmount());
});

it("keeps typed values through the app being hidden and saves them once under the same id", async () => {
  await type("deceased_name", "Asha");
  await type("date_of_death", "2026-01-15");
  await type("date_of_birth", "1980-01-01");
  await press("sexFemale");

  await appState("background");
  expect(field("deceased_name").props["data-value"]).toBe("");
  const copy = await savedCopy();
  expect(copy?.fields).toMatchObject({ deceased_name: "Asha", deceased_sex: "female", date_of_death: "2026-01-15" });

  await appState("active");
  expect(field("deceased_name").props["data-value"]).toBe("Asha");
  expect(field("date_of_birth").props["data-value"]).toBe("1980-01-01");

  await press("save");
  await settle();
  const rows = await mockDb.getAllAsync<{ client_death_id: string }>("SELECT client_death_id FROM registrations", []);
  expect(rows).toEqual([{ client_death_id: copy!.clientDeathId }]);
  expect(await savedCopy()).toBeUndefined();
  expect(mockRouter.back).toHaveBeenCalled();
});

it("restores the copy when the screen is opened again after the app was closed", async () => {
  await type("deceased_name", "Ravi");
  await appState("background");
  const copy = await savedCopy();
  await act(async () => tree.unmount());

  await act(async () => { tree = create(<Register />); });
  await settle();
  expect(field("deceased_name").props["data-value"]).toBe("Ravi");
  expect((await savedCopy())?.clientDeathId).toBe(copy?.clientDeathId);
});

it("removes the copy only after a confirmed discard", async () => {
  await type("deceased_name", "Meena");
  await appState("background");
  await appState("active");
  expect(await savedCopy()).toBeDefined();

  await press("discard");
  const buttons = alert.mock.calls[0][2] as Array<{ text: string; style?: string; onPress?: () => void }>;
  expect(await savedCopy()).toBeDefined();
  await act(async () => buttons.find((button) => button.style === "destructive")?.onPress?.());
  await settle();

  expect(await savedCopy()).toBeUndefined();
  expect(field("deceased_name").props["data-value"]).toBe("");
});
