/**
 * Home and the Active/Demo slots (docs/policy/public-demo.md section 10.1): an
 * empty Active slot goes to QR enrolment as before, but an empty Demo slot is
 * never sent there (a QR enrolment would fill Active): it hands the phone back
 * to Active.
 */
import React, { type ReactNode } from "react";
import { act, create } from "react-test-renderer";

const mockSwitchSlot = jest.fn(async (_slot: string) => true);
const mockPush = jest.fn();
let mockState: Record<string, unknown> = {};
jest.mock("react-native", () => ({
  ActivityIndicator: "spinner", Image: "image", Platform: { OS: "android" }, Pressable: "pressable", Text: "text", View: "view",
}));
jest.mock("expo-router", () => {
  const R = jest.requireActual("react") as typeof React;
  return {
    Redirect: ({ href }: { href: string }) => R.createElement("redirect", { href }),
    useRouter: () => ({ push: mockPush, replace: jest.fn() }),
  };
});
jest.mock("../src/AppState", () => ({ useAppState: () => mockState }));
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/standalone/home", () => ({ homeRoute: () => "/standalone" }));
let mockUnlocked = false;
const mockOpenDb = jest.fn(async (_userId: string) => ({}));
let mockInterviews = 0;
jest.mock("../src/interviewerDb", () => ({ isUnlocked: () => mockUnlocked, openInterviewerDb: (userId: string) => mockOpenDb(userId) }));
jest.mock("../src/standalone/adopt", () => ({ standaloneCounts: async () => ({ interviews: mockInterviews, codings: 0, staleDraftIds: [], held: 0 }) }));
jest.mock("../src/DemoPanel", () => ({ __esModule: true, default: () => null }));
jest.mock("../src/browserScreens", () => ({ WorkspaceScreen: () => null }));
// Home reads one radius token; the real theme pulls in native preferences.
jest.mock("../src/theme", () => ({ radius: { lg: 8 }, spacing: { xs: 8 } }));
jest.mock("../src/ui", () => {
  const R = jest.requireActual("react") as typeof React;
  return {
    Button: ({ label, onPress }: { label: string; onPress?: () => void }) => R.createElement("button", { onPress }, label),
    TextLink: ({ label, onPress }: { label: string; onPress?: () => void }) => R.createElement("button", { onPress, link: true }, label),
    Card: ({ children, grouped }: { children: ReactNode; grouped?: boolean }) => R.createElement("card", { grouped }, children),
    Separator: () => R.createElement("separator"),
    // A profile row: its press, then its label, second line and badge value as text nodes.
    ListRow: ({ label, secondary, value, badge, emphasis, chevron, onPress, trailing }: { label: string; secondary?: string; value?: string; badge?: boolean; emphasis?: boolean; chevron?: boolean; onPress?: () => void; trailing?: ReactNode }) =>
      R.createElement("pressable", { onPress, emphasis, chevron, badge: badge && value ? value : undefined },
        R.createElement("text", null, label), secondary ? R.createElement("text", null, secondary) : null, value ? R.createElement("text", null, value) : null, trailing),
    Screen: ({ children, lead }: { children: ReactNode; lead?: ReactNode }) => R.createElement("main", null, lead, children),
    Notice: ({ children }: { children: ReactNode }) => R.createElement("aside", null, children),
    useUiStyles: () => ({ text: {}, muted: {}, error: {}, card: {} }),
  };
});

import Home from "../src/nativeRoutes/index";

async function render() {
  let tree!: ReturnType<typeof create>;
  await act(async () => {
    tree = create(<Home />);
  });
  return tree;
}
const redirects = (tree: ReturnType<typeof create>) =>
  tree.root.findAll((node) => (node.type as unknown) === "redirect").map((node) => node.props.href);

beforeEach(() => {
  mockSwitchSlot.mockClear();
  mockUnlocked = false;
  mockInterviews = 0;
  mockOpenDb.mockClear();
});

it("sends an empty Active slot to QR enrolment, as before slots", async () => {
  mockState = { ready: true, device: undefined, accounts: [], slot: "active", switchSlot: mockSwitchSlot };
  expect(redirects(await render())).toEqual(["/enrol"]);
  expect(mockSwitchSlot).not.toHaveBeenCalled();
});

it("never sends an empty Demo slot to QR enrolment: it switches to Active", async () => {
  mockState = { ready: true, device: undefined, accounts: [{ user_id: "demo-user", name: "D" }], slot: "demo", switchSlot: mockSwitchSlot };
  const tree = await render();
  expect(mockSwitchSlot).toHaveBeenCalledWith("active");
  expect(redirects(tree)).toEqual([]);
});

it("shows an enrolled Demo slot as usual", async () => {
  mockState = {
    ready: true, accounts: [], slot: "demo", switchSlot: mockSwitchSlot,
    device: { device_id: "d", server: "https://demo.example", project_id: "D", project_name: "Demo project" },
  };
  const tree = await render();
  expect(mockSwitchSlot).not.toHaveBeenCalled();
  expect(redirects(tree)).toEqual([]);
  expect(JSON.stringify(tree.toJSON())).toContain("Demo project");
});

