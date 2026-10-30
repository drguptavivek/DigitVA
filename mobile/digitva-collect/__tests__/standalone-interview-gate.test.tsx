/**
 * Standalone interview start gate (digitva-0vz7): the readiness rule, the prefill and its locks on the real WHO
 * engine, the interviewer recall not overriding it, the SmartVA fallback from the interview's own answers, and the
 * standalone home's "New interview" gate.
 */
import React, { type ReactNode } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { createWhoVa2022Instrument, createWhoVaSession } from "@drguptavivek/who-2022-va";

const mockProfile: { value: unknown } = { value: null };
const mockPush = jest.fn();
const mockBackupAt: { value: string | null } = { value: new Date().toISOString() };
jest.mock("expo-secure-store", () => ({
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 0,
  getItemAsync: jest.fn(async () => (mockProfile.value ? JSON.stringify(mockProfile.value) : null)),
  setItemAsync: jest.fn(async () => undefined),
}));
jest.mock("expo-router", () => {
  const R = jest.requireActual("react") as typeof React;
  return {
    Redirect: () => null,
    useRouter: () => ({ push: mockPush, replace: jest.fn(), back: jest.fn() }),
    useLocalSearchParams: () => ({ userId: "standalone-1" }),
    // Focus once on mount, as the screen does when first shown.
    useFocusEffect: (callback: () => void | (() => void)) => R.useEffect(callback, [callback]),
  };
});
jest.mock("expo-crypto", () => ({
  ...jest.requireActual("expo-crypto"),
  randomUUID: () => "44444444-4444-4444-8444-444444444444",
}));
const mockLockNow = jest.fn();
const mockAppState = {
  accounts: [{ user_id: "standalone-1", name: "Asha", standalone: true }],
  lockVersion: 0,
  lockNow: mockLockNow,
  uiLocale: "en",
};
jest.mock("../src/AppState", () => ({ useAppState: () => mockAppState }));
jest.mock("../src/interviewerDb", () => ({ isUnlocked: () => true, openInterviewerDb: jest.fn(async () => ({})) }));
jest.mock("../src/drafts", () => ({ retryHeldDraft: jest.fn() }));
const baseRecord: Record<string, unknown> & { id: string } = {
  id: "draft-1", completed: false, started_at: "2026-10-30T00:00:00Z", updated_at: "2026-10-30T00:00:00Z",
  completed_at: null, coding_status: null, upload_issue: null, refusal_code: null, name: "", age_years: null, sex: null,
};
const mockRecords: { value: Array<typeof baseRecord> } = { value: [] };
jest.mock("../src/standalone/records", () => ({
  listStandaloneRecords: jest.fn(async () => mockRecords.value),
  lastBackupAt: jest.fn(async () => mockBackupAt.value),
}));
// The home no longer renders DataActions; a marker lets the test prove it stays off the home.
jest.mock("../src/standalone/DataActions", () => ({ DataActions: () => require("react").createElement("data-actions") }));
jest.mock("../src/standalone/export", () => ({ dataActionsAllowed: () => true }));
const mockSweep = jest.fn();
const mockWarmUpStop = jest.fn();
const mockWarmUp = jest.fn(() => mockWarmUpStop);
jest.mock("../src/offlineEngine", () => ({ scheduleEngineWarmUp: () => mockWarmUp() }));
jest.mock("../src/standalone/shareFile", () => ({ sweepExportLeftovers: () => mockSweep() }));
const WORDS: Record<string, string> = { sexMale: "Male", sexFemale: "Female" };
jest.mock("../src/i18n", () => ({
  t: (key: string, values?: Record<string, string | number>) => WORDS[key]
    ?? (key === "standaloneTabCount" ? `${values!.label} (${values!.count})` : key === "metaAgeYears" ? `${values!.value} y` : values?.time ? `${key} ${values.time}` : values?.fields ? `${key}:${values.fields}` : key),
}));
jest.mock("../src/ui", () => {
  const R = jest.requireActual("react") as typeof React;
  return {
    Button: ({ label, onPress, disabled }: { label: string; onPress?: () => void; disabled?: boolean }) =>
      R.createElement("button", { "data-label": label, onClick: onPress, disabled }, label),
    Screen: ({ children }: { children: ReactNode }) => R.createElement("main", null, children),
    errorText: () => "error",
    useUiStyles: () => ({ text: {}, muted: {}, error: {}, input: {}, card: {} }),
  };
});

