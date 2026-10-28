import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

const mockState: {
  pathname: string;
  userId?: string;
  accounts: Array<{ user_id: string; standalone?: boolean }>;
  slot?: "active" | "demo";
  standaloneAvailable: boolean;
} = { pathname: "/", accounts: [], standaloneAvailable: false };

jest.mock("expo-router", () => ({ usePathname: () => mockState.pathname }));
jest.mock("../src/AppState", () => ({ useAppState: () => mockState }));
jest.mock("../src/nativeShell/shellContext", () => ({ useShell: () => ({ userId: mockState.userId }) }));
jest.mock("../src/theme", () => ({
  typography: { subhead: { fontSize: 14, lineHeight: 20 } },
  useTheme: () => ({ ui: {
    warning: "#FEF3C7", warningBorder: "#B45309", warningForeground: "#3B2200",
    accent: "#E8F0FF", accentForeground: "#10233F", border: "#CBD5E1",
  } }),
}));

import { ModeBanner, resolveModeBanner } from "../src/nativeShell/ModeBanner";

const serverAccount = { user_id: "server", standalone: false };
const standaloneAccount = { user_id: "offline", standalone: true };

function renderBanner(): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => { tree = create(<ModeBanner />); });
  return tree;
}

function renderedText(tree: ReactTestRenderer): string {
  return tree.root.findAll((node) => typeof node.props.children === "string").map((node) => node.props.children).join(" ");
}

beforeEach(() => {
  mockState.pathname = "/";
  mockState.userId = undefined;
  mockState.accounts = [];
  mockState.slot = "active";
  mockState.standaloneAvailable = false;
});

describe("resolveModeBanner", () => {
  it("marks explicit demo pages as Demo without using connectivity", () => {
    expect(resolveModeBanner({ pathname: "/demo", accounts: [serverAccount], slot: "active", standaloneAvailable: false })).toBe("demo");
    expect(resolveModeBanner({ pathname: "/form", accounts: [serverAccount], slot: "demo", standaloneAvailable: false })).toBe("demo");
  });

  it("requires standalone availability for setup and standalone account routes", () => {
    expect(resolveModeBanner({ pathname: "/standalone-setup", accounts: [], slot: "active", standaloneAvailable: true })).toBe("standalone");
    expect(resolveModeBanner({ pathname: "/form", userId: "offline", accounts: [standaloneAccount], slot: "active", standaloneAvailable: true })).toBe("standalone");
    expect(resolveModeBanner({ pathname: "/unlock", userId: "offline", accounts: [standaloneAccount], slot: "active", standaloneAvailable: true })).toBe("standalone");
    expect(resolveModeBanner({ pathname: "/pin-setup", userId: "offline", accounts: [standaloneAccount], slot: "active", standaloneAvailable: true })).toBe("standalone");
  });

  it("does not label enrolled or blocked server routes as standalone", () => {
    expect(resolveModeBanner({ pathname: "/worklist", userId: "server", accounts: [serverAccount], slot: "active", standaloneAvailable: true })).toBeUndefined();
    expect(resolveModeBanner({ pathname: "/standalone-setup", accounts: [serverAccount], slot: "active", standaloneAvailable: false })).toBeUndefined();
    expect(resolveModeBanner({ pathname: "/form", userId: "offline", accounts: [standaloneAccount, serverAccount], slot: "active", standaloneAvailable: false })).toBeUndefined();
  });
});

describe("ModeBanner renderer", () => {
  it.each(["/standalone-setup", "/standalone", "/unlock", "/pin-setup", "/form", "/settings", "/"]) (
    "stays above the %s route content for standalone mode",
    (pathname) => {
      Object.assign(mockState, { pathname, userId: pathname === "/" ? undefined : "offline", accounts: [standaloneAccount], standaloneAvailable: true });
      expect(renderedText(renderBanner())).toContain("Standalone Mode - Server Disabled");
    },
  );

  it("labels a demo form with Demo Mode", () => {
    Object.assign(mockState, { pathname: "/form", userId: "demo-user", accounts: [{ user_id: "demo-user" }], slot: "demo" });
    expect(renderedText(renderBanner())).toContain("Demo Mode");
  });

  it("keeps Demo mode on shared Settings without an account parameter", () => {
    Object.assign(mockState, { pathname: "/settings", userId: undefined, accounts: [serverAccount], slot: "demo" });
    expect(renderedText(renderBanner())).toContain("Demo Mode");
  });
});
