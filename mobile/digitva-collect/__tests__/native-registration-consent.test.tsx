/**
 * Informant details on the phone need a recorded consent decision (docs/policy/respondent-consent-notice-draft.md,
 * "Phone flow"): closed with no notice, closed until a decision, opened by a grant, kept empty by a refusal, and the
 * decision stored with the queued registration. Real SQLite as native-registration-persist.test.tsx.
 */
import React from "react";
import { DatabaseSync } from "node:sqlite";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { Alert, AppState, type AppStateStatus } from "react-native";

import { getMeta, migrate, setMeta, type Db } from "../src/drafts";
import { computeUtf8Sha256HexSync } from "../src/consent";

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
let mockPanel: Record<string, unknown> | undefined;
jest.mock("../src/web/StationConsentPanel", () => ({
  RespondentConsentPanel: (props: Record<string, unknown>) => {
    mockPanel = props;
    return (jest.requireActual("react") as typeof React).createElement("panel", { "data-consent-panel": true });
  },
}));
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
import { getDeathRegistrationAccess, postNativeDeathRegistration } from "../src/deathRegistrationApi";
import { loadConsents, consentFor } from "../src/consentStore";

const NOTICE = "Notice";
const config = {
  project_id: "P1", consent_required: false, refusal_behaviour: "interview_without_informant_data",
  notice_versions: [{
    notice_version_id: "n1", version: 1, language: "en", text: NOTICE, text_sha256: computeUtf8Sha256HexSync(NOTICE),
    purposes: [{ code: "a", label: "A", required: true }], covered_fields: ["informant_name", "informant_phone", "address"], allowed_modes: ["spoken"], witness_allowed: false,
  }],
};
const envelope = (decision: "granted" | "refused") => ({
  client_id: "c1", client_draft_id: null, notice_version_id: "n1", notice_language: "en", notice_sha256: computeUtf8Sha256HexSync(NOTICE),
  decision, purposes: [{ code: "a", granted: decision === "granted" }], mode: "spoken", witness_present: false, supersedes_client_id: null, recorded_at: "2026-10-23T00:00:00Z",
});

let tree: ReactTestRenderer;
const settle = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
const fields = () => tree.root.findAll((node) => node.type === "input").map((node) => node.props["data-field"] as string);
const field = (name: string) => tree.root.find((node) => node.type === "input" && node.props["data-field"] === name);
const type = (name: string, value: string) => act(async () => field(name).props.onChange({ target: { value } }));
const press = (label: string) => act(async () => tree.root.findByProps({ label }).props.onPress());
const text = () => JSON.stringify(tree.toJSON());
const open = async (cached?: typeof config) => {
  mockDb = memoryDb();
  await migrate(mockDb);
  if (cached) await setMeta(mockDb, "consentConfig", cached, "P1");
  mockPanel = undefined;
  mockRouter.back.mockClear();
  await act(async () => { tree = create(<Register />); });
  await settle();
  await settle();
};
const fillRequired = async () => {
  await type("deceased_name", "Asha");
  await type("date_of_death", "2026-01-15");
  await type("date_of_birth", "1980-01-01");
  await press("sexFemale");
};
const queued = () => mockDb.getAllAsync<{ client_death_id: string; fields: string }>("SELECT client_death_id, fields FROM registrations", []);

beforeEach(() => {
  jest.spyOn(AppState, "addEventListener").mockImplementation(() => ({ remove: () => undefined }) as ReturnType<typeof AppState.addEventListener>);
  Object.defineProperty(AppState, "currentState", { configurable: true, value: "active" });
});
afterEach(async () => { await act(async () => tree.unmount()); });

it("keeps the informant's details closed, with the reason, when the project has no consent notice on the phone", async () => {
  await open();
  expect(fields()).not.toContain("informant_name");
  expect(fields()).not.toContain("address_house_street");
  expect(text()).toContain("consentInformantNoNotice");
  expect(mockPanel).toBeUndefined();
  await fillRequired();
  await press("save");
  await settle();
  expect(JSON.parse((await queued())[0].fields)).not.toHaveProperty("informant_name");
});

it("shows the cached notice, opens the informant fields only on a grant, and stores the decision with the registration", async () => {
  await open(config);
  expect(mockPanel).toMatchObject({ clientDraftId: null });
  expect(fields()).not.toContain("informant_name");
  expect(text()).toContain("consentInformantClosed");
  await act(async () => { (mockPanel!.onDecision as (e: unknown) => void)(envelope("granted")); });
  await settle();
  expect(fields()).toEqual(expect.arrayContaining(["informant_name", "address_house_street"]));
  await fillRequired();
  await type("informant_name", "Ravi");
  await press("save");
  await settle();
  const [row] = await queued();
  expect(JSON.parse(row.fields)).toMatchObject({ informant_name: "Ravi" });
  const stored = await getMeta<{ envelope: unknown; covered_fields: string[]; recorded_by: string }>(mockDb, `consent:reg:${row.client_death_id}`);
  expect(stored).toMatchObject({ envelope: envelope("granted"), covered_fields: ["informant_name", "informant_phone", "address"], recorded_by: "u1" });
});

