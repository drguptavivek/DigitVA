import React, { type ReactNode } from "react";
import { Image, Modal, StyleSheet, Text } from "react-native";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";

import { ApiError } from "../src/api";
import { activeFilterCount, DEFAULT_FILTERS, filtersFromSearch, filtersToSearch, usersQuery } from "../src/users/api";

let mockWidth = 1280;
const mockRequest = jest.fn();
const mockBootstrap = { csrf: { header: "X-CSRFToken", token: "csrf-token" }, access: { roles: ["data_manager"] } };

jest.mock("react-native", () => {
  const actual = jest.requireActual("react-native");
  Object.defineProperty(actual, "useWindowDimensions", { value: () => ({ width: mockWidth, height: 900, scale: 1, fontScale: 1 }), configurable: true });
  return actual;
});
jest.mock("../src/AppState", () => ({ useAppState: () => ({ bootstrap: mockBootstrap }) }));
jest.mock("../src/workspace/transport.web", () => ({ createWebWorkspaceTransport: () => mockRequest }));
jest.mock("../src/web/common", () => ({
  WebShell: ({ children }: { children: ReactNode }) => <>{children}</>,
  browserErrorText: () => "server error",
}));
let mockFormat = (value: string) => value;
jest.mock("../src/ui/interviewRows", () => ({ formatWhen: (value: string) => mockFormat(value) }));

import UsersScreen, { USER_COLUMNS } from "../src/web/UsersScreen";

const ASHA = {
  user_id: "u1",
  name: "Asha Devi",
  email: "asha@example.org",
  phone: "9876500001",
  active: true,
  last_signed_in_at: null,
  grants: [{ role: "interviewer", scope: "org_unit", project_id: "P1", project_name: "Project One", site_id: null, site_name: null, org_unit_id: "U1", unit_name: "PHC A", level_name: "PHC" }],
  enrolment: { status: "enrolled", devices: 1, revoked_devices: 0, last_seen_at: "2026-10-21T10:00:00Z" },
};
const PAGE = {
  users: [ASHA],
  total: 1,
  limit: 50,
  offset: 0,
  options: { projects: [{ project_id: "P1", project_name: "Project One" }, { project_id: "P2", project_name: "Project Two" }], units: [] },
};
const ACTIVITY = {
  user_id: "u1", name: "Asha Devi",
  totals: { deaths_reported: 4, interviews_submitted: 7, drafts_in_progress: 1, coded: 0, not_codeable: 0, reviewed: 0 },
  by_project: {}, last_signed_in_at: null, last_device_seen_at: "2026-10-21T10:00:00Z", last_active_at: "2026-10-21T10:00:00Z",
};

async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

const mounted: ReactTestRenderer[] = [];

async function render(): Promise<ReactTestRenderer> {
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<UsersScreen />);
  });
  await settle();
  mounted.push(tree);
  return tree;
}

// Unmount every screen, so its search-debounce timer never fires after the test.
afterEach(() => {
  act(() => { mounted.splice(0).forEach((tree) => tree.unmount()); });
});

/** Host nodes only: a composite View and its host node would otherwise both match. */
const byTestId = (tree: ReactTestRenderer, id: string) => tree.root.findAll((n) => typeof n.type === "string" && n.props.testID === id);
const text = (tree: ReactTestRenderer) => tree.root.findAllByType(Text).map((n) => [n.props.children].flat().join("")).join("|");

const pressable = (tree: ReactTestRenderer, label: string) => tree.root.findAll((n) => typeof n.props.onPress === "function" && n.props.accessibilityLabel === label);

/** The wide table keeps a row's actions in its "More actions" menu: open it first when the button is not on screen. */
async function press(tree: ReactTestRenderer, label: string) {
  const menuLabel = /^(?:Show the status of|Create a sign-in QR for|Issue an app enrolment code for) (.+)$/.exec(label)?.[1] ?? (label === "Activity" ? "Asha Devi" : "");
  if (menuLabel && !pressable(tree, label).length) {
    const [menu] = pressable(tree, `More actions for ${menuLabel}`);
    await act(async () => { menu.props.onPress(); });
  }
  const [target] = pressable(tree, label);
  if (!target) throw new Error(`no button labelled ${label}`);
  await act(async () => {
    target.props.onPress();
  });
  await settle();
}

