import React from "react";
import { act, create, type ReactTestInstance } from "react-test-renderer";

let mockParams: Record<string, string> = { userId: "coder-user", deathId: "death-id" };
let mockAccount: Record<string, unknown> = { user_id: "coder-user", name: "Coder", coding_access: true };
const mockRouter = { push: jest.fn(), replace: jest.fn(), back: jest.fn() };
const mockWorkspaceApi = { codeOwnSubmission: jest.fn().mockResolvedValue({ va_sid: "sid" }), releaseCoding: jest.fn() };

jest.mock("expo-router", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    Redirect: () => ReactActual.createElement("redirect"),
    useFocusEffect: (callback: () => (() => void) | void) => ReactActual.useEffect(callback, [callback]),
    useLocalSearchParams: () => mockParams,
    useRouter: () => mockRouter,
  };
});
jest.mock("../src/AppState", () => ({ useAppState: () => ({ accounts: [mockAccount] }) }));
jest.mock("../src/auth", () => ({}));
jest.mock("../src/interviewerDb", () => ({ isUnlocked: () => true, openInterviewerDb: async () => ({}) }));
jest.mock("../src/cases", () => ({
  CONTACT_OUTCOMES: ["reached", "no_answer", "wrong_number", "moved", "refused"],
  deleteAction: jest.fn(), discardRegistration: jest.fn(), getCase: async () => ({
    death_id: "death-id", unique_id: "unique-id", project_id: "P1", site_id: "S1", state: "submitted",
    code_now: true, va_sid: "sid", deceased: { name: "Deceased", age_years: 54 }, household_address: {}, informant: {},
  }),
  getRegistration: async () => undefined, listActions: async () => [], queueAction: jest.fn(), visitAt: () => null,
}));
jest.mock("../src/drafts", () => ({ draftForCase: async () => null }));
jest.mock("../src/sync", () => ({
  draftSyncDefaults: jest.fn(),
  fetchCaseDetail: async () => { throw new TypeError("offline"); },
  getCachedReferenceData: async () => undefined,
}));
jest.mock("../src/draftSync", () => ({ reconcileCaseDraft: async () => ({ draft: null, conflict: false }) }));
jest.mock("../src/workspace/api", () => ({ createWorkspaceApi: () => mockWorkspaceApi }));
jest.mock("../src/workspace/transport.native", () => ({ createNativeWorkspaceTransport: () => jest.fn() }));
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/deathWorkflow", () => ({ canFollowUpDeath: () => false, canStartDeathInterview: () => false, deathPhoneUrl: () => undefined }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  const { View } = jest.requireActual("react-native") as typeof import("react-native");
  return {
    Button: ({ label, onPress, disabled }: { label: string; onPress?: () => void; disabled?: boolean }) => ReactActual.createElement("button", {
      accessibilityRole: "button", accessibilityLabel: label, disabled, onPress,
    }),
    Row: ({ children }: { children: React.ReactNode }) => ReactActual.createElement(View, null, children),
    Screen: ({ children }: { children: React.ReactNode }) => ReactActual.createElement("screen", null, children),
    errorText: () => "error",
    stateLabel: (value: string) => value,
    useUiStyles: () => ({ error: {}, muted: {}, text: {}, headline: {}, card: {}, row: {}, input: {} }),
  };
});

import Case from "../src/nativeRoutes/case";

function button(root: ReactTestInstance, label: string) {
  return root.findAll((node) => node.props.accessibilityRole === "button" && node.props.accessibilityLabel === label)[0];
}

async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

test("native case detail opens Code now into the account-bound coding workspace", async () => {
  let renderer!: ReturnType<typeof create>;
  await act(async () => { renderer = create(<Case />); });
  await settle();
  expect(button(renderer.root, "codeNow")).toBeDefined();
  await act(async () => { button(renderer.root, "codeNow")?.props.onPress(); });
  await settle();
  expect(mockWorkspaceApi.codeOwnSubmission).toHaveBeenCalledWith("sid");
  expect(mockRouter.push).toHaveBeenCalledWith({ pathname: "/workspace", params: { userId: "coder-user", vaSid: "sid", mode: "coding" } });
  await act(async () => { renderer.unmount(); });
});