it("under a refusal starts a separate direct refusal draft without registering identity", async () => {
  await open(config);
  await act(async () => { (mockPanel!.onDecision as (e: unknown) => void)(envelope("refused")); });
  await settle();
  expect(fields()).not.toContain("informant_name");
  expect(await queued()).toHaveLength(0);
  expect(mockRouter.replace).toHaveBeenCalledWith(expect.objectContaining({ pathname: "/form", params: expect.objectContaining({ projectId: "P1", siteId: "S1" }) }));
  const consents = await loadConsents(mockDb);
  expect([...consents.values()]).toEqual([expect.objectContaining({ envelope: expect.objectContaining({ decision: "refused" }) })]);
});

it("refuses to save informant details typed without a granted decision (a copy kept before consent existed)", async () => {
  mockDb = memoryDb();
  await migrate(mockDb);
  await setMeta(mockDb, "registration-in-progress", {
    clientDeathId: "11111111-1111-4111-8111-111111111111", projectId: "P1", siteId: "S1", orgUnitId: null,
    fields: { deceased_name: "Asha", deceased_sex: "female", date_of_death: "2026-01-15", date_of_birth: "1980-01-01", informant_name: "Ravi" },
    birthMode: "exact", ageConfirmationPending: false, ageConfirmationStartAfter: false,
  });
  mockPanel = undefined;
  await act(async () => { tree = create(<Register />); });
  await settle();
  await settle();
  expect(fields()).toContain("informant_name");
  await press("save");
  await settle();
  expect(text()).toContain("consentNeededBeforeSave");
  expect(await queued()).toEqual([]);
});

const familyConfig = {
  ...config,
  notice_versions: [{ ...config.notice_versions[0], covered_fields: ["informant_name", "father_name", "mother_name"] }],
};

it("locks the father's and mother's names with the informant's until a decision, and a refusal clears them (the server's covered list)", async () => {
  await open(familyConfig);
  expect(fields()).not.toContain("father_name");
  expect(fields()).not.toContain("mother_name");
  expect(fields()).not.toContain("informant_name");
  await act(async () => { (mockPanel!.onDecision as (e: unknown) => void)(envelope("granted")); });
  await settle();
  expect(fields()).toEqual(expect.arrayContaining(["father_name", "mother_name"]));
  await type("father_name", "Hari");
  await press("consentChange");
  await settle();
  expect(fields()).toContain("father_name"); // typed before the change: shown, saving is blocked until a decision
  await act(async () => { (mockPanel!.onDecision as (e: unknown) => void)(envelope("refused")); });
  await settle();
  expect(fields()).not.toContain("father_name");
  await fillRequired();
  await press("save");
  await settle();
  const [row] = await queued();
  expect(JSON.parse(row.fields)).not.toHaveProperty("father_name");
});

it("Change on a queued registration keeps the stored decision until a new one replaces it", async () => {
  await open(config);
  await act(async () => { (mockPanel!.onDecision as (e: unknown) => void)(envelope("granted")); });
  await settle();
  const keys = () => mockDb.getAllAsync<{ key: string }>("SELECT key FROM meta WHERE key LIKE 'consent:reg:%'", []);
  expect(await keys()).toHaveLength(1);
  await press("consentChange");
  await settle();
  expect(await keys()).toHaveLength(1);
  await act(async () => { (mockPanel!.onDecision as (e: unknown) => void)({ ...envelope("refused"), client_id: "c2" }); });
  await settle();
  const [{ key }] = await keys();
  expect(await getMeta(mockDb, key)).toMatchObject({ envelope: { client_id: "c1", decision: "granted" } });
  expect(mockRouter.replace).toHaveBeenCalledWith(expect.objectContaining({ pathname: "/form" }));
});

it("a registration-only user cannot create a registration after refusal", async () => {
  (getDeathRegistrationAccess as jest.Mock).mockResolvedValue({ projects: [{ project_id: "P1", project_name: "P1", has_tree: false, actions: { interview: [], register_death: [{ site_id: "S1", site_name: "S1", org_units: [] }] } }] });
  (postNativeDeathRegistration as jest.Mock).mockResolvedValueOnce({ death_id: "d9", unique_id: "u9" });
  await open(config);
  await act(async () => { (mockPanel!.onDecision as (e: unknown) => void)(envelope("refused")); });
  await settle();
  (getDeathRegistrationAccess as jest.Mock).mockResolvedValue(undefined);
  expect(postNativeDeathRegistration).not.toHaveBeenCalled();
  expect(fields()).toHaveLength(0);
  await press("Save refusal");
  await settle();
  const [row] = await queued();
  expect(JSON.parse(row.fields)).toEqual({ refusal_only: true });
  expect(await getMeta(mockDb, `consent:reg:${row.client_death_id}`)).toMatchObject({ envelope: { decision: "refused" } });
});
