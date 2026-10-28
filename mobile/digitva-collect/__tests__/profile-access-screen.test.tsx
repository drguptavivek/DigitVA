import React from "react";
import { Text } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import ProfileAccess from "../src/nativeRoutes/profileAccess";
import { setUiLocale } from "../src/i18n";
import type { LoadedAccessProfile } from "../src/accessProfile";
import type { Account } from "../src/auth";

const mockLoad = jest.fn<Promise<LoadedAccessProfile>, unknown[]>();
let mockAccount: Account;
let mockUnlocked = true;
let mockSlot = "active";
let mockServer: string | undefined = "https://digitvav3.causeofdeathindia.com";
let mockUserId: string | undefined = "U";
let mockOffline = false;
jest.mock("expo-router", () => ({ useFocusEffect: (effect: () => void) => require("react").useEffect(effect, [effect]) }));
jest.mock("../src/AppState", () => ({ useAppState: () => ({ accounts: [mockAccount], slot: mockSlot, lockVersion: 0 }) }));
jest.mock("../src/nativeShell/shellContext", () => ({ useShell: () => ({ userId: mockUserId, server: mockServer, sync: { offline: mockOffline } }) }));
jest.mock("../src/accessProfile", () => ({
  ...jest.requireActual("../src/accessProfile"), loadAccessProfile: (...args: unknown[]) => mockLoad(...args),
}));
jest.mock("../src/auth", () => ({}));
jest.mock("../src/drafts", () => ({}));
jest.mock("../src/sync", () => ({}));
jest.mock("../src/offlineProfile", () => ({}));
jest.mock("../src/interviewerDb", () => ({ isUnlocked: () => mockUnlocked }));
jest.mock("../src/icd11DorisPreference", () => ({ useIcd11DorisPreference: () => ({ ready: true, enabled: false }) }));
jest.mock("../src/ui", () => ({
  Screen: ({ title, children }: { title: string; children: React.ReactNode }) => {
    const RN = require("react-native");
    return <RN.View><RN.Text>{title}</RN.Text>{children}</RN.View>;
  },
  Button: ({ label, onPress }: { label: string; onPress: () => void }) => {
    const RN = require("react-native");
    return <RN.Pressable onPress={onPress}><RN.Text>{label}</RN.Text></RN.Pressable>;
  },
  useUiStyles: () => ({ text: {}, muted: {}, error: {}, card: {}, headline: {} }),
}));

const digest = "a".repeat(64);
const serverResult = (current = true): LoadedAccessProfile => ({
  kind: "server", current,
  profile: { schema: 1, slot: "active", server: mockServer!, userId: "U", accessDigest: digest,
    refreshedAt: "2026-10-28T04:00:00Z", name: "Asha", roles: ["Coder"], codingLanguages: ["hi"],
    projects: [{ id: "P", name: "Project One", rights: ["Coder · North district · Coding allowed"], intake: "Off",
      codingMode: "Unmasked with DORIS", classification: "ICD11", selfCoding: "Enabled", localCoding: "Eligible", codingScope: "Project scope" }],
  },
});
const text = (tree: TestRenderer.ReactTestRenderer) => tree.root.findAllByType(Text).map((node) => node.props.children).flat().join(" ");
async function render() {
  let tree!: TestRenderer.ReactTestRenderer;
  await act(async () => { tree = TestRenderer.create(<ProfileAccess />); });
  return tree;
}

beforeEach(() => {
  jest.clearAllMocks();
  setUiLocale("en");
  mockAccount = { user_id: "U", name: "Asha", server: "https://digitvav3.causeofdeathindia.com", coding_history_access: digest };
  mockSlot = "active";
  mockUserId = "U";
  mockServer = mockAccount.server;
  mockUnlocked = true;
  mockOffline = false;
  mockLoad.mockResolvedValue(serverResult());
});

test("shows project access, current status and device preference separately without guessed questionnaire languages", async () => {
  const tree = await render();
  expect(mockLoad).toHaveBeenCalledWith("U", "active", mockServer, false);
  expect(text(tree)).toContain("Asha");
  expect(text(tree)).toContain("Project One");
  expect(text(tree)).toContain("Current");
  expect(text(tree)).toContain("North district");
  expect(text(tree)).toContain("Questionnaire languages are not saved on this phone");
  expect(text(tree)).toContain("ICD-11 / DORIS tools on this phone");
});

test("labels saved rights with a timestamp", async () => {
  mockLoad.mockResolvedValue(serverResult(false));
  expect(text(await render())).toContain("Saved on phone");
});

test("demo shows only the current demo account and its exact server", async () => {
  mockSlot = "demo";
  mockServer = "https://demo.causeofdeathindia.com";
  const result = serverResult();
  if (result.kind === "server") result.profile.slot = "demo";
  mockLoad.mockResolvedValue(result);
  const tree = await render();
  expect(text(tree)).toContain("Demo");
  expect(text(tree)).toContain(mockServer);
  expect(mockLoad).toHaveBeenCalledWith("U", "demo", mockServer, false);
});

test("standalone renders only local profile and disabled server even with retained enrolment", async () => {
  mockAccount.standalone = true;
  mockLoad.mockResolvedValue({ kind: "standalone", userId: "U", slot: "active", name: "Local coder", profile: null });
  const tree = await render();
  expect(mockLoad).toHaveBeenCalledWith("U", "active", undefined, false);
  expect(text(tree)).toContain("Local coder");
  expect(text(tree)).toContain("Server :  Disabled");
  expect(text(tree)).not.toContain("Project One");
  expect(text(tree)).not.toContain(mockServer!);
});

test.each(["needs_sign_in", "signed_out", "access_removed", "terms_required", "access_blocked"]) ("hides profile and performs no load behind %s", async (gate) => {
  Object.assign(mockAccount, { [gate]: gate === "access_blocked" ? "maintenance" : true });
  const tree = await render();
  expect(mockLoad).not.toHaveBeenCalled();
  expect(text(tree)).toContain("Sign in and unlock");
  expect(text(tree)).not.toContain("Asha");
});

test("locking or access-digest change hides an already displayed snapshot immediately", async () => {
  const tree = await render();
  expect(text(tree)).toContain("Project One");
  mockAccount.coding_history_access = "b".repeat(64);
  await act(async () => { tree.update(<ProfileAccess />); });
  expect(text(tree)).not.toContain("Project One");
  mockUnlocked = false;
  await act(async () => { tree.update(<ProfileAccess />); });
  expect(text(tree)).toContain("Sign in and unlock");
});

test("malformed or refused refresh renders an error without saved roles", async () => {
  mockLoad.mockRejectedValue(new Error("unavailable"));
  const tree = await render();
  expect(text(tree)).toContain("Profile and project access is unavailable");
  expect(text(tree)).not.toContain("Project One");
});

test("translates app labels while preserving project names and unknown server roles", async () => {
  const result = serverResult();
  if (result.kind === "server") {
    result.profile.roles.push("site_assistant_qa");
    result.profile.projects[0].rights.push("site_assistant_qa · North district · Coding allowed");
  }
  mockLoad.mockResolvedValue(result);
  setUiLocale("hi");
  const rendered = text(await render());
  expect(rendered).toContain("प्रोफ़ाइल और परियोजना की अनुमतियाँ");
  expect(rendered).toContain("कोडर");
  expect(rendered).toContain("किसी परियोजना में कोडिंग की अनुमति नहीं मिलती");
  expect(rendered).toContain("North district");
  expect(rendered).toContain("Project One");
  expect(rendered).toContain("site_assistant_qa");
  expect(rendered).toContain("ICD11");
});