const STATUS = {
  user_id: "u1", name: "Asha Devi", active: true, created_at: "2026-09-01T08:00:00Z",
  email_verified: true, email_verified_at: "2026-09-02T08:00:00Z", password_set: true,
  verification_email_sent_at: "2026-09-01T08:05:00Z", password_emailed_at: "2026-09-03T08:00:00Z",
  terms_accepted: true, terms_accepted_at: "2026-09-04T08:00:00Z",
  passkeys: { count: 2, last_used_at: "2026-10-01T08:00:00Z" },
  enrolment_codes: [{ generated_at: "2026-10-02T08:00:00Z", project_id: "P1", status: "used", expires_at: "2026-10-03T08:00:00Z", code: "LEAK-CODE" }],
  mobile: { status: "enrolled", devices: 1, revoked_devices: 1, last_seen_at: "2026-10-21T10:00:00Z" },
  sign_in_qrs: [{ status: "pending", issued_at: "2026-10-22T08:00:00Z", expires_at: "2026-10-22T14:00:00Z", redeemed_at: null, token: "LEAK-TOKEN" }],
  training: [{ session_code: "TS1", session_name: "Training One", session_status: "open", role: "coder", coder_slot: 2, onboarded: true, onboarded_at: "2026-10-05T08:00:00Z" }],
};
const EMPTY_STATUS = {
  ...STATUS, active: false, created_at: null, email_verified: false, email_verified_at: null, password_set: false,
  verification_email_sent_at: null, password_emailed_at: null, terms_accepted: false, terms_accepted_at: null,
  passkeys: { count: 0, last_used_at: null }, enrolment_codes: [], mobile: { status: "none", devices: 0, revoked_devices: 0, last_seen_at: null },
  sign_in_qrs: [], training: [],
};
const FUTURE = () => new Date(Date.now() + 6 * 3600 * 1000).toISOString();
const PAST = "2020-01-01T00:00:00Z";

let statusBody: unknown = STATUS;
let qrItems: unknown[] = [];
let qrPost: () => Promise<unknown> = () => Promise.resolve({});

function route(path: string, init?: { method?: string; json?: unknown }) {
  if (path.endsWith("/activity")) return Promise.resolve(ACTIVITY);
  if (path.endsWith("/enrolment-code")) return Promise.resolve({ code: "SECRET-CODE", qr_payload: "{}", qr_png: "iVBOR", project_id: "P1", expires_at: "2026-10-22T11:00:00Z", max_uses: 1 });
  if (path.endsWith("/status")) return Promise.resolve(statusBody);
  if (path.endsWith("/sign-in-qr")) {
    if (init?.method === "POST") return qrPost();
    if (init?.method === "DELETE") return Promise.resolve({ revoked: true });
    return Promise.resolve({ items: qrItems });
  }
  return Promise.resolve(PAGE);
}

/** A browser location the page reads on mount and rewrites through history.replaceState. */
const loc = { pathname: "/users", search: "", hash: "" };
const replaceState = jest.fn((_state: unknown, _title: string, url: string) => { loc.search = url.includes("?") ? `?${url.split("?")[1]}` : ""; });
Object.assign(globalThis, { location: loc, history: { state: null, replaceState } });

const lastUrl = () => String(mockRequest.mock.calls.filter(([p]) => String(p).startsWith("/api/v1/users?")).at(-1)?.[0]);
const labelled = (tree: ReactTestRenderer, label: string) => tree.root.findAll((n) => typeof n.props.onPress === "function" && n.props.accessibilityLabel === label);
const hasButton = (tree: ReactTestRenderer, label: string) => labelled(tree, label).length > 0;

