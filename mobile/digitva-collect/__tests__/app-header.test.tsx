/** @jest-environment jsdom */
import React, { act } from "react";

let mockPathname = "/coding";
let mockParams: Record<string, string> = {};
let mockWidth = 1280;
let mockBootstrap: unknown;
const mockLogout = jest.fn(async () => undefined);
const mockRouter = { push: jest.fn(), replace: jest.fn() };

jest.mock("expo-router", () => ({ usePathname: () => mockPathname, useRouter: () => mockRouter, useGlobalSearchParams: () => mockParams }));
jest.mock("../src/AppState", () => ({ useAppState: () => ({ bootstrap: mockBootstrap, logout: mockLogout }) }));
jest.mock("react-native", () => {
  const actual = jest.requireActual("react-native");
  Object.defineProperty(actual, "useWindowDimensions", { value: () => ({ width: mockWidth, height: 900, scale: 1, fontScale: 1 }), configurable: true });
  return actual;
});
jest.mock("../src/preferences", () => ({ ...jest.requireActual("../src/preferences"), setUiTheme: jest.fn().mockResolvedValue(undefined) }));

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createRoot } = require("react-dom/client") as { createRoot: (el: Element) => { render(node: React.ReactNode): void; unmount(): void } };
import AppHeader, { BottomTabs } from "../src/web/AppHeader.web";
import { activeTab, showBottomTabs, tabsThatFit } from "../src/web/navTabs";
import { browserSessionStore } from "../src/workspace/viewState";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const boot = (roles: string[]) => ({ user: { user_id: "u1", name: "Test Admin" }, access: { roles }, capabilities: { intake: false, registerDeath: false, registeredDeaths: false, supervision: false } });
let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const mount = () => act(() => { root.render(<AppHeader />); });
const link = (href: string) => host.querySelector<HTMLAnchorElement>(`a[href='${href}']`)!;
const click = (el: Element, init: MouseEventInit = {}) => {
  const event = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0, ...init });
  act(() => { el.dispatchEvent(event); });
  return event;
};

