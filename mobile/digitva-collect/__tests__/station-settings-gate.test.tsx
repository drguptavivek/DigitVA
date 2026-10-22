import React, { type ReactNode } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import {
  fetchStationFacility,
  fetchStationSettings,
  saveStationFacility,
  saveStationSettings,
  type StationSettings,
} from "../src/api";
import { ApiError } from "../src/api";
import { exportStationBundle, fetchStationRoster, importBundleReceipt, type StationRosterSnapshot } from "../src/roster";
import { fetchContextualHelp } from "../src/web/ContextualHelp";

// The station UI (actor bar, .dvb transfer, roster) exists only in the desktop edition, which
// injects a per-launch token; the server build has no /station/* routes.

jest.mock("expo-router", () => ({ useRouter: () => ({ push: jest.fn() }) }));
jest.mock("../src/AppState", () => ({
  useAppState: () => ({ bootstrap: { csrf: { token: "csrf" } }, reload: jest.fn() }),
}));
jest.mock("../src/web/common", () => ({
  WebShell: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
jest.mock("../src/ui", () => ({ Button: "button", useUiStyles: () => ({}) }));
jest.mock("../src/theme", () => ({
  ...jest.requireActual("../src/theme"),
  useTheme: () => ({
    ...jest.requireActual("../src/theme").getTheme("dark"),
    preference: "system",
    setPreference: jest.fn(),
  }),
}));
jest.mock("../src/api", () => ({
  ...jest.requireActual("../src/api"),
  fetchStationFacility: jest.fn(),
  saveStationFacility: jest.fn(),
  fetchStationSettings: jest.fn(),
  saveStationSettings: jest.fn(),
}));
jest.mock("../src/roster", () => ({
  ...jest.requireActual("../src/roster"),
  fetchStationRoster: jest.fn(),
  importBundleReceipt: jest.fn(),
  exportStationBundle: jest.fn(),
}));

import SettingsScreen from "../src/web/SettingsScreen";

const snapshot: StationRosterSnapshot = {
  station_mode: "standalone",
  editable: true,
  custodian: null,
  designations: [{ code: "medical_officer", label: "Medical Officer" }],
  members: [
    {
      user_id: null,
      member_id: "roster-mo-1",
      name: "Dr. Anil Sharma",
      designation: "medical_officer",
      is_reporter: true,
      is_interviewer: true,
      is_supervisor: true,
      is_coder: true,
      active: true,
      source: "sandbox",
      created_at: "2026-10-21T00:00:00Z",
      updated_at: "2026-10-21T00:00:00Z",
    },
  ],
  active_actor: {
    member_id: "roster-mo-1",
    user_id: null,
    name: "Dr. Anil Sharma",
    designation: "medical_officer",
    acting_role: "station_supervisor",
    allowed_acting_roles: ["death_reporter", "interviewer", "station_supervisor", "coder"],
  } as StationRosterSnapshot["active_actor"],
  recent_audit: [],
};

const settings = (locked = false): StationSettings => ({
  modules: [
    { code: "abha", label: "ABHA health ID", enabled: true },
    { code: "social_autopsy", label: "Social autopsy", enabled: !locked },
  ],
  modules_locked: locked,
  coding_mode: "icd11_doris",
  coding_mode_locked: false,
  available_coding_modes: ["icd11_doris", "icd10"],
});

const globals = globalThis as { __DIGITVA_LAUNCH_TOKEN__?: string; fetch?: unknown };

async function render(): Promise<ReactTestRenderer> {
  let tree: ReactTestRenderer;
  await act(async () => {
    tree = create(<SettingsScreen />);
  });
  return tree!;
}

const byTestId = (tree: ReactTestRenderer, id: string) => tree.root.findAll((node) => node.props.testID === id);

beforeEach(() => {
  jest.mocked(fetchStationRoster).mockReset().mockResolvedValue(snapshot);
  jest.mocked(fetchStationFacility).mockReset().mockResolvedValue({
    name: "Rampur PHC", code: "RP01", type: "PHC", address: "Main Rd", district: "Rampur", state: "UP",
  });
  jest.mocked(saveStationFacility).mockReset().mockImplementation(async (f) => f);
  jest.mocked(fetchStationSettings).mockReset().mockResolvedValue(settings());
  jest.mocked(saveStationSettings).mockReset().mockImplementation(async (change) => ({
    ...settings(),
    ...(change.coding_mode ? { coding_mode: change.coding_mode } : {}),
  }));
});

afterEach(() => {
  delete globals.__DIGITVA_LAUNCH_TOKEN__;
});

it("hides the station UI and never calls /station/* without a launch token (server app)", async () => {
  const tree = await render();
  expect(byTestId(tree, "station-bundle-transfer-card")).toHaveLength(0);
  expect(byTestId(tree, "station-actor-bar")).toHaveLength(0);
  expect(fetchStationRoster).not.toHaveBeenCalled();
});

it("shows the station UI with a launch token (desktop edition)", async () => {
  globals.__DIGITVA_LAUNCH_TOKEN__ = "launch-token";
  const tree = await render();
  expect(byTestId(tree, "station-bundle-transfer-card").length).toBeGreaterThan(0);
  expect(byTestId(tree, "station-actor-bar").length).toBeGreaterThan(0);
  expect(byTestId(tree, "sandbox-station-banner").length).toBeGreaterThan(0);
  expect(fetchStationRoster).toHaveBeenCalled();
});

it("does not request contextual help on the station (no route there)", async () => {
  globals.__DIGITVA_LAUNCH_TOKEN__ = "launch-token";
  const fetchMock = jest.fn();
  const saved = globals.fetch;
  globals.fetch = fetchMock;
  try {
    await expect(fetchContextualHelp("settings")).resolves.toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  } finally {
    globals.fetch = saved;
  }
});

it("shows the facility details above the roster and saves edits", async () => {
  globals.__DIGITVA_LAUNCH_TOKEN__ = "launch-token";
  const tree = await render();
  const nameInput = byTestId(tree, "facility-name-input")[0];
  expect(nameInput.props.value).toBe("Rampur PHC");
  expect(byTestId(tree, "facility-state-input")[0].props.value).toBe("UP");

  await act(async () => {
    nameInput.props.onChangeText("Rampur Model PHC");
  });
  const save = tree.root.findAll((n) => n.props.label === "Save facility details")[0];
  await act(async () => {
    save.props.onPress();
  });
  expect(saveStationFacility).toHaveBeenCalledWith(
    expect.objectContaining({ name: "Rampur Model PHC", code: "RP01" }),
    { token: "csrf" },
  );

  await act(async () => {
    byTestId(tree, "facility-name-input")[0].props.onChangeText("  ");
  });
  await act(async () => {
    tree.root.findAll((n) => n.props.label === "Save facility details")[0].props.onPress();
  });
  expect(saveStationFacility).toHaveBeenCalledTimes(1);
});

it("shows the interview modules and coding mode cards and saves each choice", async () => {
  globals.__DIGITVA_LAUNCH_TOKEN__ = "launch-token";
  const tree = await render();
  expect(byTestId(tree, "station-modules-card").length).toBeGreaterThan(0);
  const sa = byTestId(tree, "module-social_autopsy")[0];
  expect(sa.props.accessibilityState.checked).toBe(true);
  await act(async () => {
    sa.props.onPress();
  });
  await act(async () => {
    tree.root.findAll((n) => n.props.label === "Save modules")[0].props.onPress();
  });
  expect(saveStationSettings).toHaveBeenCalledWith({ enabled_modules: ["abha"] }, { token: "csrf" });

  expect(byTestId(tree, "coding-mode-icd11_doris")[0].props.accessibilityState.selected).toBe(true);
  await act(async () => {
    byTestId(tree, "coding-mode-icd10")[0].props.onPress();
  });
  await act(async () => {
    tree.root.findAll((n) => n.props.label === "Save coding mode")[0].props.onPress();
  });
  expect(saveStationSettings).toHaveBeenLastCalledWith({ coding_mode: "icd10" }, { token: "csrf" });
  expect(byTestId(tree, "coding-mode-icd10")[0].props.accessibilityState.selected).toBe(true);
});

it("shows project-set modules read-only with the setup-file note", async () => {
  globals.__DIGITVA_LAUNCH_TOKEN__ = "launch-token";
  jest.mocked(fetchStationSettings).mockResolvedValue(settings(true));
  const tree = await render();
  const card = byTestId(tree, "station-modules-card")[0];
  expect(card.findAll((n) => n.props.children === "Set by your project's setup file").length).toBeGreaterThan(0);
  const sa = byTestId(tree, "module-social_autopsy")[0];
  expect(sa.props.disabled).toBe(true);
  expect(sa.props.accessibilityState.checked).toBe(false);
  expect(tree.root.findAll((n) => n.props.label === "Save modules")).toHaveLength(0);
  // The coding mode is not locked by this policy and stays editable.
  expect(tree.root.findAll((n) => n.props.label === "Save coding mode").length).toBeGreaterThan(0);
});

it("shows a config-locked coding mode read-only, and says when coding is done on the server", async () => {
  globals.__DIGITVA_LAUNCH_TOKEN__ = "launch-token";
  jest.mocked(fetchStationSettings).mockResolvedValue({ ...settings(), coding_mode: "icd10", coding_mode_locked: true });
  let tree = await render();
  let card = byTestId(tree, "station-coding-mode-card")[0];
  expect(card.findAll((n) => n.props.children === "Set by your project's setup file").length).toBeGreaterThan(0);
  expect(byTestId(tree, "coding-mode-icd10")[0].props.accessibilityState).toEqual({ selected: true, disabled: true });
  expect(tree.root.findAll((n) => n.props.label === "Save coding mode")).toHaveLength(0);

  jest.mocked(fetchStationSettings).mockResolvedValue({ ...settings(), coding_mode: null, coding_mode_locked: true });
  tree = await render();
  card = byTestId(tree, "station-coding-mode-card")[0];
  expect(byTestId(tree, "coding-done-on-server")[0].props.children).toBe("Coding for this project is done on the server.");
  expect(byTestId(tree, "coding-mode-icd10")).toHaveLength(0);
  expect(tree.root.findAll((n) => n.props.label === "Save coding mode")).toHaveLength(0);
});

it("reports the receipt's accepted, waiting and refused counts", async () => {
  globals.__DIGITVA_LAUNCH_TOKEN__ = "launch-token";
  jest.mocked(importBundleReceipt).mockReset().mockResolvedValue({
    bundle_id: "b-1", acknowledged_deleted_count: 2, accepted_count: 2, pending_count: 1, rejected_count: 1, purged_ids: [],
  });
  const tree = await render();
  const input = tree.root.findAll((n) => n.props.onChangeText && String(n.props.placeholder ?? "").includes("bundle_id"))[0];
  await act(async () => {
    input.props.onChangeText("line1\nline2");
  });
  await act(async () => {
    byTestId(tree, "import-dvb-receipt-btn")[0].props.onPress();
  });
  expect(importBundleReceipt).toHaveBeenCalledWith("line1\nline2", { token: "csrf" });
  const texts = tree.root.findAll((n) => typeof n.props.children === "string").map((n) => n.props.children as string);
  expect(texts.some((text) => text.includes("The server's answers: 2 accepted, 1 waiting, 1 refused."))).toBe(true);
});

it("lists the records held back from a data file, with their reasons", async () => {
  globals.__DIGITVA_LAUNCH_TOKEN__ = "launch-token";
  jest.mocked(fetchStationRoster).mockResolvedValue({ ...snapshot, station_mode: "provisioned" });
  jest.mocked(exportStationBundle).mockReset().mockResolvedValue({
    bundle_id: "b-1", filename: "f.dvb", record_count: 1,
    records_held_back: [{ client_id: "c-1", reason: "Consent notice invalid." }],
  });
  const tree = await render();
  await act(async () => {
    byTestId(tree, "export-dvb-bundle-btn")[0].props.onPress();
  });
  const texts = () => tree.root.findAll((n) => typeof n.props.children === "string").map((n) => n.props.children as string);
  expect(texts().some((text) => text.includes("Data file f.dvb created with 1 record(s)"))).toBe(true);
  expect(texts()).toContain("1 record(s) were kept out of this data file and stay on this computer: c-1: Consent notice invalid.");

  // Every record held back: the export is refused, and the reasons still show.
  jest.mocked(exportStationBundle).mockReset().mockRejectedValue(
    new ApiError(422, "records_held_back", undefined, undefined, {
      records_held_back: [{ client_id: "c-2", reason: "No notice." }, { bad: true }],
    }),
  );
  await act(async () => {
    byTestId(tree, "export-dvb-bundle-btn")[0].props.onPress();
  });
  expect(texts()).toContain("1 record(s) were kept out of this data file and stay on this computer: c-2: No notice.");
});