describe("UsersScreen", () => {
  beforeEach(() => {
    mockFormat = (value) => value;
    mockWidth = 1280;
    mockRequest.mockReset();
    mockRequest.mockImplementation(route);
    loc.search = "";
    replaceState.mockClear();
    statusBody = STATUS;
    qrItems = [];
    qrPost = () => Promise.resolve({ code: "SIGNIN-SECRET", qr_payload: "{}", qr_png: "QRPNG", expires_at: FUTURE() });
  });

  it("renders a table on a wide screen and cards on a phone", async () => {
    const wide = await render();
    expect(byTestId(wide, "users-table")).toHaveLength(1);
    expect(text(wide)).toContain("asha@example.org");
    expect(text(wide)).toContain("9876500001");
    expect(text(wide)).toContain("Interviewer|PHC A");
    expect(byTestId(wide, "users-card")).toHaveLength(0);

    mockWidth = 375;
    const narrow = await render();
    expect(byTestId(narrow, "users-card").length).toBeGreaterThan(0);
    expect(byTestId(narrow, "users-table")).toHaveLength(0);
  });

  it("starts on active accounts and re-queries the server when a filter changes", async () => {
    const tree = await render();
    expect(mockRequest.mock.calls[0][0]).toBe("/api/v1/users?status=active&limit=50");
    await press(tree, "Filters");
    await press(tree, "Filter: Not enrolled");
    expect(mockRequest.mock.calls.at(-1)?.[0]).toBe("/api/v1/users?status=active&enrolment=none&limit=50");
    await press(tree, "Filter: Project Two");
    expect(mockRequest.mock.calls.at(-1)?.[0]).toContain("project=P2");
  });

  it("builds the query from set filters only", () => {
    expect(usersQuery({ q: " asha ", status: "all", role: "", unit: "U 1" }, 50)).toBe("/api/v1/users?q=asha&unit=U+1&limit=50&offset=50");
  });

  it("loads activity when it is opened", async () => {
    const tree = await render();
    expect(mockRequest.mock.calls.some(([path]) => String(path).endsWith("/activity"))).toBe(false);
    await press(tree, "Activity");
    expect(mockRequest.mock.calls.at(-1)?.[0]).toBe("/api/v1/users/u1/activity");
    expect(text(tree)).toContain("Interviews submitted");
    expect(text(tree)).toContain("7");
    expect(text(tree)).toContain("Last active: 2026-10-21T10:00:00Z");
  });

  it("issues an enrolment code and shows it once in a dialog", async () => {
    const tree = await render();
    await press(tree, "Issue an app enrolment code for Asha Devi");
    expect(text(tree)).toContain("App enrolment for Asha Devi");
    await press(tree, "Show code");
    expect(mockRequest).toHaveBeenLastCalledWith("/api/v1/users/u1/enrolment-code", { method: "POST", json: { project_id: "P1", delivery: "show" } });
    expect(text(tree)).toContain("SECRET-CODE");
    expect(tree.root.findAllByType(Image)[0].props.source.uri).toBe("data:image/png;base64,iVBOR");
    await press(tree, "Close");
    expect(text(tree)).not.toContain("SECRET-CODE");
  });

  it("shows one line per user on a wide screen with a single menu button in the last column", async () => {
    const tree = await render();
    const [line] = byTestId(tree, "users-line");
    const last = line.children[line.children.length - 1] as ReactTestInstance;
    const inLast = (label: string) => last.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onPress === "function").length > 0;
    expect(inLast("More actions for Asha Devi")).toBe(true);
    expect(inLast("Show the status of Asha Devi")).toBe(false); // behind the menu until it is opened
    // name, contact, roles, status and app are single-line text
    const oneLine = tree.root.findAll((n) => typeof n.type === "string" && n.props.numberOfLines === 1).map((n) => n.props.children);
    expect(oneLine).toEqual(expect.arrayContaining(["Asha Devi", "asha@example.org · 9876500001", "Active"]));
    expect(text(tree)).toContain("1 of 1 users");
  });

  it("lines the header up with the cells: same columns, order and layout", async () => {
    const tree = await render();
    const keys = (row: ReactTestInstance) => row.children.map((c) => (c as ReactTestInstance).props.testID);
    const [head] = byTestId(tree, "users-head");
    const [line] = byTestId(tree, "users-line");
    const expected = USER_COLUMNS.map((c) => `users-col-${c.key}`);
    expect(keys(head)).toEqual(expected);
    expect(keys(line)).toEqual(expected);
    const flat = (n: ReactTestInstance) => StyleSheet.flatten((n as ReactTestInstance).props.style);
    const headStyles = head.children.map((c) => flat(c as ReactTestInstance));
    const lineStyles = line.children.map((c) => flat(c as ReactTestInstance));
    expect(lineStyles).toEqual(headStyles);
    expect(text(tree)).toContain("Actions");
    // every column is bounded, so none can push the row wider than the page
    for (const c of USER_COLUMNS) expect(c.style.width ?? c.style.maxWidth).toBeDefined();
  });

  it("reaches every action through the row menu", async () => {
    const tree = await render();
    await press(tree, "More actions for Asha Devi");
    for (const label of ["Activity", "Issue an app enrolment code for Asha Devi", "Show the status of Asha Devi", "Create a sign-in QR for Asha Devi"]) {
      expect(hasButton(tree, label)).toBe(true);
    }
    await press(tree, "Show the status of Asha Devi");
    expect(mockRequest).toHaveBeenLastCalledWith("/api/v1/users/u1/status");
    expect(hasButton(tree, "Create a sign-in QR for Asha Devi")).toBe(false); // the menu closed
  });

  it("formats the status dialog times with the app's formatter", async () => {
    mockFormat = (value) => `FMT(${value.slice(0, 10)})`;
    const tree = await render();
    await press(tree, "Show the status of Asha Devi");
    expect(text(tree)).toContain("Created FMT(2026-09-01)");
    expect(text(tree)).toContain("Last seen FMT(2026-10-21)");
    expect(text(tree)).not.toContain("T08:00:00Z");
  });

  it("summarises many roles on one line and expands them on press", async () => {
    const grant = (role: string, unit: string) => ({ ...ASHA.grants[0], role, unit_name: unit });
    mockRequest.mockImplementation((path: string) => (String(path).startsWith("/api/v1/users?")
      ? Promise.resolve({ ...PAGE, users: [{ ...ASHA, grants: [grant("interviewer", "PHC A"), grant("coder", "PHC B"), grant("reviewer", "PHC C")] }] })
      : route(path)));
    const tree = await render();
    expect(text(tree)).toContain("Interviewer|PHC A|+2 more");
    expect(text(tree)).not.toContain("PHC C");
    await press(tree, "Show all roles of Asha Devi");
    expect(text(tree)).toContain("PHC C");
  });

  it("opens the fly-out as a side sheet on desktop and a bottom sheet on a phone", async () => {
    const wide = await render();
    await press(wide, "Filters");
    expect(byTestId(wide, "users-filter-side")).toHaveLength(1);
    mockWidth = 360;
    const phone = await render();
    expect(byTestId(phone, "users-card").length).toBeGreaterThan(0);
    await press(phone, "Filters");
    expect(byTestId(phone, "users-filter-bottom")).toHaveLength(1);
    expect(byTestId(phone, "users-filter-side")).toHaveLength(0);
  });

  it("sends every fly-out filter to the server and counts them on the button", async () => {
    const tree = await render();
    expect(hasButton(tree, "Filters")).toBe(true);
    await press(tree, "Filters");
    await press(tree, "Filter: Inactive");
    await press(tree, "Filter: Project Two");
    await press(tree, "Filter: Coder");
    await press(tree, "Filter: Not enrolled");
    await press(tree, "Filter: Email verified Yes");
    await press(tree, "Filter: Password set No");
    await press(tree, "Filter: Passkey set Yes");
    const url = new URL(lastUrl(), "http://x");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      status: "inactive", project: "P2", role: "coder", enrolment: "none", email_verified: "yes", password_set: "no", passkey: "yes", limit: "50",
    });
    expect(hasButton(tree, "Filters, 7 active")).toBe(true);
    const field = (label: string) => tree.root.find((n) => n.type === "input" && n.props["aria-label"] === label);
    await act(async () => { field("Created from").props.onChange({ currentTarget: { value: "2026-10-01" } }); });
    await act(async () => { field("Created to").props.onChange({ currentTarget: { value: "2026-10-15" } }); });
    await settle();
    expect(lastUrl()).toContain("created_from=2026-10-01");
    expect(lastUrl()).toContain("created_to=2026-10-15");
    expect(hasButton(tree, "Filters, 8 active")).toBe(true);
  });

  it("keeps the quick chips and the fly-out in step", async () => {
    const tree = await render();
    await press(tree, "Filter: Created today");
    expect(lastUrl()).toContain("created=today");
    await press(tree, "Filters, 1 active");
    const states = () => labelled(tree, "Filter: Created today").map((n) => n.props.accessibilityState?.selected);
    expect(states()).toEqual([true, true]);
    await press(tree, "Filter: Created yesterday"); // the first match is the quick chip: switches the same param
    expect(lastUrl()).toContain("created=yesterday");
    expect(lastUrl()).not.toContain("created=today");
    await press(tree, "Filter: Created yesterday");
    expect(lastUrl()).not.toContain("created=");
    await press(tree, "Filter: App revoked");
    expect(lastUrl()).toContain("enrolment=revoked");
    expect(labelled(tree, "Filter: Revoked").every((n) => n.props.accessibilityState?.selected)).toBe(true);
    await press(tree, "Filter: Email not verified");
    expect(lastUrl()).toContain("email_verified=no");
    await press(tree, "Filter: Email verified");
    expect(lastUrl()).toContain("email_verified=yes");
  });

  it("clears every filter from the fly-out", async () => {
    const tree = await render();
    await press(tree, "Filter: Email verified");
    await press(tree, "Filter: App enrolled");
    await press(tree, "Filters, 2 active");
    await press(tree, "Clear all");
    expect(lastUrl()).toBe("/api/v1/users?status=active&limit=50");
    expect(loc.search).toBe("");
    expect(hasButton(tree, "Filters")).toBe(true);
  });

  it("restores filters from the URL and writes them back", async () => {
    loc.search = "?status=all&email_verified=no&created=yesterday&role=bogus_but_kept&passkey=maybe";
    const tree = await render();
    expect(mockRequest.mock.calls[0][0]).toBe("/api/v1/users?role=bogus_but_kept&created=yesterday&email_verified=no&limit=50");
    expect(replaceState.mock.calls.at(-1)?.[2]).toBe("/users?role=bogus_but_kept&status=all&created=yesterday&email_verified=no");
    await press(tree, "Filter: App enrolled");
    expect(replaceState.mock.calls.at(-1)?.[2]).toContain("enrolment=enrolled");
  });

  it("round-trips filters through the URL and drops bad values", () => {
    const filters = { ...DEFAULT_FILTERS, status: "inactive" as const, project: "P2", created_from: "2026-10-01", passkey: "yes" as const };
    expect(filtersFromSearch(filtersToSearch(filters))).toEqual(filters);
    expect(filtersToSearch(DEFAULT_FILTERS)).toBe("");
    expect(filtersFromSearch("?status=zzz&created=tomorrow&created_from=1/2/3&email_verified=2")).toEqual(DEFAULT_FILTERS);
    expect(activeFilterCount({ ...DEFAULT_FILTERS, q: "x" })).toBe(0);
    expect(activeFilterCount({ ...DEFAULT_FILTERS, status: "all", created_to: "2026-10-01" })).toBe(2);
  });

  it("closes the fly-out and the dialogs on Escape and labels them as modal dialogs", async () => {
    const tree = await render();
    await press(tree, "Filters");
    const modal = tree.root.findAllByType(Modal)[0];
    expect(tree.root.findAll((n) => n.props.role === "dialog" && n.props.accessibilityViewIsModal).length).toBeGreaterThan(0);
    await act(async () => { modal.props.onRequestClose(); });
    expect(tree.root.findAllByType(Modal)).toHaveLength(0);
    await press(tree, "Show the status of Asha Devi");
    const dialog = tree.root.findAll((n) => n.props.role === "dialog")[0];
    expect(dialog.props.accessibilityLabel).toBe("User status: Asha Devi");
    await act(async () => { tree.root.findAllByType(Modal)[0].props.onRequestClose(); });
    expect(tree.root.findAllByType(Modal)).toHaveLength(0);
  });

  it("offers the sign-in QR only for collector-only accounts", async () => {
    const coder = { ...ASHA, user_id: "u2", name: "Coder Dev", grants: [{ ...ASHA.grants[0], role: "coder" }] };
    mockRequest.mockImplementation((path: string) => (String(path).startsWith("/api/v1/users?") ? Promise.resolve({ ...PAGE, users: [ASHA, coder], total: 2 }) : route(path)));
    const tree = await render();
    await press(tree, "More actions for Asha Devi");
    expect(hasButton(tree, "Create a sign-in QR for Asha Devi")).toBe(true);
    await press(tree, "Close");
    await press(tree, "More actions for Coder Dev");
    expect(hasButton(tree, "Create a sign-in QR for Coder Dev")).toBe(false);
    expect(hasButton(tree, "Show the status of Coder Dev")).toBe(true);
  });

  it("shows the status popup from the status endpoint, without codes or tokens", async () => {
    const tree = await render();
    await press(tree, "Show the status of Asha Devi");
    expect(mockRequest).toHaveBeenLastCalledWith("/api/v1/users/u1/status");
    const all = text(tree);
    for (const piece of [
      "User status: Asha Devi", "Account is active", "Created 2026-09-01T08:00:00Z", "Terms accepted 2026-09-04T08:00:00Z",
      "Email verified 2026-09-02T08:00:00Z", "Verification email sent 2026-09-01T08:05:00Z",
      "Password set", "Password setup email sent 2026-09-03T08:00:00Z",
      "2 passkey(s) · Last used 2026-10-01T08:00:00Z",
      "Used · generated 2026-10-02T08:00:00Z · project P1 · expires 2026-10-03T08:00:00Z",
      "Enrolled · 1 device(s) · 1 revoked", "Last seen 2026-10-21T10:00:00Z",
      "Pending · issued 2026-10-22T08:00:00Z · expires 2026-10-22T14:00:00Z",
      "Training One (open) · coder · slot 2 · onboarded 2026-10-05T08:00:00Z",
    ]) expect(all).toContain(piece);
    expect(all).not.toContain("LEAK");
  });

  it("shows clear empty states in the status popup", async () => {
    statusBody = EMPTY_STATUS;
    const tree = await render();
    await press(tree, "Show the status of Asha Devi");
    const all = text(tree);
    for (const piece of [
      "Account is inactive", "Creation date not recorded", "Email not verified", "Password not set", "No password setup email sent",
      "Terms not accepted", "No passkey registered", "No enrolment code has been generated.", "Not enrolled · 0 device(s) · 0 revoked",
      "No sign-in QR has been issued.", "Not in any training session.",
    ]) expect(all).toContain(piece);
  });

  it("shows a status error when the popup cannot load", async () => {
    mockRequest.mockImplementation((path: string) => (String(path).endsWith("/status") ? Promise.reject(new Error("boom")) : route(path)));
    const tree = await render();
    await press(tree, "Show the status of Asha Devi");
    expect(text(tree)).toContain("server error");
  });

  it("shows a sign-in QR once with a countdown and a warning, and clears it on Close", async () => {
    const tree = await render();
    await press(tree, "Create a sign-in QR for Asha Devi");
    expect(mockRequest.mock.calls.some(([p]) => p === "/api/v1/users/u1/status")).toBe(true);
    expect(text(tree)).toContain("valid for 6 hours and works once");
    await press(tree, "Show on screen");
    expect(mockRequest).toHaveBeenLastCalledWith("/api/v1/users/u1/sign-in-qr", { method: "POST", json: { delivery: "show" } });
    expect(text(tree)).toContain("SIGNIN-SECRET");
    expect(tree.root.findAllByType(Image).some((i) => i.props.source.uri === "data:image/png;base64,QRPNG")).toBe(true);
    expect(text(tree)).toMatch(/Valid for 6 hours\. Expires in (6:00:00|5:59:5\d)\./);
    expect(text(tree)).toContain("Do not photograph or share this screen");
    await press(tree, "Close");
    expect(text(tree)).not.toContain("SIGNIN-SECRET");
    expect(tree.root.findAllByType(Image)).toHaveLength(0);
  });

  it("clears an expired QR from memory", async () => {
    qrPost = () => Promise.resolve({ code: "SIGNIN-SECRET", qr_payload: "{}", qr_png: "QRPNG", expires_at: PAST });
    const tree = await render();
    await press(tree, "Create a sign-in QR for Asha Devi");
    await press(tree, "Show on screen");
    expect(text(tree)).not.toContain("SIGNIN-SECRET");
    expect(text(tree)).toContain("This QR has expired and was cleared");
  });

  it("emails a sign-in QR to a verified address", async () => {
    const tree = await render();
    await press(tree, "Create a sign-in QR for Asha Devi");
    await press(tree, "Email it");
    expect(mockRequest).toHaveBeenLastCalledWith("/api/v1/users/u1/sign-in-qr", { method: "POST", json: { delivery: "email" } });
    expect(text(tree)).toContain("Emailed. The QR is valid for 6 hours");
  });

  it("explains why email is off for an unverified address and does not send", async () => {
    statusBody = EMPTY_STATUS;
    const tree = await render();
    await press(tree, "Create a sign-in QR for Asha Devi");
    expect(text(tree)).toContain("this person's email is not verified");
    const [email] = labelled(tree, "Email it");
    expect(email.props.disabled || email.props.accessibilityState?.disabled).toBeTruthy();
    expect(mockRequest.mock.calls.some(([, init]) => init?.json?.delivery === "email")).toBe(false);
  });

  it("explains when the person has no email address", async () => {
    mockRequest.mockImplementation((path: string) => (String(path).startsWith("/api/v1/users?") ? Promise.resolve({ ...PAGE, users: [{ ...ASHA, email: null }] }) : route(path)));
    const tree = await render();
    await press(tree, "Create a sign-in QR for Asha Devi");
    expect(text(tree)).toContain("no email address on file");
  });

  it("lists a pending QR and revokes it", async () => {
    qrItems = [{ status: "expired", issued_at: "a", expires_at: "b", redeemed_at: null }, { status: "pending", issued_at: "c", expires_at: "2026-10-22T14:00:00Z", redeemed_at: null }];
    const tree = await render();
    await press(tree, "Create a sign-in QR for Asha Devi");
    expect(text(tree)).toContain("already pending (expires 2026-10-22T14:00:00Z)");
    await press(tree, "Revoke pending QR");
    expect(mockRequest).toHaveBeenLastCalledWith("/api/v1/users/u1/sign-in-qr", { method: "DELETE" });
    expect(text(tree)).toContain("The pending QR was revoked.");
    expect(hasButton(tree, "Revoke pending QR")).toBe(false);
  });

  it.each([
    [400, "not_eligible", "Show on screen", "cannot get a sign-in QR"],
    [400, "no_verified_email", "Email it", "email is not verified, so the QR cannot be emailed"],
    [502, "email_failed", "Email it", "The email could not be sent"],
    [404, "not_found", "Show on screen", "cannot manage this person's sign-in QR"],
  ])("shows %s %s clearly", async (status, code, action, message) => {
    qrPost = () => Promise.reject(new ApiError(status as number, code as string));
    const tree = await render();
    await press(tree, "Create a sign-in QR for Asha Devi");
    await press(tree, action as string);
    expect(text(tree)).toContain(message as string);
    expect(text(tree)).not.toContain("SIGNIN-SECRET");
  });

  it("hides the QR actions when the person is not manageable", async () => {
    mockRequest.mockImplementation((path: string, init?: { method?: string }) => (
      String(path).endsWith("/sign-in-qr") && !init?.method ? Promise.reject(new ApiError(404, "not_found")) : route(path, init)));
    const tree = await render();
    await press(tree, "Create a sign-in QR for Asha Devi");
    expect(text(tree)).toContain("cannot manage this person's sign-in QR");
    expect(hasButton(tree, "Show on screen")).toBe(false);
  });
});