beforeEach(() => {
  mockPathname = "/coding";
  mockParams = {};
  mockWidth = 1280;
  mockBootstrap = boot(["coder"]);
  mockRouter.push.mockClear();
  mockLogout.mockClear();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => { act(() => root.unmount()); host.remove(); });

test("one banner with a Main navigation, the coder link, Help in a new tab and the account menu", () => {
  mount();
  expect(host.querySelectorAll("header")).toHaveLength(1);
  expect(host.querySelector("nav")?.getAttribute("aria-label")).toBe("Main");
  expect(link("/app/coding").textContent).toBe("VA Coding");
  expect(link("/app/coding").getAttribute("aria-current")).toBe("page");
  expect(host.querySelector("a[href='/app/reviewing']")).toBeNull();
  const help = link("/help");
  expect([help.target, help.rel]).toEqual(["_blank", "noopener"]);
  expect(host.querySelector("button[aria-label='Account menu, Test Admin']")).not.toBeNull();
  expect(link("/app/").getAttribute("aria-label")).toBe("DigitVA home");
  // The full logo image is the brand: a plate with the whole wordmark (never a cropped square), no text beside it.
  const plate = link("/app/").querySelector("span[aria-hidden='true']") as HTMLElement | null;
  expect(plate).not.toBeNull();
  // (jsdom drops the `background` shorthand with a url(), so the image itself is covered by the browser check.)
  expect(parseInt(plate!.style.width, 10)).toBeGreaterThan(parseInt(plate!.style.height, 10) * 2.5);
});

test("a reviewer gets VA Review, a collector the reported-deaths links, from the shell's role data", () => {
  mockBootstrap = boot(["reviewer"]);
  mount();
  expect(link("/app/reviewing").textContent).toBe("VA Review");
  expect(host.querySelector("a[href='/app/coding']")).toBeNull();
  mockBootstrap = { ...boot([]), capabilities: { intake: true, registerDeath: true, registeredDeaths: false, supervision: false } };
  mount();
  expect(link("/app/collection")).not.toBeNull();
  expect(link("/app/death-registration")).not.toBeNull();
});

test.each(["/sign-in", "/enrol", "/unlock", "/pin-setup", "/register"])("is absent on the pre-login route %s", (path) => {
  mockPathname = path;
  mount();
  expect(host.querySelector("header")).toBeNull();
});

test("is absent while nobody is signed in and present on the queue, home and workspace routes", () => {
  mockBootstrap = undefined;
  mount();
  expect(host.querySelector("header")).toBeNull();
  mockBootstrap = boot(["coder"]);
  for (const path of ["/coding", "/", "/workspace"]) {
    mockPathname = path;
    mount();
    expect(host.querySelectorAll("header")).toHaveLength(1);
  }
});

test("left click navigates in-app, modified and middle clicks fall through, the logo goes home", () => {
  mount();
  expect(click(link("/app/coding")).defaultPrevented).toBe(true);
  expect(mockRouter.push).toHaveBeenLastCalledWith("/coding");
  expect(click(link("/app/")).defaultPrevented).toBe(true);
  expect(mockRouter.push).toHaveBeenLastCalledWith("/");
  mockRouter.push.mockClear();
  expect(click(link("/app/coding"), { ctrlKey: true }).defaultPrevented).toBe(false);
  expect(click(link("/app/coding"), { button: 1 }).defaultPrevented).toBe(false);
  expect(click(link("/help")).defaultPrevented).toBe(false);
  expect(mockRouter.push).not.toHaveBeenCalled();
});

test("signing out drops every pinned scroll offset before the session ends", async () => {
  const store = browserSessionStore()!;
  store.setItem("digitva.scroll.v1:coding:sid-1:one", "120");
  mount();
  act(() => { host.querySelector<HTMLButtonElement>("button[aria-label^='Account menu']")!.click(); });
  const signOut = Array.from(host.querySelectorAll<HTMLElement>("[role='menuitem']")).find((item) => item.textContent === "Sign out")!;
  await act(async () => { signOut.click(); });
  expect(mockLogout).toHaveBeenCalledTimes(1);
  expect(store.getItem("digitva.scroll.v1:coding:sid-1:one")).toBeNull();
});

const mountAll = () => act(() => { root.render(<><AppHeader /><BottomTabs /></>); });
const flags = ["/coding", "/reviewing", "/collection", "/worklist", "/death-registration", "/supervision", "/organization", "/settings"];

test("tabs: the current route carries aria-current and the 3px underline, and moves with the route", () => {
  mockBootstrap = boot(["coder", "reviewer"]);
  mount();
  expect(link("/app/coding").getAttribute("aria-current")).toBe("page");
  expect(link("/app/coding").querySelector("span[aria-hidden]:empty")).not.toBeNull();
  expect(link("/app/reviewing").getAttribute("aria-current")).toBeNull();
  expect(link("/app/reviewing").querySelector("span[aria-hidden]:empty")).toBeNull();
  mockPathname = "/reviewing";
  mount();
  expect(link("/app/reviewing").getAttribute("aria-current")).toBe("page");
  expect(link("/app/coding").getAttribute("aria-current")).toBeNull();
});

test("tabs: /workspace belongs to Coding or Review by its mode", () => {
  mockBootstrap = boot(["coder", "reviewer"]);
  mockPathname = "/workspace";
  mockParams = { mode: "reviewing", vaSid: "s1" };
  mount();
  expect(link("/app/reviewing").getAttribute("aria-current")).toBe("page");
  mockParams = { mode: "coding", vaSid: "s1" };
  mount();
  expect(link("/app/coding").getAttribute("aria-current")).toBe("page");
  expect(activeTab("/worklist")).toBe("/collection");
  expect(activeTab("/supervision/case")).toBe("/supervision");
  expect(activeTab("/")).toBeUndefined();
});

test("tabs: icons are hidden from assistive tech and every tab keeps its visible label, in DOM (tab) order", () => {
  mockBootstrap = boot(["coder", "reviewer", "interview_supervisor"]);
  mount();
  const nav = host.querySelector("nav[aria-label='Main']")!;
  expect(Array.from(nav.querySelectorAll("svg")).every((svg) => svg.getAttribute("aria-hidden") === "true")).toBe(true);
  expect(Array.from(nav.querySelectorAll("a")).map((a) => a.textContent)).toEqual(["VA Coding", "VA Review", "supervisionTitle", "navOrganization", "Help"].map((x) => x === "supervisionTitle" ? "Supervision" : x === "navOrganization" ? "My organization" : x));
});

test("tabs: the ones that do not fit go into a More menu that opens and closes", () => {
  mockBootstrap = boot(["coder", "reviewer", "interview_supervisor"]);
  mockWidth = 768;
  mount();
  const more = Array.from(host.querySelectorAll<HTMLButtonElement>("nav button")).find((b) => b.textContent === "More")!;
  expect(more.getAttribute("aria-expanded")).toBe("false");
  act(() => more.click());
  const items = Array.from(host.querySelectorAll("[role='menuitem']")).map((el) => el.textContent);
  expect(items).toContain("My organization");
  expect(items).toContain("Settings");
  act(() => { document.activeElement?.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
  expect(host.querySelector("[role='menu']")).toBeNull();
  expect(tabsThatFit(["a", "b"], 10_000, 0)).toBe(2);
  expect(tabsThatFit(["a", "b"], 10, 0)).toBe(0);
});

test.each([
  ["/", {}, true], ["/coding", {}, true], ["/reviewing", {}, true], ["/collection", {}, true], ["/worklist", {}, true], ["/supervision", {}, true],
  ["/organization", {}, true], ["/settings", {}, true], ["/workspace", { mode: "coding" }, true],
  ["/workspace", { vaSid: "s1", mode: "coding" }, false], ["/workspace", { vaSid: ["s1"] }, false],
  ["/case", {}, false], ["/form", {}, false], ["/interview", {}, false],
  ["/sign-in", {}, false], ["/enrol", {}, false], ["/unlock", {}, false], ["/pin-setup", {}, false], ["/register", {}, false],
])("showBottomTabs(%s, %j) = %s", (path, params, expected) => {
  expect(showBottomTabs(path, params)).toBe(expected);
});

test("phone: bottom bar on the queue and home, a compact header without the tab row, none inside a case or before sign-in", () => {
  mockBootstrap = boot(["coder", "reviewer"]);
  mockWidth = 375;
  mountAll();
  expect(host.querySelector("nav[aria-label='Main']")).toBeNull();
  const bar = host.querySelector("nav[aria-label='Primary']")!;
  expect(Array.from(bar.querySelectorAll("a,button")).map((el) => el.textContent)).toEqual(["Coding", "Review", "Help", "More"]);
  expect(bar.querySelector("a[href='/app/coding']")!.getAttribute("aria-current")).toBe("page");
  expect(bar.querySelector<HTMLAnchorElement>("a[href='/help']")!.target).toBe("_blank");
  mockPathname = "/";
  mountAll();
  expect(host.querySelector("nav[aria-label='Primary']")).not.toBeNull();
  mockPathname = "/workspace";
  mockParams = { vaSid: "s1", mode: "coding" };
  mountAll();
  expect(host.querySelector("nav[aria-label='Primary']")).toBeNull();
  expect(host.querySelectorAll("header")).toHaveLength(1);
  mockPathname = "/sign-in";
  mountAll();
  expect(host.querySelector("nav[aria-label='Primary']")).toBeNull();
});

test("phone: in-app click on a bottom tab navigates without leaving, and the More sheet closes on Escape and outside press", () => {
  mockBootstrap = boot(["coder", "reviewer", "interview_supervisor"]);
  mockWidth = 375;
  mockPathname = "/";
  mountAll();
  expect(click(link("/app/reviewing")).defaultPrevented).toBe(true);
  expect(mockRouter.push).toHaveBeenLastCalledWith("/reviewing");
  const more = () => Array.from(host.querySelectorAll<HTMLButtonElement>("nav[aria-label='Primary'] button")).find((b) => b.textContent === "More")!;
  act(() => more().click());
  const labels = Array.from(host.querySelectorAll("[role='menuitem']")).map((el) => el.textContent);
  expect(labels).toEqual(["Supervision", "My organization", "Settings", "Profile", "Sign out"]);
  act(() => { document.activeElement?.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
  expect(host.querySelector("[role='menu']")).toBeNull();
  act(() => more().click());
  expect(host.querySelector("[role='menu']")).not.toBeNull();
  act(() => { document.body.dispatchEvent(new Event("pointerdown", { bubbles: true })); });
  expect(host.querySelector("[role='menu']")).toBeNull();
});

// pointerdown, mousedown, pointerup, mouseup, click: what a browser sends for one press.
const realClick = (el: Element) => act(() => {
  for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
    const Ctor = type.startsWith("pointer") && typeof PointerEvent !== "undefined" ? PointerEvent : MouseEvent;
    el.dispatchEvent(new Ctor(type, { bubbles: true, cancelable: true, button: 0 }));
  }
});

test("phone: a real pointer sequence opens the More sheet, reaches Sign out, and toggles it shut again", () => {
  mockWidth = 375;
  mockPathname = "/";
  mountAll();
  const more = () => Array.from(host.querySelectorAll<HTMLButtonElement>("nav[aria-label='Primary'] button")).find((b) => b.textContent === "More")!;
  realClick(more());
  expect(host.querySelector("[role='menu']")).not.toBeNull();
  realClick(more()); // the trigger is inside: its pointerdown must not close the sheet only for its click to reopen it
  expect(host.querySelector("[role='menu']")).toBeNull();
  realClick(more());
  realClick(Array.from(host.querySelectorAll("[role='menuitem']")).find((el) => el.textContent === "Sign out")!);
  expect(mockLogout).toHaveBeenCalledTimes(1);
});

test("phone: the bottom bar is hidden while the on-screen keyboard is open", () => {
  const listeners: Array<() => void> = [];
  const viewport = { height: 800, width: 375, addEventListener: (_: string, fn: () => void) => listeners.push(fn), removeEventListener: jest.fn() };
  Object.defineProperty(window, "visualViewport", { value: viewport, configurable: true });
  Object.defineProperty(window, "innerHeight", { value: 800, configurable: true });
  mockWidth = 375;
  mockPathname = "/";
  mountAll();
  expect(host.querySelector("nav[aria-label='Primary']")).not.toBeNull();
  viewport.height = 450;
  act(() => listeners.forEach((fn) => fn()));
  expect(host.querySelector("nav[aria-label='Primary']")).toBeNull();
  viewport.height = 800;
  act(() => listeners.forEach((fn) => fn()));
  expect(host.querySelector("nav[aria-label='Primary']")).not.toBeNull();
  Object.defineProperty(window, "visualViewport", { value: undefined, configurable: true });
});

test("desktop: no bottom bar", () => {
  mountAll();
  expect(host.querySelector("nav[aria-label='Primary']")).toBeNull();
  expect(flags.length).toBe(8);
});
