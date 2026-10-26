/** @jest-environment jsdom */
import React, { act } from "react";

let mockPathname = "/coding";
let mockParams: Record<string, string> = {};
let mockWidth = 1280;
let mockBootstrap: unknown;
const mockLogout = jest.fn(async () => undefined);
const mockRouter = { push: jest.fn(), replace: jest.fn() };

let mockFocused = true;
jest.mock("expo-router", () => ({ usePathname: () => mockPathname, useRouter: () => mockRouter, useGlobalSearchParams: () => mockParams, useIsFocused: () => mockFocused }));
jest.mock("../src/AppState", () => ({ useAppState: () => ({ bootstrap: mockBootstrap, logout: mockLogout }) }));
jest.mock("react-native", () => {
  const actual = jest.requireActual("react-native");
  Object.defineProperty(actual, "useWindowDimensions", { value: () => ({ width: mockWidth, height: 900, scale: 1, fontScale: 1 }), configurable: true });
  return actual;
});
jest.mock("../src/preferences", () => ({ ...jest.requireActual("../src/preferences"), setUiTheme: jest.fn().mockResolvedValue(undefined) }));

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createRoot } = require("react-dom/client") as { createRoot: (el: Element) => { render(node: React.ReactNode): void; unmount(): void } };
import AppHeader, { AppHeaderBar, BottomTabs, HeaderHelpSlot } from "../src/web/AppHeader.web";
import { setUiLocale } from "../src/i18n";
import { activeTab, showBottomTabs } from "../src/web/navTabs";
import { registerNavigationGuard } from "../src/web/navigationGuard";
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
  mockFocused = true;
  mockBootstrap = boot(["coder"]);
  mockRouter.push.mockClear();
  mockLogout.mockClear();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => { act(() => root.unmount()); host.remove(); });

test("one banner: Help in a new tab and the account menu, and no top navigation; the logo is the sidebar's, not the header's", () => {
  mount();
  expect(host.querySelectorAll("header")).toHaveLength(1);
  expect(link("/help")).not.toBeNull();
  // Wide screens navigate from the left sidebar only (common.tsx): the header carries no tabs at all.
  expect(host.querySelector("nav")).toBeNull();
  expect(host.querySelector("a[href='/app/coding']")).toBeNull();
  const help = link("/help");
  expect([help.target, help.rel]).toEqual(["_blank", "noopener"]);
  expect(host.querySelector("button[aria-label='Account menu, Test Admin']")).not.toBeNull();
  // Wide with the left sidebar (which carries the logo): one logo on screen.
  expect(host.querySelector("a[href='/app/']")).toBeNull();
});

test.each([[900, "/coding", {}], [1280, "/coding", {}]])("the header has no logo beside the full sidebar (width %d, %s)", (width, path, params) => {
  mockWidth = width;
  mockPathname = path;
  mockParams = params;
  mount();
  expect(host.querySelector("a[href='/app/']")).toBeNull();
  expect(link("/help")).not.toBeNull();
});

