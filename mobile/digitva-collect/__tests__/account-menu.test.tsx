/** @jest-environment jsdom */
import React, { act } from "react";

jest.mock("react-native", () => {
  const actual = jest.requireActual("react-native");
  Object.defineProperty(actual, "useWindowDimensions", { value: jest.fn(), configurable: true });
  return actual;
});
jest.mock("../src/preferences", () => ({
  ...jest.requireActual("../src/preferences"),
  setUiTheme: jest.fn().mockResolvedValue(undefined),
}));

// No @types/react-dom in this app; the test only needs createRoot.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createRoot } = require("react-dom/client") as { createRoot: (el: Element) => Root };
type Root = { render(node: React.ReactNode): void; unmount(): void };

import * as ReactNative from "react-native";
import { AccountMenu, initialsOf } from "../src/workspace/AccountMenu.web";
import { __setThemePreferenceForTest, useTheme } from "../src/theme";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const dimensions = ReactNative.useWindowDimensions as jest.Mock;
let host: HTMLDivElement;
let root: Root;
let preference = "";
function Probe() { preference = useTheme().preference; return null; }

function mount(onSignOut: () => Promise<void> = async () => undefined, width = 1280) {
  dimensions.mockReturnValue({ width, height: 900, scale: 1, fontScale: 1 });
  act(() => { root.render(<><Probe /><AccountMenu name="Test Admin" onSignOut={onSignOut} /></>); });
}
const button = () => host.querySelector<HTMLButtonElement>("button[aria-haspopup='menu']")!;
const items = () => Array.from(host.querySelectorAll<HTMLElement>("[role^='menuitem']"));
const open = () => act(() => { button().click(); });
const key = (target: Element, k: string, init: KeyboardEventInit = {}) =>
  act(() => { target.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, ...init })); });

beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  __setThemePreferenceForTest("system");
});
afterEach(() => { act(() => root.unmount()); host.remove(); });

test("initials come from the first and last word", () => {
  expect([initialsOf("Test Admin"), initialsOf("asha"), initialsOf("A B C"), initialsOf("  ")]).toEqual(["TA", "AS", "AC", "?"]);
});

test("closed by default, opens with menu semantics and items by role", () => {
  mount();
  expect(button().getAttribute("aria-expanded")).toBe("false");
  expect(host.querySelector("[role='menu']")).toBeNull();
  open();
  expect(button().getAttribute("aria-expanded")).toBe("true");
  expect(host.querySelector("[role='menu']")).not.toBeNull();
  expect(items().map((i) => `${i.getAttribute("role")}:${i.textContent}`)).toEqual([
    "menuitem:Profile", "menuitem:Open web version", "menuitemradio:Light", "menuitemradio:Dark", "menuitemradio:System✓", "menuitem:Help", "menuitem:Sign out",
  ]);
  expect(host.querySelector<HTMLAnchorElement>("a[role='menuitem']")!.getAttribute("href")).toBe("/profile/");
  expect(host.textContent).toContain("Test Admin");
  expect(document.activeElement).toBe(items()[0]);
});

test("Open web version sits between Profile and Theme, opens the Flask home in a new tab and takes part in arrow navigation", () => {
  mount();
  open();
  const link = items()[1] as HTMLAnchorElement;
  expect(link.getAttribute("href")).toBe("/vaindex");
  expect(link.getAttribute("target")).toBe("_blank");
  expect(link.getAttribute("rel")).toBe("noopener");
  expect(link.getAttribute("aria-label")).toBe("Open web version (opens in a new tab)");
  expect(link.querySelector("svg")).not.toBeNull();
  const help = items().find((item) => item.textContent === "Help") as HTMLAnchorElement;
  expect(help.getAttribute("target")).toBe("_blank");
  expect(help.getAttribute("rel")).toBe("noopener");
  key(items()[0], "ArrowDown");
  expect(document.activeElement).toBe(link);
});

