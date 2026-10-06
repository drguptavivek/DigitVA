import React from "react";
import { act, create } from "react-test-renderer";
import { AppState } from "react-native";

let mockUnlocked = true;
let mockState: {
  accounts: Array<{ user_id: string; name: string; collection_access: boolean; registered_deaths_access: boolean }>;
  lockVersion: number;
  lockNow: () => Promise<void>;
  reload: () => Promise<void>;
};
const mockRouter = { replace: jest.fn(), push: jest.fn() };
const mockLoad = jest.fn();

jest.mock("expo-router", () => ({
  useRouter: () => mockRouter,
  useFocusEffect: (callback: () => void | (() => void)) => {
    const ReactActual = jest.requireActual("react") as typeof React;
    ReactActual.useEffect(() => {
      const cleanup = callback();
      return cleanup;
    }, [callback]);
  },
}));
jest.mock("../src/AppState", () => ({ useAppState: () => mockState }));
jest.mock("../src/auth", () => ({ signOut: jest.fn(async () => undefined) }));
jest.mock("../src/deathRegistrationApi", () => ({ getNativeRegisteredDeaths: (...args: unknown[]) => mockLoad(...args) }));
jest.mock("../src/interviewerDb", () => ({ isUnlocked: () => mockUnlocked }));
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    Button: ({ label, onPress }: { label: string; onPress: () => void }) =>
      ReactActual.createElement("button", { label, onPress }),
    Screen: ({ children }: { children: React.ReactNode }) => ReactActual.createElement("screen", null, children),
    useUiStyles: () => ({ text: {}, muted: {}, error: {}, card: {} }),
  };
});

import RegisteredDeaths from "../src/nativeRoutes/RegisteredDeaths";

beforeEach(() => {
  Object.defineProperty(AppState, "currentState", { configurable: true, value: "active" });
  mockUnlocked = true;
  mockRouter.replace.mockClear();
  mockRouter.push.mockClear();
  mockLoad.mockReset();
  mockState = {
    accounts: [{ user_id: "u1", name: "Worker", collection_access: false, registered_deaths_access: true }],
    lockVersion: 0,
    lockNow: jest.fn(async () => { mockUnlocked = false; mockState.lockVersion += 1; }),
    reload: jest.fn(async () => undefined),
  };
});

it("discards a pending page when the reporter locks and never renders its PII", async () => {
  let resolvePage!: (page: { deaths: Array<{ death_id: string; unique_id: string; deceased_name: string }>; next_cursor: string | null }) => void;
  mockLoad.mockReturnValue(new Promise((resolve) => { resolvePage = resolve; }));
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<RegisteredDeaths userId="u1" registeredMine={false} />); });
  expect(mockLoad).toHaveBeenCalledTimes(1);

  await act(async () => {
    await mockState.lockNow();
    tree.update(<RegisteredDeaths userId="u1" registeredMine={false} />);
  });
  await act(async () => {
    resolvePage({ deaths: [{ death_id: "d1", unique_id: "U1", deceased_name: "Private Name" }], next_cursor: "next" });
    await Promise.resolve();
  });

  expect(JSON.stringify(tree.toJSON())).not.toContain("Private Name");
  expect(mockLoad).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());
});

it("opens an own-list correction with its bounded page cursor and source", async () => {
  mockLoad
    .mockResolvedValueOnce({ deaths: [], next_cursor: "cursor-1" })
    .mockResolvedValueOnce({ deaths: [{ death_id: "d1", unique_id: "U1", deceased_name: "Asha" }], next_cursor: null });
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<RegisteredDeaths userId="u1" registeredMine={true} />); });
  await act(async () => { await Promise.resolve(); });
  await act(async () => tree.root.findByProps({ label: "loadMore" }).props.onPress());
  await act(async () => { await Promise.resolve(); });
  await act(async () => tree.root.findByProps({ label: "editRegistration" }).props.onPress());
  expect(mockRouter.push).toHaveBeenCalledWith({
    pathname: "/register",
    params: { userId: "u1", deathId: "d1", registrationSource: "mine", registrationCursor: "cursor-1" },
  });
  expect(mockLoad).toHaveBeenCalledTimes(2);
  await act(async () => tree.unmount());
});

it("hides one reporter's rows immediately and ignores its pending page after an account switch", async () => {
  let resolveFirst!: (page: { deaths: Array<{ death_id: string; unique_id: string; deceased_name: string }>; next_cursor: string | null }) => void;
  let resolveSecond!: (page: { deaths: Array<{ death_id: string; unique_id: string; deceased_name: string }>; next_cursor: string | null }) => void;
  mockLoad
    .mockReturnValueOnce(new Promise((resolve) => { resolveFirst = resolve; }))
    .mockReturnValueOnce(new Promise((resolve) => { resolveSecond = resolve; }));
  mockState.accounts.push({ user_id: "u2", name: "Other worker", collection_access: false, registered_deaths_access: true });
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<RegisteredDeaths userId="u1" registeredMine={false} />); });
  expect(mockLoad).toHaveBeenCalledTimes(1);

  await act(async () => tree.update(<RegisteredDeaths userId="u2" registeredMine={false} />));
  expect(JSON.stringify(tree.toJSON())).not.toContain("First worker's death");
  expect(mockLoad).toHaveBeenCalledTimes(2);

  await act(async () => {
    resolveFirst({ deaths: [{ death_id: "d1", unique_id: "U1", deceased_name: "First worker's death" }], next_cursor: "old-cursor" });
    await Promise.resolve();
  });
  expect(JSON.stringify(tree.toJSON())).not.toContain("First worker's death");

  await act(async () => {
    resolveSecond({ deaths: [{ death_id: "d2", unique_id: "U2", deceased_name: "Second worker's death" }], next_cursor: null });
    await Promise.resolve();
  });
  expect(JSON.stringify(tree.toJSON())).toContain("Second worker's death");
  expect(JSON.stringify(tree.toJSON())).not.toContain("First worker's death");
  await act(async () => tree.unmount());
});