import { standalonePrefill, standaloneProfileMissing, type OfflineProfile } from "../src/offlineProfile";
import { initialDataFromPrefill } from "../src/prefill";
import { withInterviewerRecall } from "../src/interviewerRecall";
import { standaloneSmartVaSnapshot, standaloneSmartVaSnapshotFromAnswers } from "../src/smartva/options";
import StandaloneHome from "../src/nativeRoutes/standalone";

const ready: OfflineProfile = {
  name: "Asha Devi", age_years: 34, sex: "female", designation: "", facility_name: "", country: "India", state: "",
  hiv_mortality: "low", malaria_mortality: "none", updated_at: "2026-10-30T00:00:00Z",
};

describe("standaloneProfileMissing", () => {
  it("is empty for a complete profile", () => {
    expect(standaloneProfileMissing(ready)).toEqual([]);
    expect(standaloneProfileMissing({ ...ready, age_years: 99 })).toEqual([]);
  });

  it("names every field of a missing or bare profile in form order", () => {
    const all = ["name", "age_years", "sex", "country", "hiv_mortality", "malaria_mortality"];
    expect(standaloneProfileMissing(null)).toEqual(all);
    expect(standaloneProfileMissing({ ...ready, name: " ", age_years: null, sex: null, country: " ", hiv_mortality: null, malaria_mortality: null }))
      .toEqual(all);
  });

  it("counts a value the form would refuse once locked as missing", () => {
    expect(standaloneProfileMissing({ ...ready, name: "आशा" })).toEqual(["name"]);
    for (const age of [17, 90, 98, 130, Number.NaN]) expect(standaloneProfileMissing({ ...ready, age_years: age })).toEqual(["age_years"]);
    expect(standaloneProfileMissing({ ...ready, age_years: 18 })).toEqual([]);
    expect(standaloneProfileMissing({ ...ready, age_years: 89 })).toEqual([]);
  });
});

describe("standalone prefill", () => {
  it("maps the profile to the form's choice values and locks the five questions on the real engine", () => {
    const prefill = standalonePrefill({ ...ready, name: "Dr. Asha Devi", sex: "other", hiv_mortality: "high" });
    const data = initialDataFromPrefill(prefill);
    expect(data).toEqual({ Id10010: "Dr Asha Devi", Id10010a: 34, Id10010b: "undetermined", Id10002: "high", Id10003: "veryl" });
    expect(initialDataFromPrefill(standalonePrefill({ ...ready, sex: "male", hiv_mortality: "none", malaria_mortality: "low" })))
      .toMatchObject({ Id10010b: "male", Id10002: "veryl", Id10003: "low" });

    const session = createWhoVaSession(createWhoVa2022Instrument([]), { initialData: data, lockedQuestionNames: prefill.lockedQuestionNames });
    const snapshot = session.getSnapshot();
    expect(snapshot.data).toMatchObject({ Id10010: "Dr Asha Devi", Id10010a: 34, Id10010b: "undetermined", Id10002: "high", Id10003: "veryl" });
    expect([...snapshot.lockedQuestionNames].sort()).toEqual(["Id10002", "Id10003", "Id10010", "Id10010a", "Id10010b"]);
    for (const [name, value] of [["Id10010", "Other"], ["Id10010a", 40], ["Id10010b", "male"], ["Id10002", "low"], ["Id10003", "high"]] as const) {
      expect(() => session.setAnswer(name, value)).toThrow("cannot be edited");
    }
  });

  // The engine enforces only locks that hold an answer (session.ts enforcedLocks, digitva-k7m4), so a value left out
  // stays editable.
  it("leaves out a value the form would refuse", () => {
    const data = initialDataFromPrefill(standalonePrefill({ ...ready, name: "आशा", age_years: 17 }))!;
    expect(data).toEqual({ Id10010b: "female", Id10002: "low", Id10003: "veryl" });
  });

  it("wins over the interviewer recall, which still fills the interviewer ID", () => {
    const data = withInterviewerRecall(
      initialDataFromPrefill(standalonePrefill(ready)),
      { Id10010: "Old Name", Id10010a: 60, Id10010b: "male", Id10010c: "EMP-7" },
      "Asha",
    );
    expect(data).toMatchObject({ Id10010: "Asha Devi", Id10010a: 34, Id10010b: "female", Id10010c: "EMP-7" });
  });
});

