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
const mockAppState = {
  accounts: [{ user_id: "standalone-1", name: "Asha", standalone: true }],
  lockVersion: 0,
  lockNow: jest.fn(),
  uiLocale: "en",
};
jest.mock("../src/AppState", () => ({ useAppState: () => mockAppState }));
jest.mock("../src/interviewerDb", () => ({ isUnlocked: () => true, openInterviewerDb: jest.fn(async () => ({})) }));
jest.mock("../src/drafts", () => ({ retryHeldDraft: jest.fn() }));
jest.mock("../src/standalone/records", () => ({
  listStandaloneRecords: jest.fn(async () => [{
    id: "draft-1", completed: false, started_at: "2026-10-30T00:00:00Z", updated_at: "2026-10-30T00:00:00Z",
    completed_at: null, coding_status: null, upload_issue: null, refusal_code: null,
  }]),
  lastBackupAt: jest.fn(async () => "2026-10-30T00:00:00Z"),
}));
jest.mock("../src/standalone/DataActions", () => ({ DataActions: () => null }));
jest.mock("../src/standalone/export", () => ({ dataActionsAllowed: () => false }));
jest.mock("../src/i18n", () => ({ t: (key: string, values?: Record<string, string>) => (values?.fields ? `${key}:${values.fields}` : key) }));
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

  beforeEach(() => mockPush.mockClear());

  it("disables New interview, names what is missing and opens the profile, but keeps drafts open", async () => {
    mockProfile.value = { ...ready, sex: null, malaria_mortality: null };
    const tree = await render();
    expect(button(tree, "standaloneNewInterview").props.disabled).toBe(true);
    expect(tree.root.findByProps({ accessibilityRole: "alert" }).props.children)
      .toBe("standaloneProfileIncomplete:offlineProfileSex, offlineProfileMalaria");
    await act(async () => { button(tree, "standaloneProfileComplete").props.onClick(); });
    expect(mockPush).toHaveBeenCalledWith("/offline-profile");
    const draft = button(tree, "standaloneDraft");
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
});
