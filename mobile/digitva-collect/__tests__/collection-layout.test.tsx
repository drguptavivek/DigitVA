import React from "react";
import { act, create } from "react-test-renderer";

const mockState = {
  ready: true,
  accounts: [
    { user_id: "worker", name: "Worker", collection_access: false },
    { user_id: "other", name: "Other", collection_access: true },
  ],
  activity: jest.fn(),
  reload: jest.fn(async () => undefined),
  lockNow: jest.fn(async () => undefined),
};
const mockRouter = { replace: jest.fn() };
const mockStackRendered = jest.fn();

jest.mock("expo-router", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    Stack: ({ screenLayout }: {
      screenLayout: (props: {
        children: React.ReactNode;
        route: { name: string; params: unknown };
      }) => React.ReactNode;
    }) => {
      mockStackRendered();
      return ReactActual.createElement("stack", null,
        screenLayout({
          children: ReactActual.createElement("home", null, "other account home"),
          route: { name: "index", params: { userId: "other" } },
        }),
        screenLayout({
          children: ReactActual.createElement("route", null, "collection case"),
          route: { name: "case", params: { userId: "worker" } },
        }),
      );
    },
    useGlobalSearchParams: () => ({ userId: "other" }),
    usePathname: () => "/",
    useRouter: () => mockRouter,
  };
});
jest.mock("../src/AppState", () => ({
  AppStateProvider: ({ children }: { children: React.ReactNode }) => children,
  useAppState: () => mockState,
}));
jest.mock("../src/NativeTermsGate", () => ({
  __esModule: true,
  default: ({ children }: { children: React.ReactNode }) => children,
}));
jest.mock("../src/theme", () => ({ useTheme: () => ({ mode: "light" }) }));
jest.mock("../src/auth", () => ({
  refreshAccessSummary: jest.fn(async () => undefined),
  signOut: jest.fn(async () => undefined),
}));
jest.mock("../src/interviewerDb", () => ({ isUnlocked: () => true }));
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    Button: ({ label }: { label: string }) => ReactActual.createElement("button", { label }),
    Screen: ({ children }: { children: React.ReactNode }) => ReactActual.createElement("screen", null, children),
    errorText: () => "accessError",
    useUiStyles: () => ({ text: {}, error: {} }),
  };
});
jest.mock("expo-screen-capture", () => ({ preventScreenCaptureAsync: jest.fn() }));
jest.mock("expo-status-bar", () => ({ StatusBar: () => null }));
jest.mock("react-native-safe-area-context", () => ({
  SafeAreaProvider: ({ children }: { children: React.ReactNode }) => children,
}));

import RootLayout from "../app/_layout";

it("keeps a role-only back-stack route gated while home uses another account", async () => {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<RootLayout />); });

  expect(mockStackRendered).toHaveBeenCalledTimes(1);
  const output = JSON.stringify(tree.toJSON());
  expect(output).toContain('"type":"stack"');
  expect(output).toContain('"type":"home"');
  expect(output).not.toContain('"type":"route"');
  expect(output).toContain("codingReviewPending");
  await act(async () => tree.unmount());
});
