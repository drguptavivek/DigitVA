/** Native Settings shows the enrolled server read-only and changes it only by re-enrolling. */
import React from "react";
import { act, create } from "react-test-renderer";

const mockRouter = { replace: jest.fn(), push: jest.fn(), back: jest.fn() };
const mockReload = jest.fn(async () => undefined);
const mockConfirm = jest.fn<Promise<void>, [unknown[], () => void]>(async () => undefined);
const mockReEnrol = jest.fn<Promise<void>, [unknown[]]>(async () => undefined);
const mockAccounts = [{ user_id: "a", name: "Asha" }];

jest.mock("react-native", () => ({ Platform: { OS: "android" }, Text: "text" }));
jest.mock("expo-router", () => ({ useRouter: () => mockRouter }));
jest.mock("expo-secure-store", () => ({ canUseBiometricAuthentication: () => false }));
jest.mock("../src/AppState", () => ({
  useAppState: () => ({
    device: { device_id: "d", server: "https://digitvav3.causeofdeathindia.com", project_id: "P", project_name: "Project" },
    accounts: mockAccounts,
    uiLocale: "en",
    chooseUiLocale: jest.fn(),
    lockNow: jest.fn(),
    reload: mockReload,
  }),
}));
jest.mock("../src/vault", () => ({ biometricEnabled: async () => false }));
jest.mock("../src/browserScreens", () => ({ SettingsScreen: () => null }));
jest.mock("../src/i18n", () => ({ t: (key: string) => key, UI_LOCALES: [] }));
jest.mock("../src/reEnrolConfirm", () => ({
  confirmReEnrol: (accounts: unknown[], onConfirmed: () => void) => mockConfirm(accounts, onConfirmed),
  reEnrolDevice: (accounts: unknown[]) => mockReEnrol(accounts),
}));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    Button: (props: { label: string; onPress: () => void }) => ReactActual.createElement("button", props),
    Screen: ({ children }: { children: React.ReactNode }) => ReactActual.createElement("screen", null, children),
    useUiStyles: () => ({ text: {}, muted: {}, error: {} }),
  };
});

import Settings from "../app/settings";

async function render() {
  let tree: ReturnType<typeof create>;
  await act(async () => {
    tree = create(<Settings />);
  });
  return tree!;
}

it("shows the enrolled server", async () => {
  const tree = await render();
  const texts = tree.root.findAllByType("text" as never).map((node) => node.props.children);
  expect(texts).toContain("enrolledServer");
  expect(texts).toContain("https://digitvav3.causeofdeathindia.com");
});

it("re-enrols through the unsent-work check, then goes to the enrol screen", async () => {
  const tree = await render();
  const button = tree.root.findAll((node) => node.props.label === "reEnrol")[0];
  expect(button).toBeDefined();
  await act(async () => button.props.onPress());
  expect(mockConfirm).toHaveBeenCalledWith(mockAccounts, expect.any(Function));
  expect(mockReEnrol).not.toHaveBeenCalled();

  await act(async () => mockConfirm.mock.calls[0][1]());
  expect(mockReEnrol).toHaveBeenCalledWith(mockAccounts);
  expect(mockReload).toHaveBeenCalled();
  expect(mockRouter.replace).toHaveBeenCalledWith("/enrol");
});