describe("SmartVA fallback from the interview's answers", () => {
  it("takes HIV and malaria from Id10002/Id10003 and the country from the profile", async () => {
    const bare = { ...ready, country: " India ", hiv_mortality: null, malaria_mortality: null };
    await expect(standaloneSmartVaSnapshot(bare, "WHO_2022_VA", "v1")).resolves.toBeNull();
    const snapshot = await standaloneSmartVaSnapshotFromAnswers(bare, { Id10002: "high", Id10003: "veryl" }, "WHO_2022_VA", "v1");
    expect(snapshot).toMatchObject({
      schemaVersion: 1, formId: "WHO_2022_VA", formUpdatedAt: "v1", source: "interview",
      options: { country: "India", hiv: true, malaria: false, hce: true, freetext: true },
    });
    await expect(standaloneSmartVaSnapshotFromAnswers(bare, { Id10002: "low", Id10003: "high" }, "WHO_2022_VA", "v1"))
      .resolves.toMatchObject({ options: { hiv: false, malaria: true } });
  });

  it("digests the options alone, so the source does not change the digest", async () => {
    const fromAnswers = await standaloneSmartVaSnapshotFromAnswers(ready, { Id10002: "high", Id10003: "low" }, "WHO_2022_VA", "v1");
    const fromProfile = await standaloneSmartVaSnapshot({ ...ready, hiv_mortality: "high", malaria_mortality: "low" }, "WHO_2022_VA", "v1");
    expect(fromProfile).not.toHaveProperty("source");
    expect(fromAnswers!.optionsDigest).toBe(fromProfile!.optionsDigest);
  });

  it("stays null when either answer or the country is missing", async () => {
    await expect(standaloneSmartVaSnapshotFromAnswers(ready, { Id10002: "high" }, "WHO_2022_VA", "v1")).resolves.toBeNull();
    await expect(standaloneSmartVaSnapshotFromAnswers(ready, { Id10002: "dk", Id10003: "low" }, "WHO_2022_VA", "v1")).resolves.toBeNull();
    await expect(standaloneSmartVaSnapshotFromAnswers(ready, undefined, "WHO_2022_VA", "v1")).resolves.toBeNull();
    await expect(standaloneSmartVaSnapshotFromAnswers({ ...ready, country: " " }, { Id10002: "high", Id10003: "low" }, "WHO_2022_VA", "v1"))
      .resolves.toBeNull();
    await expect(standaloneSmartVaSnapshotFromAnswers(null, { Id10002: "high", Id10003: "low" }, "WHO_2022_VA", "v1")).resolves.toBeNull();
  });
});