it("opens Settings in the standalone account context from the locked accounts list", async () => {
  mockPush.mockClear();
  mockState = { ready: true, device: undefined, accounts: [{ user_id: "offline", name: "EngineBenchmark", standalone: true }], slot: "active", switchSlot: mockSwitchSlot };
  const tree = await render();
  const settings = tree.root.findAll((node) => (node.type as unknown) === "button" && node.props.children === "settings")[0];
  await act(async () => settings.props.onPress());
  expect(mockPush).toHaveBeenCalledWith({ pathname: "/settings", params: { userId: "offline" } });
});

it("shows a signed-out profile as kept and sends it to sign-in, then its PIN", async () => {
  mockPush.mockClear();
  const device = { device_id: "d1", server: "https://live.example.org", project_name: "P" };
  mockState = {
    ready: true, device, slot: "active", switchSlot: mockSwitchSlot,
    accounts: [{ user_id: "out", name: "Ravi", server: device.server, needs_sign_in: true, signed_out: true }],
  };
  const tree = await render();
  const texts = tree.root.findAll((node) => (node.type as unknown) === "text").map((node) => node.props.children);
  expect(texts).toContain("signedOutKept");
  expect(texts).not.toContain("signInAgain");
  const card = tree.root.findAll((node) => (node.type as unknown) === "pressable")[0];
  await act(async () => card.props.onPress());
  expect(mockPush).toHaveBeenCalledWith({ pathname: "/sign-in", params: { userId: "out" } });
});

it("lists the profiles as rows of one grouped card: name, lock state, chevron; Settings is a link under Add profile", async () => {
  mockPush.mockClear();
  const device = { device_id: "d1", server: "https://live.example.org", project_id: "GUJ026", project_name: "GUJARAT HEALTH SYSTEM" };
  mockState = {
    ready: true, device, slot: "active", switchSlot: mockSwitchSlot,
    accounts: [{ user_id: "a", name: "Asha" }, { user_id: "b", name: "Ravi" }],
  };
  const tree = await render();
  const cards = tree.root.findAll((node) => (node.type as unknown) === "card");
  expect(cards).toHaveLength(1);
  expect(cards[0].props.grouped).toBe(true);
  const rows = cards[0].findAll((node) => (node.type as unknown) === "pressable");
  expect(rows.map((row) => row.findAll((node) => (node.type as unknown) === "text")[0].props.children)).toEqual(["Asha", "Ravi"]);
  expect(rows.every((row) => row.props.emphasis && row.props.chevron)).toBe(true);
  expect(cards[0].findAll((node) => (node.type as unknown) === "separator")).toHaveLength(1);
  const texts = tree.root.findAll((node) => (node.type as unknown) === "text").map((node) => node.props.children);
  expect(texts).toContain("locked");
  // The 15pt sub-line: code and title-cased name, not an upper-case section label.
  expect(texts).toContain("GUJ026 · Gujarat Health System");
  const add = tree.root.findAll((node) => (node.type as unknown) === "button" && node.props.children === "addInterviewer");
  const settings = tree.root.findAll((node) => (node.type as unknown) === "button" && node.props.children === "settings");
  expect(add).toHaveLength(1);
  expect(add[0].props.link).toBeUndefined();
  expect(settings).toHaveLength(1);
  expect(settings[0].props.link).toBe(true);
  await act(async () => rows[1].props.onPress());
  expect(mockPush).toHaveBeenCalledWith({ pathname: "/unlock", params: { userId: "b" } });
});

it("shows an unlocked standalone profile's unsent records as an amber badge, with no prose hint", async () => {
  mockUnlocked = true;
  mockInterviews = 3;
  const device = { device_id: "d1", server: "https://live.example.org", project_id: "P", project_name: "P" };
  mockState = {
    ready: true, device, slot: "active", switchSlot: mockSwitchSlot,
    accounts: [{ user_id: "offline", name: "EngineBenchmark", standalone: true }, { user_id: "a", name: "Asha" }],
  };
  const tree = await render();
  const rows = tree.root.findAll((node) => (node.type as unknown) === "pressable");
  expect(rows[0].props.badge).toBe("syncUnsentScoped");
  expect(rows[1].props.badge).toBeUndefined();
  expect(mockOpenDb).toHaveBeenCalledWith("offline");
  expect(mockOpenDb).not.toHaveBeenCalledWith("a");
  const texts = tree.root.findAll((node) => (node.type as unknown) === "text").map((node) => node.props.children);
  expect(texts).not.toContain("standaloneAdoptHint");
});

it("shows no badge for a locked standalone profile: its store cannot be read", async () => {
  mockInterviews = 3;
  const device = { device_id: "d1", server: "https://live.example.org", project_id: "P", project_name: "P" };
  mockState = { ready: true, device, slot: "active", switchSlot: mockSwitchSlot, accounts: [{ user_id: "offline", name: "EngineBenchmark", standalone: true }] };
  const tree = await render();
  const rows = tree.root.findAll((node) => (node.type as unknown) === "pressable");
  expect(rows).toHaveLength(1);
  expect(rows[0].props.badge).toBeUndefined();
  expect(mockOpenDb).not.toHaveBeenCalled();
});