test.each([[899, "/coding", {}], [800, "/coding", {}], [1280, "/workspace", { vaSid: "s1", mode: "coding" }], [1280, "/form", {}], [1280, "/worklist", {}]])(
  "the header keeps the logo as the home link where no full sidebar shows (width %d, %s)", (width, path, params) => {
    mockWidth = width;
    mockPathname = path;
    mockParams = params;
    mount();
    expect(link("/app/").getAttribute("aria-label")).toBe("DigitVA home");
    // The full logo image is the brand: a plate with the whole wordmark (never a cropped square), no text beside it.
    const plate = link("/app/").querySelector("span[aria-hidden='true']") as HTMLElement | null;
    expect(plate).not.toBeNull();
    // (jsdom drops the `background` shorthand with a url(), so the image itself is covered by the browser check.)
    expect(parseInt(plate!.style.width, 10)).toBeGreaterThan(parseInt(plate!.style.height, 10) * 2.5);
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

test("the logo goes home in-app on a left click; modified and middle clicks and Help fall through", () => {
  mockWidth = 800; // no full sidebar, so the header carries the logo
  mount();
  expect(click(link("/app/")).defaultPrevented).toBe(true);
  expect(mockRouter.push).toHaveBeenLastCalledWith("/");
  mockRouter.push.mockClear();
  expect(click(link("/app/"), { ctrlKey: true }).defaultPrevented).toBe(false);
  expect(click(link("/app/"), { button: 1 }).defaultPrevented).toBe(false);
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
const bar = () => host.querySelector("nav[aria-label='Primary']");
const barLabels = () => Array.from(bar()!.querySelectorAll("a,button")).map((el) => el.textContent);
const moreButton = () => Array.from(host.querySelectorAll<HTMLButtonElement>("nav[aria-label='Primary'] button")).find((b) => b.textContent === "More")!;
const everything = () => ({
  user: { user_id: "u1", name: "Test Admin" },
  access: { roles: ["coder", "reviewer", "data_manager"], is_admin: true, account: { mentor: { member: true } } },
  capabilities: { intake: true, registerDeath: true, registeredDeaths: true, supervision: true },
});

test("bottom bar: the current route carries aria-current and the 3px top line, and moves with the route", () => {
  mockBootstrap = boot(["coder", "reviewer"]);
  mockWidth = 375;
  mountAll();
  const coding = () => bar()!.querySelector("a[href='/app/coding']")!;
  const reviewing = () => bar()!.querySelector("a[href='/app/reviewing']")!;
  expect(coding().getAttribute("aria-current")).toBe("page");
  expect(coding().querySelector("span[aria-hidden]:empty")).not.toBeNull();
  expect(reviewing().getAttribute("aria-current")).toBeNull();
  expect(reviewing().querySelector("span[aria-hidden]:empty")).toBeNull();
  mockPathname = "/reviewing";
  mountAll();
  expect(reviewing().getAttribute("aria-current")).toBe("page");
  expect(coding().getAttribute("aria-current")).toBeNull();
});

test("active item: Home on /, Deaths for both death-registration views, /workspace by its mode", () => {
  expect(activeTab("/")).toBe("/");
  expect(activeTab("/death-registration")).toBe("/death-registration");
  expect(activeTab("/death-registration", { view: "mine" } as never)).toBe("/death-registration");
  expect(activeTab("/workspace", { mode: "reviewing", vaSid: "s1" })).toBe("/reviewing");
  expect(activeTab("/workspace", { mode: "coding", vaSid: "s1" })).toBe("/coding");
  expect(activeTab("/workspace")).toBeUndefined();
  expect(activeTab("/worklist")).toBe("/collection");
  expect(activeTab("/interview", { deathId: "d1" } as never)).toBe("/collection");
  expect(activeTab("/case")).toBe("/collection");
  expect(activeTab("/supervision/case")).toBeUndefined();
  mockBootstrap = everything();
  mockWidth = 375;
  for (const params of [{}, { view: "mine" }] as Record<string, string>[]) {
    mockPathname = "/death-registration";
    mockParams = params;
    mountAll();
    expect(bar()!.querySelector("a[href='/app/death-registration?view=mine']")!.getAttribute("aria-current")).toBe("page");
    expect(bar()!.querySelectorAll("[aria-current='page']")).toHaveLength(1);
  }
  mockPathname = "/";
  mockParams = {};
  mountAll();
  expect(bar()!.querySelector("a[href='/app/']")!.getAttribute("aria-current")).toBe("page");
});

test("bottom bar: the owner's labels and order, icons hidden from assistive tech", () => {
  mockBootstrap = everything();
  mockWidth = 375;
  mountAll();
  expect(barLabels()).toEqual(["Home", "Deaths", "VA Interview", "VA Code", "VA Review", "Statistics", "More"]);
  expect(Array.from(bar()!.querySelectorAll("svg")).every((svg) => svg.getAttribute("aria-hidden") === "true")).toBe(true);
  expect(bar()!.querySelector("a[href='/app/statistics']")!.textContent).toBe("Statistics");
  act(() => moreButton().click());
  const labels = Array.from(host.querySelectorAll("[role='menuitem']")).map((el) => el.textContent);
  expect(labels).toEqual(["Organization", "Users", "Settings", "Website", "Data management", "Mentoring Institution", "Admin console", "Sign out"]);
  const website = host.querySelector<HTMLAnchorElement>("[role='menuitem'][href='/vaindex']")!;
  expect([website.target, website.rel]).toEqual(["_blank", "noopener"]);
  expect(host.querySelector("[role='menuitem'][href='/app/organization']")).not.toBeNull();
  expect(host.querySelector("[role='menuitem'][href='/admin/']")).not.toBeNull();
});

test("a screen's help trigger replaces the Help link; the top tab rules are gone", () => {
  mount();
  const css = host.querySelector("style")!.textContent!;
  expect(css).toContain("#digitva-app-header:has(#digitva-help-trigger) .dva-help-link{display:none!important}");
  expect(link("/help").className).toContain("dva-help-link");
  expect(css).not.toContain("dva-main-nav");
  expect(css).not.toContain("digitva-sidebar");
});

test("phone-width text fields are 16px so iOS Safari does not zoom the page on focus", () => {
  mount();
  const css = host.querySelector("style")!.textContent!;
  expect(css).toContain("@media (max-width:767px){input,textarea,select{font-size:16px!important}}");
});

test("on /interview the root header renders no bar; the screen's own bar is in normal flow, so it scrolls away", () => {
  // Every other route keeps the one sticky header.
  mockPathname = "/collection";
  mount();
  expect(host.querySelector<HTMLElement>("header")!.style.position).toBe("sticky");
  for (const path of ["/interview", "/training/interview/form"]) {
    mockPathname = path;
    mount();
    expect(host.querySelector("header")).toBeNull();
    act(() => { root.render(<><AppHeader /><AppHeaderBar sticky={false} /></>); });
    expect(host.querySelectorAll("header")).toHaveLength(1);
    expect(host.querySelector<HTMLElement>("header")!.style.position).toBe("static");
    expect(host.querySelector("button[aria-label='Account menu, Test Admin']")).not.toBeNull();
  }
});

test("HeaderHelpSlot follows the bar when it moves into the interview's scroller", () => {
  const render = (inHeader: boolean) => <button type="button" id="digitva-help-trigger">{inHeader ? "in header" : "inline"}</button>;
  act(() => { root.render(<><AppHeader /><main><HeaderHelpSlot>{render}</HeaderHelpSlot></main></>); });
  expect(host.querySelector("header #digitva-help-trigger")).not.toBeNull();
  mockPathname = "/interview";
  act(() => { root.render(<><AppHeader /><main><AppHeaderBar sticky={false} /><HeaderHelpSlot>{render}</HeaderHelpSlot></main></>); });
  expect(host.querySelectorAll("header")).toHaveLength(1);
  expect(host.querySelector("main header #digitva-help-trigger")!.textContent).toBe("in header");
});

test("HeaderHelpSlot renders into the header beside the account menu, and inline where there is no header", () => {
  const render = (inHeader: boolean) => <button type="button" id="digitva-help-trigger">{inHeader ? "in header" : "inline"}</button>;
  act(() => { root.render(<><AppHeader /><main><HeaderHelpSlot>{render}</HeaderHelpSlot></main></>); });
  const trigger = host.querySelector("#digitva-help-trigger")!;
  expect(trigger.textContent).toBe("in header");
  expect(host.querySelector("header")!.contains(trigger)).toBe(true);
  expect(host.querySelector("main")!.contains(trigger)).toBe(false);
  mockFocused = false; // an earlier screen the Stack keeps mounted never claims the slot
  act(() => { root.render(<><AppHeader /><main><HeaderHelpSlot>{render}</HeaderHelpSlot></main></>); });
  expect(host.querySelector("header #digitva-help-trigger")).toBeNull();
  expect(host.querySelector("main #digitva-help-trigger")!.textContent).toBe("inline");
  mockFocused = true;
  mockPathname = "/sign-in"; // headerless route
  act(() => { root.render(<main><HeaderHelpSlot>{render}</HeaderHelpSlot></main>); });
  expect(host.querySelector("main #digitva-help-trigger")!.textContent).toBe("inline");
});

test.each([
  ["/", {}, true], ["/coding", {}, true], ["/reviewing", {}, true], ["/collection", {}, true], ["/worklist", {}, true], ["/supervision", {}, true],
  ["/organization", {}, true], ["/settings", {}, true], ["/workspace", { mode: "coding" }, true],
  ["/workspace", { vaSid: "s1", mode: "coding" }, false], ["/workspace", { vaSid: ["s1"] }, false],
  ["/case", {}, true], ["/form", {}, true], ["/interview", {}, true], ["/death-registration", {}, true], ["/revision", {}, true],
  ["/sign-in", {}, false], ["/enrol", {}, false], ["/unlock", {}, false], ["/pin-setup", {}, false], ["/register", {}, false],
])("showBottomTabs(%s, %j) = %s", (path, params, expected) => {
  expect(showBottomTabs(path, params)).toBe(expected);
});

test("phone: bottom bar on the queue and home, a compact header with Help, none inside a case or before sign-in", () => {
  mockBootstrap = boot(["coder", "reviewer"]);
  mockWidth = 375;
  mountAll();
  expect(host.querySelector("nav[aria-label='Main']")).toBeNull();
  expect(barLabels()).toEqual(["Home", "VA Code", "VA Review", "Statistics", "More"]);
  expect(bar()!.querySelector("a[href='/app/coding']")!.getAttribute("aria-current")).toBe("page");
  expect(bar()!.querySelector("a[href='/help']")).toBeNull();
  expect(host.querySelector("header a[href='/help']")).not.toBeNull();
  mockPathname = "/";
  mountAll();
  expect(bar()).not.toBeNull();
  mockPathname = "/workspace";
  mockParams = { vaSid: "s1", mode: "coding" };
  mountAll();
  expect(bar()).toBeNull();
  expect(host.querySelectorAll("header")).toHaveLength(1);
  // Inside a case the logo is the way home.
  expect(host.querySelector("header a[href='/app/']")).not.toBeNull();
  mockPathname = "/sign-in";
  mountAll();
  expect(bar()).toBeNull();
});

test("phone: the bottom bar also shows on /interview and /case with VA Interview current", () => {
  mockBootstrap = { ...boot(["coder", "interviewer"]), capabilities: { intake: true, registerDeath: false, registeredDeaths: false, supervision: false } };
  mockWidth = 375;
  for (const path of ["/interview", "/case"]) {
    mockPathname = path;
    mountAll();
    expect(bar()).not.toBeNull();
    expect(bar()!.querySelector("a[href='/app/collection']")!.getAttribute("aria-current")).toBe("page");
  }
});

test("phone: in-app click on a bottom tab navigates without leaving, and the More sheet closes on Escape and outside press", () => {
  mockBootstrap = boot(["coder", "reviewer", "interview_supervisor"]);
  mockWidth = 375;
  mockPathname = "/";
  mountAll();
  expect(click(link("/app/reviewing")).defaultPrevented).toBe(true);
  expect(mockRouter.push).toHaveBeenLastCalledWith("/reviewing");
  act(() => moreButton().click());
  const labels = Array.from(host.querySelectorAll("[role='menuitem']")).map((el) => el.textContent);
  expect(labels).toEqual(["Organization", "Settings", "Website", "Sign out"]);
  expect(click(host.querySelector("[role='menuitem'][href='/app/settings']")!).defaultPrevented).toBe(true);
  expect(mockRouter.push).toHaveBeenLastCalledWith("/settings");
  expect(host.querySelector("[role='menu']")).toBeNull();
  act(() => moreButton().click());
  act(() => { document.activeElement?.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
  expect(host.querySelector("[role='menu']")).toBeNull();
  act(() => moreButton().click());
  expect(host.querySelector("[role='menu']")).not.toBeNull();
  act(() => { document.body.dispatchEvent(new Event("pointerdown", { bubbles: true })); });
  expect(host.querySelector("[role='menu']")).toBeNull();
});

test("phone: Deaths opens my registrations in-app", () => {
  mockBootstrap = everything();
  mockWidth = 375;
  mockPathname = "/";
  mountAll();
  expect(click(link("/app/death-registration?view=mine")).defaultPrevented).toBe(true);
  expect(mockRouter.push).toHaveBeenLastCalledWith("/death-registration?view=mine");
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

test("phone: a reviewer gets VA Review, a collector who also interviews gets Deaths (the shared list) and VA Interview", () => {
  mockWidth = 375;
  mockPathname = "/";
  mockBootstrap = boot(["reviewer"]);
  mountAll();
  expect(barLabels()).toEqual(["Home", "VA Review", "Statistics", "More"]);
  mockBootstrap = { ...boot([]), capabilities: { intake: true, registerDeath: true, registeredDeaths: false, supervision: false } };
  mountAll();
  expect(barLabels()).toEqual(["Home", "Deaths", "VA Interview", "More"]);
  expect(link("/app/death-registration?view=mine")).not.toBeNull();
  expect(link("/app/collection")).not.toBeNull();
});

test("desktop: no bottom bar", () => {
  mountAll();
  expect(host.querySelector("header")).not.toBeNull();
  expect(host.querySelector("nav[aria-label='Primary']")).toBeNull();
});

describe("leave dialog of an open interview's navigation guard", () => {
  let dirty: boolean;
  let failed: boolean;
  let save: jest.Mock;
  let unregister: () => void;
  // On /interview the screen renders the header bar inside its scroller; the root header keeps only the dialog.
  const mountAll = () => act(() => { root.render(<><AppHeader /><AppHeaderBar sticky={false} /><BottomTabs /></>); });
  const dialog = () => host.querySelector<HTMLElement>("[role='alertdialog']");
  const dialogButton = (label: string) => Array.from(dialog()!.querySelectorAll<HTMLButtonElement>("button")).find((b) => b.textContent === label)!;
  const key = (name: string, init: KeyboardEventInit = {}) => act(() => { document.dispatchEvent(new KeyboardEvent("keydown", { key: name, bubbles: true, cancelable: true, ...init })); });

  beforeEach(() => {
    dirty = true;
    failed = false;
    save = jest.fn(async () => true);
    unregister = registerNavigationGuard({ isDirty: () => dirty, save, saveFailed: () => failed });
    mockBootstrap = everything();
    mockWidth = 375;
    mockPathname = "/interview";
  });
  afterEach(() => unregister());

  test("a bottom-bar tab asks first: an alertdialog with focus on Stay; Stay and Escape keep the user", () => {
    mountAll();
    const tab = link("/app/coding");
    expect(click(tab).defaultPrevented).toBe(true);
    expect(mockRouter.push).not.toHaveBeenCalled();
    expect(dialog()).not.toBeNull();
    expect(dialog()!.getAttribute("aria-modal")).toBe("true");
    expect(host.querySelector("#" + dialog()!.getAttribute("aria-labelledby"))!.textContent).toBe("Leave this interview?");
    expect(host.querySelector("#" + dialog()!.getAttribute("aria-describedby"))!.textContent)
      .toBe("Your latest answers have not finished saving. Stay to let them save, or save now and leave.");
    expect(Array.from(dialog()!.querySelectorAll("button")).map((b) => b.textContent)).toEqual(["Stay", "Save and leave", "Leave without saving"]);
    expect(document.activeElement).toBe(dialogButton("Stay"));
    // Tab stays inside the dialog.
    key("Tab", { shiftKey: true });
    expect(document.activeElement).toBe(dialogButton("Leave without saving"));
    key("Tab");
    expect(document.activeElement).toBe(dialogButton("Stay"));
    act(() => dialogButton("Stay").click());
    expect(dialog()).toBeNull();
    click(link("/app/coding"));
    key("Escape");
    expect(dialog()).toBeNull();
    expect(mockRouter.push).not.toHaveBeenCalled();
  });

  test("a second press while the dialog is open does not stack another; Leave runs the first navigation", () => {
    mountAll();
    click(link("/app/coding"));
    click(link("/app/reviewing"));
    expect(host.querySelectorAll("[role='alertdialog']")).toHaveLength(1);
    act(() => dialogButton("Leave without saving").click());
    expect(dialog()).toBeNull();
    expect(mockRouter.push).toHaveBeenCalledTimes(1);
    expect(mockRouter.push).toHaveBeenCalledWith("/coding");
    expect(save).not.toHaveBeenCalled();
  });

  test("Save and leave navigates after the save succeeds and stays when it fails", async () => {
    mountAll();
    click(link("/app/coding"));
    save.mockResolvedValueOnce(false);
    await act(async () => { dialogButton("Save and leave").click(); });
    expect(save).toHaveBeenCalledTimes(1);
    expect(dialog()).toBeNull();
    expect(mockRouter.push).not.toHaveBeenCalled();
    click(link("/app/coding"));
    await act(async () => { dialogButton("Save and leave").click(); });
    expect(mockRouter.push).toHaveBeenCalledWith("/coding");
  });

  test("after a failed save the body says the answers could not be saved, in English and Hindi", () => {
    failed = true;
    mountAll();
    click(link("/app/coding"));
    const body = () => host.querySelector("#" + dialog()!.getAttribute("aria-describedby"))!.textContent;
    expect(body()).toBe("Your latest answers could not be saved. Check your connection, then save again.");
    act(() => dialogButton("Stay").click());
    setUiLocale("hi");
    try {
      click(link("/app/coding"));
      expect(body()).toBe("आपके नवीनतम उत्तर सहेजे नहीं जा सके। अपना कनेक्शन जाँचें, फिर दोबारा सहेजें।");
      failed = false;
      act(() => dialogButton("रुकें").click());
      click(link("/app/coding"));
      expect(body()).toBe("आपके नवीनतम उत्तर अभी पूरी तरह सहेजे नहीं गए हैं। उन्हें सहेजने के लिए रुकें, या अभी सहेजें और जाएँ।");
      expect(Array.from(dialog()!.querySelectorAll("button")).map((b) => b.textContent)).toEqual(["रुकें", "सहेजें और जाएँ", "सहेजे बिना जाएँ"]);
      act(() => dialogButton("रुकें").click());
    } finally {
      setUiLocale("en");
    }
  });

  test("no dialog when nothing would be lost; a new-tab Help link is never held", () => {
    dirty = false;
    mountAll();
    click(link("/app/coding"));
    expect(mockRouter.push).toHaveBeenCalledWith("/coding");
    expect(dialog()).toBeNull();
    dirty = true;
    expect(click(link("/help")).defaultPrevented).toBe(false);
    expect(dialog()).toBeNull();
  });

  test("the logo, Statistics and Sign out ask first too", async () => {
    mountAll();
    click(link("/app/"));
    expect(dialog()).not.toBeNull();
    act(() => dialogButton("Stay").click());
    expect(click(link("/app/statistics")).defaultPrevented).toBe(true);
    expect(dialog()).not.toBeNull();
    act(() => dialogButton("Stay").click());
    act(() => { host.querySelector<HTMLButtonElement>("button[aria-label^='Account menu']")!.click(); });
    const signOut = Array.from(host.querySelectorAll<HTMLElement>("[role='menuitem']")).find((item) => item.textContent === "Sign out")!;
    await act(async () => { signOut.click(); });
    expect(mockLogout).not.toHaveBeenCalled();
    expect(dialog()).not.toBeNull();
    await act(async () => { dialogButton("Leave without saving").click(); });
    expect(mockLogout).toHaveBeenCalledTimes(1);
  });
});

describe("desktop station", () => {
  afterEach(() => { delete (globalThis as { __DIGITVA_LAUNCH_TOKEN__?: string }).__DIGITVA_LAUNCH_TOKEN__; });

  test("the account menu has no Sign out (the station switches actor in Settings), and has it off-station", () => {
    const labels = () => Array.from(host.querySelectorAll("[role='menuitem']")).map((el) => el.textContent);
    mount();
    act(() => { host.querySelector<HTMLButtonElement>("button[aria-label^='Account menu']")!.click(); });
    expect(labels()).toContain("Sign out");
    act(() => root.unmount());
    root = createRoot(host);
    (globalThis as { __DIGITVA_LAUNCH_TOKEN__?: string }).__DIGITVA_LAUNCH_TOKEN__ = "launch-token";
    mount();
    act(() => { host.querySelector<HTMLButtonElement>("button[aria-label^='Account menu']")!.click(); });
    expect(labels()).toContain("Help");
    expect(labels()).not.toContain("Sign out");
  });

  test("phone: the More sheet has no Sign out", () => {
    (globalThis as { __DIGITVA_LAUNCH_TOKEN__?: string }).__DIGITVA_LAUNCH_TOKEN__ = "launch-token";
    mockWidth = 375;
    mockPathname = "/";
    mountAll();
    act(() => moreButton().click());
    const labels = Array.from(host.querySelectorAll("[role='menuitem']")).map((el) => el.textContent);
    expect(labels).toContain("Settings");
    expect(labels).not.toContain("Sign out");
  });
});