test("Escape closes and returns focus to the button; outside click closes", () => {
  mount();
  open();
  key(document.activeElement!, "Escape");
  expect(host.querySelector("[role='menu']")).toBeNull();
  expect(document.activeElement).toBe(button());
  open();
  act(() => { document.body.dispatchEvent(new Event("pointerdown", { bubbles: true })); });
  expect(host.querySelector("[role='menu']")).toBeNull();
});

test("arrow keys wrap, Home/End jump and Tab stays inside the menu", () => {
  mount();
  open();
  const list = items();
  key(list[0], "ArrowUp");
  expect(document.activeElement).toBe(list[list.length - 1]);
  key(document.activeElement!, "Tab");
  expect(document.activeElement).toBe(list[0]);
  key(list[0], "ArrowDown");
  expect(document.activeElement).toBe(list[1]);
  key(document.activeElement!, "End");
  expect(document.activeElement).toBe(list[list.length - 1]);
  key(document.activeElement!, "Home");
  expect(document.activeElement).toBe(list[0]);
});

test("theme radios change the shared store, reflect the choice and close the menu", () => {
  mount();
  open();
  expect(items()[4].getAttribute("aria-checked")).toBe("true");
  act(() => { items()[3].click(); });
  expect(preference).toBe("dark");
  expect(host.querySelector("[role='menu']")).toBeNull();
  open();
  expect(items()[3].getAttribute("aria-checked")).toBe("true");
  expect(items()[4].getAttribute("aria-checked")).toBe("false");
});

test("Sign out calls the injected logout once; a failure shows an alert and keeps the menu open", async () => {
  const signOut = jest.fn().mockRejectedValueOnce(new Error("x")).mockResolvedValue(undefined);
  mount(signOut);
  open();
  await act(async () => { items()[items().length - 1].click(); });
  expect(signOut).toHaveBeenCalledTimes(1);
  expect(host.querySelector("[role='alert']")?.textContent).toMatch(/could not sign out/i);
  expect(host.querySelector("[role='menu']")).not.toBeNull();
  await act(async () => { items()[items().length - 1].click(); });
  expect(signOut).toHaveBeenCalledTimes(2);
  expect(host.querySelector("[role='menu']")).toBeNull();
});

test("route change (popstate) closes the menu", () => {
  mount();
  open();
  act(() => { window.dispatchEvent(new PopStateEvent("popstate")); });
  expect(host.querySelector("[role='menu']")).toBeNull();
});

test("the name is hidden on narrow phones but the initials and accessible name stay", () => {
  mount(undefined, 390);
  expect(button().textContent).toBe("TA");
  expect(button().getAttribute("aria-label")).toBe("Account menu, Test Admin");
  act(() => root.unmount());
  root = createRoot(host);
  mount(undefined, 1280);
  expect(button().textContent).toBe("TATest Admin");
});

// A browser sends pointerdown, mousedown, pointerup, mouseup, then click; the menu must survive the
// whole sequence on the trigger and on an item, whatever listeners react to the earlier events.
const realClick = (target: Element) => act(() => {
  for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
    const Ctor = type.startsWith("pointer") && typeof PointerEvent !== "undefined" ? PointerEvent : MouseEvent;
    target.dispatchEvent(new Ctor(type, { bubbles: true, cancelable: true, button: 0 }));
  }
});

test("a real pointer sequence opens the menu and fires an item action", async () => {
  const onSignOut = jest.fn().mockResolvedValue(undefined);
  mount(onSignOut);
  realClick(button());
  expect(host.querySelector("[role='menu']")).not.toBeNull();
  const signOut = items().find((i) => i.textContent === "Sign out")!;
  realClick(signOut);
  expect(onSignOut).toHaveBeenCalledTimes(1);
});

test("a real pointer sequence on a theme item applies it and closes the menu", () => {
  mount();
  realClick(button());
  realClick(items().find((i) => i.textContent === "Dark")!);
  expect(preference).toBe("dark");
  expect(host.querySelector("[role='menu']")).toBeNull();
});

test("Escape closes the menu from an item and returns focus to the trigger", () => {
  mount();
  realClick(button());
  key(items()[0], "Escape");
  expect(host.querySelector("[role='menu']")).toBeNull();
  expect(document.activeElement).toBe(button());
});
