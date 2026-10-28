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
  ActivityIndicator: "spinner", Platform: { OS: "android" }, Pressable: "pressable", Text: "text", View: "view",
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
jest.mock("../src/interviewerDb", () => ({ isUnlocked: () => false }));
jest.mock("../src/DemoPanel", () => ({ __esModule: true, default: () => null }));
jest.mock("../src/browserScreens", () => ({ WorkspaceScreen: () => null }));
jest.mock("../src/ui", () => {
  const R = jest.requireActual("react") as typeof React;
  return {
    Button: ({ label, onPress }: { label: string; onPress?: () => void }) => R.createElement("button", { onPress }, label),
    Screen: ({ children }: { children: ReactNode }) => R.createElement("main", null, children),
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