describe("standalone home gate", () => {
  async function render(): Promise<ReactTestRenderer> {
    let tree!: ReactTestRenderer;
    await act(async () => { tree = create(<StandaloneHome />); });
    await act(async () => { await Promise.resolve(); });
    return tree;
  }
  const button = (tree: ReactTestRenderer, label: string) => tree.root.findAllByProps({ "data-label": label })[0];

  beforeEach(() => {
    mockPush.mockClear();
    mockLockNow.mockClear();
    mockRecords.value = [{ ...baseRecord }];
    mockBackupAt.value = new Date().toISOString();
  });

  it("disables New interview, names what is missing and opens the profile, but keeps drafts open", async () => {
    mockProfile.value = { ...ready, sex: null, malaria_mortality: null };
    const tree = await render();
    expect(button(tree, "standaloneNewInterview").props.disabled).toBe(true);
    expect(tree.root.findByProps({ accessibilityRole: "alert" }).props.children)
      .toBe("standaloneProfileIncomplete:offlineProfileSex, offlineProfileMalaria");
    await act(async () => { button(tree, "standaloneProfileComplete").props.onClick(); });
    expect(mockPush).toHaveBeenCalledWith("/offline-profile");
    const draft = button(tree, "actionResume");
    expect(draft.props.disabled).toBeFalsy();
    await act(async () => { draft.props.onClick(); });
    expect(mockPush).toHaveBeenLastCalledWith({ pathname: "/form", params: expect.objectContaining({ draftId: "draft-1" }) });
    await act(async () => tree.unmount());
  });

  it("enables New interview when the profile is ready", async () => {
    mockProfile.value = ready;
    const tree = await render();
    expect(tree.root.findAllByProps({ "data-label": "standaloneProfileComplete" })).toHaveLength(0);
    const start = button(tree, "standaloneNewInterview");
    expect(start.props.disabled).toBe(false);
    await act(async () => { start.props.onClick(); });
    expect(mockPush).toHaveBeenCalledWith({ pathname: "/form", params: expect.objectContaining({ draftId: "44444444-4444-4444-8444-444444444444" }) });
    await act(async () => tree.unmount());
  });

  it("keeps Settings and Lock now on the home but moves export, backup, restore and enrol to Settings", async () => {
    mockProfile.value = ready;
    const tree = await render();
    await act(async () => { button(tree, "lockNow").props.onClick(); });
    expect(mockLockNow).toHaveBeenCalledTimes(1);
    await act(async () => { button(tree, "settings").props.onClick(); });
    expect(mockPush).toHaveBeenLastCalledWith({ pathname: "/settings", params: { userId: "standalone-1" } });
    expect(tree.root.findAllByType("data-actions" as never)).toHaveLength(0);
    expect(tree.root.findAllByProps({ "data-label": "standaloneEnrol" })).toHaveLength(0);
    await act(async () => tree.unmount());
  });

  it("shows the backup reminder with a button that opens Settings, and no reminder after a recent backup", async () => {
    mockProfile.value = ready;
    mockSweep.mockClear();
    const recent = await render();
    expect(button(recent, "lockNow")).toBeDefined();
    expect(mockSweep).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(recent.toJSON())).not.toContain("standaloneBackup");
    await act(async () => recent.unmount());

    mockBackupAt.value = "2020-01-01T00:00:00Z";
    const tree = await render();
    expect(JSON.stringify(tree.toJSON())).toContain("standaloneBackupReminder");
    await act(async () => { button(tree, "standaloneBackupOpenSettings").props.onClick(); });
    expect(mockPush).toHaveBeenLastCalledWith({ pathname: "/settings", params: { userId: "standalone-1" } });
    await act(async () => tree.unmount());
  });

  describe("record tabs (digitva-31ci)", () => {
    const done = { ...baseRecord, completed: true, completed_at: "2026-10-29T00:00:00Z" };
    const tabLabels = (tree: ReactTestRenderer) => tree.root.findAllByType("button" as never)
      .map((node) => node.props["data-label"] as string).filter((label) => /\(\d+\)$/.test(label));
    const text = (tree: ReactTestRenderer) => JSON.stringify(tree.toJSON());

    beforeEach(() => {
      mockProfile.value = ready;
      mockRecords.value = [
        { ...baseRecord, id: "d-1", name: "Ravi Kumar", age_years: 62, sex: "male" },
        { ...done, id: "p-1", name: "Sita Devi", age_years: 41, sex: "female", coding_status: null },
        { ...done, id: "p-2", name: "", coding_status: "pending" },
        { ...done, id: "c-1", name: "Mohan Lal", age_years: 70, sex: "male", coding_status: "coded" },
      ];
    });

    it("counts each tab and opens on Pending coding when it has records", async () => {
      const tree = await render();
      expect(tabLabels(tree).sort()).toEqual(["standaloneCoded (1)", "standaloneDraft (1)", "standaloneTabPending (2)"]);
      const out = text(tree);
      expect(out).toContain("Sita Devi · 41 y · Female");
      expect(out).not.toContain("Ravi Kumar");
      expect(out).not.toContain("Mohan Lal");
      await act(async () => tree.unmount());
    });

    it("falls back to In progress when nothing is pending, and switches tabs on press", async () => {
      mockRecords.value = mockRecords.value.filter((r) => r.id !== "p-1" && r.id !== "p-2");
      const tree = await render();
      expect(text(tree)).toContain("Ravi Kumar · 62 y · Male");
      expect(tree.root.findAllByProps({ "data-label": "standaloneTabPending (0)" })).toHaveLength(1);
      await act(async () => { button(tree, "standaloneTabPending (0)").props.onClick(); });
      expect(text(tree)).toContain("standaloneNoPending");
      expect(text(tree)).not.toContain("Ravi Kumar");
      await act(async () => { button(tree, "standaloneCoded (1)").props.onClick(); });
      expect(text(tree)).toContain("Mohan Lal · 70 y · Male");
      await act(async () => tree.unmount());
    });

    it("warms the engine only on Pending coding with a record to code, and stops on leaving the tab", async () => {
      mockWarmUp.mockClear();
      mockWarmUpStop.mockClear();
      const tree = await render();
      expect(text(tree)).toContain("Sita Devi · 41 y · Female");
      expect(mockWarmUp).toHaveBeenCalledTimes(1);
      await act(async () => { button(tree, "standaloneDraft (1)").props.onClick(); });
      expect(mockWarmUpStop).toHaveBeenCalledTimes(1);
      await act(async () => { button(tree, "standaloneTabPending (2)").props.onClick(); });
      expect(mockWarmUp).toHaveBeenCalledTimes(2);
      await act(async () => tree.unmount());

      mockWarmUp.mockClear();
      mockRecords.value = mockRecords.value.filter((r) => r.id !== "p-1" && r.id !== "p-2");
      const empty = await render();
      await act(async () => { button(empty, "standaloneTabPending (0)").props.onClick(); });
      expect(text(empty)).toContain("standaloneNoPending");
      expect(mockWarmUp).not.toHaveBeenCalled();
      await act(async () => empty.unmount());
    });

    it("stays on Pending coding after its last record is coded, so the empty tab says so", async () => {
      mockRecords.value = mockRecords.value.filter((r) => r.id !== "p-2");
      const tree = await render();
      expect(text(tree)).toContain("Sita Devi · 41 y · Female");
      // Coded on the coding screen; the home reloads (focus or lock change) with the record now coded.
      mockRecords.value = mockRecords.value.map((r) => (r.id === "p-1" ? { ...r, coding_status: "coded" } : r));
      mockAppState.lockVersion += 1;
      await act(async () => { tree.update(<StandaloneHome />); });
      await act(async () => { await Promise.resolve(); });
      expect(tabLabels(tree)).toContain("standaloneCoded (2)");
      expect(text(tree)).toContain("standaloneNoPending");
      expect(text(tree)).not.toContain("Ravi Kumar");
      mockAppState.lockVersion = 0;
      await act(async () => tree.unmount());
    });

    it("titles a nameless record with its UUID and shows the UUID under a named one", async () => {
      const tree = await render();
      const out = text(tree);
      // Pending tab: the nameless record is titled by its UUID; the named one shows its UUID under the name.
      expect(out).toContain('"p-2"');
      expect(out).toContain('"Sita Devi · 41 y · Female"');
      expect(out).toContain('"p-1"');
      // The status line carries the local date and hh:mm, as the clock does, not the bare ISO date.
      const when = new Date("2026-10-29T00:00:00Z").toLocaleString(mockAppState.uiLocale, { dateStyle: "medium", timeStyle: "short" });
      expect(out).toContain(when);
      expect(out).not.toContain("2026-10-29");
      await act(async () => tree.unmount());
    });

    it("offers Revise coding only on a coded row, routed to offline coding", async () => {
      const tree = await render();
      await act(async () => { button(tree, "standaloneCoded (1)").props.onClick(); });
      const revise = button(tree, "standaloneReviseCoding");
      expect(revise).toBeDefined();
      expect(tree.root.findAllByProps({ "data-label": "standaloneCodeIt" })).toHaveLength(0);
      await act(async () => { revise.props.onClick(); });
      expect(mockPush).toHaveBeenLastCalledWith({ pathname: "/offline-coding", params: { userId: "standalone-1", caseId: "c-1" } });
      await act(async () => { button(tree, "standaloneTabPending (2)").props.onClick(); });
      expect(tree.root.findAllByProps({ "data-label": "standaloneCodeIt" })).toHaveLength(2);
      expect(tree.root.findAllByProps({ "data-label": "standaloneReviseCoding" })).toHaveLength(0);
      await act(async () => tree.unmount());
    });
  });
});
