import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

let mockRequired = true;
let mockBlocked: "maintenance" | "factor_setup_required" | undefined;
let mockAppError: string | undefined;
let mockRouteUser: string | undefined = "worker";
const mockClearError = jest.fn(() => { mockAppError = undefined; });
const mockReload = jest.fn(async () => undefined);
const mockReplace = jest.fn();
const mockAccept = jest.fn(async (_userId: string) => undefined);
const mockRefresh = jest.fn<Promise<unknown>, [string]>(async (_userId) => undefined);
jest.mock("expo-router", () => ({
  useGlobalSearchParams: () => ({ userId: mockRouteUser }),
  useRouter: () => ({ replace: mockReplace }),
}));
jest.mock("../src/AppState", () => ({
  useAppState: () => ({
    accounts: [
      { user_id: "worker", name: "Worker", terms_required: mockRequired, access_blocked: mockBlocked },
    ],
    reload: mockReload,
    error: mockAppError,
    clearError: mockClearError,
  }),
}));
jest.mock("../src/auth", () => ({
  acceptDeviceTerms: (userId: string) => mockAccept(userId),
  refreshAccessSummary: (userId: string) => mockRefresh(userId),
  signOut: jest.fn(),
}));
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    Button: ({
      label,
      onPress,
      disabled,
    }: {
      label: string;
      onPress: () => void;
      disabled: boolean;
    }) => ReactActual.createElement("button", { label, onPress, disabled }),
    Screen: ({ children }: { children: React.ReactNode }) =>
      ReactActual.createElement("screen", null, children),
    errorText: () => "error",
    useUiStyles: () => ({ text: {}, error: {} }),
  };
});
import NativeTermsGate from "../src/NativeTermsGate.native";
import { SignInRequiredError } from "../src/authErrors";

beforeEach(() => {
  mockRequired = true;
  mockBlocked = undefined;
  mockAppError = undefined;
  mockRouteUser = "worker";
  jest.clearAllMocks();
});

it("keeps the account home usable after a foreground refresh error", async () => {
  mockRequired = false;
  mockRouteUser = undefined;
  mockAppError = "server_unavailable";
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(<NativeTermsGate>accounts</NativeTermsGate>); });
  expect(tree.root.findAllByProps({ label: "retry" })).toHaveLength(0);
  expect(JSON.stringify(tree.toJSON())).toContain('"pointerEvents":"auto"');
  await act(async () => tree.unmount());
});

it("clears a prior provider error only after a confirmed access retry", async () => {
  mockRequired = false;
  mockAppError = "server_unavailable";
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(<NativeTermsGate>navigation</NativeTermsGate>); });
  await act(async () => { await tree.root.findByProps({ label: "retry" }).props.onPress(); });
  expect(mockClearError).not.toHaveBeenCalled();
  mockRefresh.mockResolvedValueOnce({ projects: [] });
  await act(async () => {
    await tree.root.findByProps({ label: "retry" }).props.onPress();
    tree.update(<NativeTermsGate>navigation</NativeTermsGate>);
  });
  expect(mockClearError).toHaveBeenCalledTimes(1);
  expect(tree.root.findAllByProps({ label: "retry" })).toHaveLength(0);
  await act(async () => tree.unmount());
});

it("shows the terms and continues with a settings refresh after successful acceptance", async () => {
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(
      <NativeTermsGate>
        <React.Fragment>navigation</React.Fragment>
      </NativeTermsGate>,
    );
  });
  expect(JSON.stringify(tree.toJSON())).toContain("termsConfidential");
  await act(async () => {
    await tree.root.findByProps({ label: "acceptTerms" }).props.onPress();
  });
  expect(mockAccept).toHaveBeenCalledWith("worker");
  expect(mockReload).toHaveBeenCalled();
  expect(mockReplace).toHaveBeenCalledWith({
    pathname: "/unlock",
    params: { userId: "worker", refresh: "1" },
  });
  await act(async () => tree.unmount());
});

it("keeps acceptance visible and does not navigate after a failed acceptance", async () => {
  mockAccept.mockRejectedValueOnce(new TypeError("offline"));
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<NativeTermsGate>navigation</NativeTermsGate>);
  });
  await act(async () => {
    await tree.root.findByProps({ label: "acceptTerms" }).props.onPress();
  });
  expect(mockReplace).not.toHaveBeenCalled();
  expect(JSON.stringify(tree.toJSON())).toContain("error");
  await act(async () => tree.unmount());
});

it("leaves normal navigation available when terms are accepted", async () => {
  mockRequired = false;
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<NativeTermsGate>navigation</NativeTermsGate>);
  });
  expect(tree.root.findAllByProps({ label: "acceptTerms" })).toHaveLength(0);
  await act(async () => tree.unmount());
});

it("blocks native navigation for a global maintenance gate and retries access", async () => {
  mockRequired = false;
  mockBlocked = "maintenance";
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<NativeTermsGate>navigation</NativeTermsGate>);
  });
  expect(JSON.stringify(tree.toJSON())).toContain("retry");
  await act(async () => {
    await tree.root.findByProps({ label: "retry" }).props.onPress();
  });
  expect(mockRefresh).toHaveBeenCalledWith("worker");
  await act(async () => tree.unmount());
});

it("returns home for sign-in when acceptance finds an ended session", async () => {
  mockAccept.mockRejectedValueOnce(new SignInRequiredError());
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<NativeTermsGate>navigation</NativeTermsGate>);
  });
  await act(async () => {
    await tree.root.findByProps({ label: "acceptTerms" }).props.onPress();
  });
  expect(mockReload).toHaveBeenCalled();
  expect(mockReplace).toHaveBeenCalledWith("/");
  await act(async () => tree.unmount());
});
