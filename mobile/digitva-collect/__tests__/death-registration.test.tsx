import React, { Profiler, type ReactNode } from "react";
import { act, create } from "react-test-renderer";

let mockLocale = "en";
let mockParams: Record<string, string> = {};
const mockReplace = jest.fn();
const mockPush = jest.fn();
const mockSetParams = jest.fn();

const access = (mode: string | undefined, userId = "u1", name = "Interviewer") => ({
  user: { user_id: userId, name },
  is_admin: false,
  roles: ["interviewer"],
  demo_coding: { available: false, project_ids: [] },
  projects: [{
    project_id: "P1", project_name: "Project", has_tree: false, grants: [], sites: [],
    actions: {
      interview: [{ site_id: "S1", site_name: "Site", web_intake_mode: "both", org_units: [] }],
      register_death: mode === undefined ? [] : [{ site_id: "S1", site_name: "Site", web_intake_mode: mode, org_units: [] }],
    },
    units: [],
  }],
});

const createBootstrap = (userId = "u1", name = "Interviewer") => ({
  user: { user_id: userId, name },
  csrf: { header: "X-CSRFToken", token: "csrf" },
  capabilities: { intake: true, registerDeath: true, registeredDeaths: false, coding: false, reviewing: false },
  access: access("death_register", userId, name),
  links: { intakeCases: "/api/v1/intake/cases", intakeDrafts: "/api/v1/intake/drafts" }
});
let mockBootstrap = createBootstrap();

const mockNavigation = { addListener: () => () => undefined, dispatch: () => undefined };
jest.mock("expo-router", () => ({ useNavigation: () => mockNavigation, useIsFocused: () => true, useRouter: () => ({ replace: mockReplace, push: mockPush, setParams: mockSetParams, back: jest.fn() }), useLocalSearchParams: () => mockParams }));
jest.mock("../src/AppState", () => ({ useAppState: () => ({ bootstrap: mockBootstrap }) }));
jest.mock("../src/i18n", () => ({ t: (key: string) => (mockLocale === "hi" ? `hi:${key}` : key), uiLocale: () => mockLocale }));
jest.mock("../src/ui", () => ({
  Button: ({ label, onPress }: { label: string; onPress: () => void }) => <button data-label={label} onClick={onPress} />,
  stateLabel: (state: string) => `state:${state}`,
  useUiStyles: () => ({ error: {}, muted: {}, input: {}, card: {}, text: {}, row: {} })
}));
jest.mock("../src/web/common", () => ({ WebShell: ({ children }: { children: ReactNode }) => <>{children}</>, browserErrorText: () => "error" }));
jest.mock("../src/web/SupervisionPanel", () => ({ SupervisionPanel: () => <div data-supervision-panel="true" /> }));
jest.mock("../src/web/registrationControls", () => {
  const React = require("react") as typeof import("react");
  return {
    RegistrationFieldControl: ({ field, value, dateAppearance, onChange, onIssue, issueMessage }: { field: string; value: string; dateAppearance?: string; onChange: (value: string) => void; onIssue: (issue?: string) => void; issueMessage?: string }) =>
      React.createElement("button", { "data-field": field, "data-value": value, "data-appearance": dateAppearance, "data-issue": issueMessage, onClick: onChange as unknown as () => void, onIssue } as Record<string, unknown>)
  };
});
jest.mock("../src/PhoneInput", () => {
  const React = require("react") as typeof import("react");
  return {
    PhoneNumbers: () => React.createElement("button", { "data-field": "informant_phone" } as Record<string, unknown>)
  };
});
jest.mock("../src/web/LocationCapture", () => {
  const React = require("react") as typeof import("react");
  return {
    LocationCapture: ({ value, onChange }: { value: unknown; onChange: (next: unknown) => void }) =>
      React.createElement("button", { "data-location": JSON.stringify(value), onClick: onChange as unknown as () => void }),
    MapsLink: ({ latitude, longitude }: { latitude?: number; longitude?: number }) =>
      typeof latitude === "number" && typeof longitude === "number" ? React.createElement("a", { "data-maps": `${latitude},${longitude}` }) : null,
    MapsPinButton: () => null
  };
});
jest.mock("../src/web/StationConsentPanel", () => {
  const React = require("react") as typeof import("react");
  return {
    StationConsentPanel: ({ onChange }: { onChange: (envelope: unknown) => void }) =>
      React.createElement("button", { "data-consent-panel": "true", onClick: () => onChange({ client_id: "c1", decision: "granted" }) } as Record<string, unknown>),
    RespondentConsentPanel: ({ onDecision, language }: { onDecision: (envelope: unknown) => void; language: string }) =>
      React.createElement("div", { "data-web-consent": language }, [
        React.createElement("button", { key: "g", "data-web-decision": "granted", onClick: () => onDecision({ client_id: "w1", decision: "granted" }) } as Record<string, unknown>),
        React.createElement("button", { key: "r", "data-web-decision": "refused", onClick: () => onDecision({ client_id: "w2", decision: "refused" }) } as Record<string, unknown>),
      ])
  };
});
const mockFetchConsentConfig = jest.fn();
jest.mock("../src/consent", () => ({
  ...jest.requireActual("../src/consent"),
  fetchProjectConsentConfig: (...args: unknown[]) => mockFetchConsentConfig(...args),
}));
jest.mock("../src/client/api", () => ({
  INTAKE_API: "/api/v1/intake",
  getCases: jest.fn(),
  getIntakeContext: jest.fn(),
  registerDeath: jest.fn(),
  startDraft: jest.fn()
}));

import DeathRegistrationScreen from "../src/web/DeathRegistrationScreen";
import { getCases, registerDeath, startDraft } from "../src/client/api";
import * as sharedApi from "../src/api";
import * as identifiersApi from "../src/identifiers";
import { TextInput } from "react-native";
import { guardedNavigate, leaveDialogOpen, stayOnPage } from "../src/web/navigationGuard";

const mockRegisterDeath = registerDeath as jest.Mock;
const mockStartDraft = startDraft as jest.Mock;
const mockGetCases = getCases as jest.Mock;

async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe("DeathRegistrationScreen", () => {
  beforeEach(() => {
    mockLocale = "en";
    mockParams = {};
    mockReplace.mockReset();
    mockPush.mockReset();
    mockSetParams.mockReset();
    jest.restoreAllMocks();
    jest.clearAllMocks();
    mockBootstrap = createBootstrap();
    mockBootstrap.capabilities = { intake: true, registerDeath: true, registeredDeaths: false, coding: false, reviewing: false };
    mockBootstrap.access = access("death_register");
    mockRegisterDeath.mockResolvedValue({ case: { death_id: "d1" } });
    mockStartDraft.mockResolvedValue({ draft: { draft_id: "draft1" } });
    mockGetCases.mockReset();
    mockGetCases.mockResolvedValue({ cases: [], next_cursor: null });
    mockFetchConsentConfig.mockResolvedValue(null);
  });

  it("blocks submit while a date control reports an invalid draft, then recovers", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<DeathRegistrationScreen />);
    });
    await settle();

    const findField = (field: string) => tree!.root.findByProps({ "data-field": field });
    await act(async () => {
      findField("deceased_name").props.onClick("Asha");
      findField("date_of_death").props.onClick("2026-09-30");
      findField("date_of_birth").props.onClick("1987-04-12");
      findField("date_of_death").props.onIssue("invalid date");
    });
    await act(async () => tree!.root.findByProps({ "data-label": "sexFemale" }).props.onClick());
    await act(async () => tree!.root.findByProps({ "data-label": "registerSaveStart" }).props.onClick());
    await settle();
    expect(mockRegisterDeath).not.toHaveBeenCalled();

    await act(async () => {
      findField("date_of_death").props.onIssue(undefined);
    });
    await settle();
    await act(async () => {
      tree!.root.findByProps({ "data-label": "registerSaveStart" }).props.onClick();
    });
    await settle();
    expect(mockRegisterDeath).toHaveBeenCalledTimes(1);
    await act(async () => tree!.unmount());
  });

  it("on a station, blocks saving informant details until consent is granted, then sends it", async () => {
    (globalThis as { __DIGITVA_LAUNCH_TOKEN__?: string }).__DIGITVA_LAUNCH_TOKEN__ = "tok";
    let tree: ReturnType<typeof create>;
    try {
      await act(async () => { tree = create(<DeathRegistrationScreen />); });
      await settle();
      const findField = (field: string) => tree!.root.findByProps({ "data-field": field });
      expect(tree!.root.findAllByProps({ "data-consent-panel": "true" })).toHaveLength(0);
      await act(async () => {
        findField("deceased_name").props.onClick("Asha");
        findField("date_of_death").props.onClick("2026-09-30");
        findField("date_of_birth").props.onClick("1987-04-12");
        findField("informant_name").props.onClick("Lakshmi");
      });
      await act(async () => tree!.root.findByProps({ "data-label": "sexFemale" }).props.onClick());
      expect(tree!.root.findByProps({ testID: "station-consent-blocked" })).toBeDefined();
      await act(async () => tree!.root.findByProps({ "data-label": "registerSaveStart" }).props.onClick());
      await settle();
      expect(mockRegisterDeath).not.toHaveBeenCalled();

      await act(async () => tree!.root.findByProps({ "data-consent-panel": "true" }).props.onClick());
      expect(tree!.root.findAllByProps({ testID: "station-consent-blocked" })).toHaveLength(0);
      await act(async () => tree!.root.findByProps({ "data-label": "registerSaveStart" }).props.onClick());
      await settle();
      expect(mockRegisterDeath).toHaveBeenCalledTimes(1);
      expect(mockRegisterDeath.mock.calls[0][1].consent).toEqual({ client_id: "c1", decision: "granted" });
      await act(async () => tree!.unmount());
    } finally {
      delete (globalThis as { __DIGITVA_LAUNCH_TOKEN__?: string }).__DIGITVA_LAUNCH_TOKEN__;
    }
  });

  it("on a station, tells the user to leave informant details empty when the project has no consent notice", async () => {
    (globalThis as { __DIGITVA_LAUNCH_TOKEN__?: string }).__DIGITVA_LAUNCH_TOKEN__ = "tok";
    mockRegisterDeath.mockRejectedValue(new sharedApi.ApiError(422, "consent_notice_unavailable"));
    let tree: ReturnType<typeof create>;
    try {
      await act(async () => { tree = create(<DeathRegistrationScreen />); });
      await settle();
      const findField = (field: string) => tree!.root.findByProps({ "data-field": field });
      await act(async () => {
        findField("deceased_name").props.onClick("Asha");
        findField("date_of_death").props.onClick("2026-09-30");
        findField("date_of_birth").props.onClick("1987-04-12");
        findField("informant_name").props.onClick("Lakshmi");
      });
      await act(async () => tree!.root.findByProps({ "data-label": "sexFemale" }).props.onClick());
      await act(async () => tree!.root.findByProps({ "data-consent-panel": "true" }).props.onClick());
      expect(JSON.stringify(tree!.toJSON())).not.toContain("stationConsentNoNotice");
      await act(async () => tree!.root.findByProps({ "data-label": "registerSaveStart" }).props.onClick());
      await settle();
      expect(mockRegisterDeath).toHaveBeenCalledTimes(1);
      expect(JSON.stringify(tree!.toJSON())).toContain("stationConsentNoNotice");
      await act(async () => tree!.unmount());
    } finally {
      delete (globalThis as { __DIGITVA_LAUNCH_TOKEN__?: string }).__DIGITVA_LAUNCH_TOKEN__;
    }
  });

  // ── web respondent consent (digitva-athy, owner 2026-10-22) ──────────────

  const requiredConfig = { project_id: "P1", consent_required: true, notice_versions: [] };

  async function fillDeceased(tree: ReturnType<typeof create>) {
    const findField = (field: string) => tree.root.findByProps({ "data-field": field });
    await act(async () => {
      findField("deceased_name").props.onClick("Asha");
      findField("date_of_death").props.onClick("2026-09-30");
      findField("date_of_birth").props.onClick("1987-04-12");
    });
    await act(async () => tree.root.findByProps({ "data-label": "sexFemale" }).props.onClick());
  }

  it("on the web, keeps informant fields closed until the respondent's consent is recorded, then sends it", async () => {
    mockFetchConsentConfig.mockResolvedValue(requiredConfig);
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<DeathRegistrationScreen />); });
    await settle();
    expect(mockFetchConsentConfig).toHaveBeenCalledWith("P1", mockBootstrap.csrf);
    // The panel is shown in the user's language; the informant fields are not there yet.
    expect(tree!.root.findByProps({ "data-web-consent": "en" })).toBeDefined();
    expect(tree!.root.findAllByProps({ "data-field": "informant_name" })).toHaveLength(0);
    expect(tree!.root.findAllByProps({ "data-field": "informant_phone" })).toHaveLength(0);
    expect(tree!.root.findAllByProps({ "data-field": "address" })).toHaveLength(0);
    expect(tree!.root.findByProps({ testID: "informant-closed" })).toBeDefined();
    await fillDeceased(tree!);
    await act(async () => tree!.root.findByProps({ "data-label": "registerSaveStart" }).props.onClick());
    await settle();
    expect(mockRegisterDeath).not.toHaveBeenCalled();
    expect(JSON.stringify(tree!.toJSON())).toContain("consentRegistrationBlocked");

    await act(async () => tree!.root.findByProps({ "data-web-decision": "granted" }).props.onClick());
    expect(tree!.root.findAllByProps({ "data-web-consent": "en" })).toHaveLength(0);
    expect(tree!.root.findByProps({ testID: "respondent-consent-recorded" })).toBeDefined();
    await act(async () => tree!.root.findByProps({ "data-field": "informant_name" }).props.onClick("Lakshmi"));
    await act(async () => tree!.root.findByProps({ "data-label": "registerSaveStart" }).props.onClick());
    await settle();
    expect(mockRegisterDeath).toHaveBeenCalledTimes(1);
    const body = mockRegisterDeath.mock.calls[0][1];
    expect(body.informant_name).toBe("Lakshmi");
    expect(body.consent).toEqual({ client_id: "w1", decision: "granted" });
    await act(async () => tree!.unmount());
  });

  it("on the web, a refusal keeps the informant fields closed and empty and is sent with the registration", async () => {
    mockFetchConsentConfig.mockResolvedValue(requiredConfig);
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<DeathRegistrationScreen />); });
    await settle();
    await fillDeceased(tree!);
    await act(async () => tree!.root.findByProps({ "data-web-decision": "refused" }).props.onClick());
    expect(tree!.root.findAllByProps({ "data-field": "informant_name" })).toHaveLength(0);
    expect(JSON.stringify(tree!.toJSON())).toContain("consentRecordedRefused");
    await act(async () => tree!.root.findByProps({ "data-label": "registerSaveStart" }).props.onClick());
    await settle();
    expect(mockRegisterDeath).toHaveBeenCalledTimes(1);
    const body = mockRegisterDeath.mock.calls[0][1];
    expect(body.consent).toEqual({ client_id: "w2", decision: "refused" });
    expect(body).not.toHaveProperty("informant_name");
    await act(async () => tree!.unmount());
  });

  it("on the web, a project without required consent shows no consent screen", async () => {
    mockFetchConsentConfig.mockResolvedValue({ ...requiredConfig, consent_required: false });
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<DeathRegistrationScreen />); });
    await settle();
    expect(tree!.root.findAllByProps({ "data-web-consent": "en" })).toHaveLength(0);
    await fillDeceased(tree!);
    await act(async () => tree!.root.findByProps({ "data-field": "informant_name" }).props.onClick("Lakshmi"));
    await act(async () => tree!.root.findByProps({ "data-label": "registerSaveStart" }).props.onClick());
    await settle();
    expect(mockRegisterDeath).toHaveBeenCalledTimes(1);
    expect(mockRegisterDeath.mock.calls[0][1]).not.toHaveProperty("consent");
    await act(async () => tree!.unmount());
  });

  it("on the web, a server consent_required reloads the consent config so the screen appears", async () => {
    mockRegisterDeath.mockRejectedValueOnce(new sharedApi.ApiError(422, "consent_required"));
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<DeathRegistrationScreen />); });
    await settle();
    await fillDeceased(tree!);
    await act(async () => tree!.root.findByProps({ "data-field": "informant_name" }).props.onClick("Lakshmi"));
    mockFetchConsentConfig.mockResolvedValue(requiredConfig);
    await act(async () => tree!.root.findByProps({ "data-label": "registerSaveStart" }).props.onClick());
    await settle();
    expect(JSON.stringify(tree!.toJSON())).toContain("consentRegistrationBlocked");
    expect(tree!.root.findByProps({ "data-web-consent": "en" })).toBeDefined();
    await act(async () => tree!.unmount());
  });

  it("on a station, keeps the always-required station rule whatever the project switch says", async () => {
    (globalThis as { __DIGITVA_LAUNCH_TOKEN__?: string }).__DIGITVA_LAUNCH_TOKEN__ = "tok";
    mockFetchConsentConfig.mockResolvedValue({ ...requiredConfig, consent_required: false });
    let tree: ReturnType<typeof create>;
    try {
      await act(async () => { tree = create(<DeathRegistrationScreen />); });
      await settle();
      // No web panel and no config fetch: informant fields are open, the station panel guards them.
      expect(mockFetchConsentConfig).not.toHaveBeenCalled();
      expect(tree!.root.findAllByProps({ "data-web-consent": "en" })).toHaveLength(0);
      await fillDeceased(tree!);
      await act(async () => tree!.root.findByProps({ "data-field": "informant_name" }).props.onClick("Lakshmi"));
      expect(tree!.root.findByProps({ testID: "station-consent-blocked" })).toBeDefined();
      await act(async () => tree!.root.findByProps({ "data-label": "registerSaveStart" }).props.onClick());
      await settle();
      expect(mockRegisterDeath).not.toHaveBeenCalled();
      await act(async () => tree!.unmount());
    } finally {
      delete (globalThis as { __DIGITVA_LAUNCH_TOKEN__?: string }).__DIGITVA_LAUNCH_TOKEN__;
    }
  });

  it("shows localized required errors and never calls the API for an invalid form", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<DeathRegistrationScreen />);
    });
    await settle();
    await act(async () => {
      tree!.root.findByProps({ "data-label": "registerSaveStart" }).props.onClick();
    });
    const issueFor = (field: string) => tree!.root.findByProps({ "data-field": field }).props["data-issue"];
    expect(issueFor("deceased_name")).toBe("errRequired");
    expect(issueFor("date_of_birth")).toBe("errBirthOrAge");
    expect(issueFor("date_of_death")).toBe("errRequired");
    expect(mockRegisterDeath).not.toHaveBeenCalled();
    await act(async () => tree!.unmount());
  });

  it("keeps validation errors as codes so they follow a language change", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<DeathRegistrationScreen />);
    });
    await settle();
    await act(async () => tree!.root.findByProps({ "data-label": "registerSaveStart" }).props.onClick());
    mockLocale = "hi";
    await act(async () => tree!.update(<DeathRegistrationScreen />));
    expect(tree!.root.findByProps({ "data-field": "date_of_birth" }).props["data-issue"]).toBe("hi:errBirthOrAge");
    await act(async () => tree!.unmount());
  });

  it("requires confirmation for an exact age over 85 and saves only after confirmation", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<DeathRegistrationScreen />);
    });
    await settle();
    const findField = (field: string) => tree!.root.findByProps({ "data-field": field });
    await act(async () => {
      findField("deceased_name").props.onClick("Asha");
      findField("date_of_birth").props.onClick("1925-01-01");
      findField("date_of_death").props.onClick("2026-09-30");
    });
    await act(async () => tree!.root.findByProps({ "data-label": "sexFemale" }).props.onClick());
    await act(async () => tree!.root.findByProps({ "data-label": "registerSaveStart" }).props.onClick());
    await settle();
    expect(mockRegisterDeath).not.toHaveBeenCalled();
    expect(tree!.root.findByProps({ "data-label": "ageReviewSave" })).toBeDefined();
    await act(async () => tree!.root.findAllByProps({ "data-label": "cancel" })[0].props.onClick());
    expect(mockRegisterDeath).not.toHaveBeenCalled();
    await act(async () => tree!.root.findByProps({ "data-label": "registerSaveStart" }).props.onClick());
    await settle();
    await act(async () => tree!.root.findByProps({ "data-label": "ageReviewSave" }).props.onClick());
    await settle();
    expect(mockRegisterDeath).toHaveBeenCalledTimes(1);
    await act(async () => tree!.unmount());
  });

  it("blocks a completed age above 125 before the API call", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<DeathRegistrationScreen />);
    });
    await settle();
    const findField = (field: string) => tree!.root.findByProps({ "data-field": field });
    await act(async () => {
      findField("deceased_name").props.onClick("Asha");
      findField("date_of_birth").props.onClick("1900-09-28");
      findField("date_of_death").props.onClick("2026-09-30");
    });
    await act(async () => tree!.root.findByProps({ "data-label": "sexFemale" }).props.onClick());
    await act(async () => tree!.root.findByProps({ "data-label": "registerSaveStart" }).props.onClick());
    await settle();
    expect(findField("date_of_birth").props["data-issue"]).toBe("errAge");
    expect(mockRegisterDeath).not.toHaveBeenCalled();
    await act(async () => tree!.unmount());
  });

  it("converts the birth value when precision changes: finer is cut, coarser is cleared", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<DeathRegistrationScreen />);
    });
    await settle();
    const findField = (field: string) => tree!.root.findByProps({ "data-field": field });
    const choose = (label: string) => act(async () => tree!.root.findByProps({ "data-label": label }).props.onClick());
    await act(async () => findField("date_of_birth").props.onClick("1987-04-12"));
    await choose("dobMonthYear");
    const partial = () => tree!.root.findByProps({ "data-field": "date_of_birth_partial" });
    expect(partial().props["data-value"]).toBe("1987-04");
    await choose("dobYear");
    expect(partial().props["data-value"]).toBe("1987");
    await choose("dobMonthYear");
    expect(partial().props["data-value"]).toBe("");
    await choose("dobExact");
    expect(findField("date_of_birth").props["data-value"]).toBe("");
    await choose("dobUnknown");
    expect(tree!.root.findAllByProps({ "data-field": "date_of_birth" })).toHaveLength(0);
    expect(tree!.root.findAllByProps({ "data-field": "date_of_birth_partial" })).toHaveLength(0);
    await act(async () => tree!.unmount());
  });

  it("shows a read-only calculated age beneath the selected birth date", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<DeathRegistrationScreen />);
    });
    await settle();
    const findField = (field: string) => tree!.root.findByProps({ "data-field": field });
    await act(async () => {
      findField("date_of_birth").props.onClick("2000-01-01");
      findField("date_of_death").props.onClick("2026-09-30");
    });
    expect(tree!.root.findByProps({ children: "ageAtDeathCalculated" })).toBeDefined();

    await act(async () => tree!.root.findByProps({ "data-label": "dobYear" }).props.onClick());
    await act(async () => findField("date_of_birth_partial").props.onClick("2000"));
    expect(tree!.root.findByProps({ children: "ageAtDeathRange" })).toBeDefined();
    await act(async () => tree!.unmount());
  });

  it("replaces the age stepper with a read-only estimate once a birth date is known, at every precision", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<DeathRegistrationScreen />); });
    await settle();
    const fieldCount = (name: string) => tree!.root.findAllByProps({ "data-field": name }).length;
    const findField = (name: string) => tree!.root.findByProps({ "data-field": name });
    expect(tree!.root.findByProps({ children: "fieldEstimatedAge" })).toBeDefined();
    expect(fieldCount("age_years")).toBe(0);
    await act(async () => findField("date_of_birth").props.onClick("2000-01-01"));
    expect(tree!.root.findByProps({ children: "ageNeedsDeathDate" })).toBeDefined();
    await act(async () => findField("date_of_death").props.onClick("2026-09-30"));
    expect(tree!.root.findAllByProps({ children: "ageNeedsDeathDate" })).toHaveLength(0);
    expect(tree!.root.findByProps({ children: "ageAtDeathCalculated" })).toBeDefined();
    for (const [mode, value, text] of [["dobMonthYear", "2000-01", "ageAtDeathFullRange"], ["dobYear", "2000", "ageAtDeathRange"]] as const) {
      await act(async () => tree!.root.findByProps({ "data-label": mode }).props.onClick());
      await act(async () => findField("date_of_birth_partial").props.onClick(value));
      expect(tree!.root.findByProps({ children: text })).toBeDefined();
      expect(fieldCount("age_years")).toBe(0);
    }
    await act(async () => tree!.root.findByProps({ "data-label": "dobUnknown" }).props.onClick());
    expect(fieldCount("age_years")).toBe(1);
    await act(async () => tree!.unmount());
  });

  it("does not send a manual age typed under unknown once a birth year is chosen", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<DeathRegistrationScreen />); });
    await settle();
    const field = (name: string) => tree!.root.findByProps({ "data-field": name });
    await act(async () => tree!.root.findByProps({ "data-label": "dobUnknown" }).props.onClick());
    await act(async () => field("age_years").props.onClick("39"));
    await act(async () => tree!.root.findByProps({ "data-label": "dobYear" }).props.onClick());
    await act(async () => {
      field("deceased_name").props.onClick("Asha");
      field("date_of_death").props.onClick("2026-09-30");
      field("date_of_birth_partial").props.onClick("1987");
      tree!.root.findByProps({ "data-label": "sexFemale" }).props.onClick();
    });
    await act(async () => tree!.root.findByProps({ "data-label": "registerSaveStart" }).props.onClick());
    await settle();
    expect(mockRegisterDeath).toHaveBeenCalledTimes(1);
    const body = mockRegisterDeath.mock.calls[0][1];
    expect(body.date_of_birth_partial).toBe("1987");
    expect(body).not.toHaveProperty("age_years");
    await act(async () => tree!.unmount());
  });

  it("rejects a future date of death before any API call", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<DeathRegistrationScreen />); });
    await settle();
    const field = (name: string) => tree!.root.findByProps({ "data-field": name });
    await act(async () => {
      field("deceased_name").props.onClick("Asha");
      field("date_of_death").props.onClick("2999-01-01");
      field("date_of_birth").props.onClick("1987-04-12");
      tree!.root.findByProps({ "data-label": "sexFemale" }).props.onClick();
    });
    await act(async () => tree!.root.findByProps({ "data-label": "registerSaveStart" }).props.onClick());
    expect(field("date_of_death").props["data-issue"]).toBe("errFutureDate");
    expect(mockRegisterDeath).not.toHaveBeenCalled();
    await act(async () => tree!.unmount());
  });

  it("keeps 30-day and partial day-only ages visible", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<DeathRegistrationScreen />);
    });
    await settle();
    const findField = (field: string) => tree!.root.findByProps({ "data-field": field });
    await act(async () => {
      findField("date_of_birth").props.onClick("2026-01-01");
      findField("date_of_death").props.onClick("2026-01-31");
    });
    expect(tree!.root.findByProps({ children: "ageAtDeathCalculatedFull" })).toBeDefined();

    await act(async () => tree!.root.findByProps({ "data-label": "dobMonthYear" }).props.onClick());
    await act(async () => findField("date_of_birth_partial").props.onClick("2026-01"));
    expect(tree!.root.findByProps({ children: "ageAtDeathFullRange" })).toBeDefined();
    await act(async () => tree!.unmount());
  });

  it("renders the core registration fields in collection order", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<DeathRegistrationScreen />);
    });
    await settle();
    const orderedFields = tree!.root
      .findAll((node) => typeof node.props["data-field"] === "string")
      .map((node) => node.props["data-field"]);
    expect(orderedFields).toEqual([
      "deceased_name",
      "date_of_death",
      "date_of_birth",
      "address",
      "informant_name",
      "informant_phone",
      "remarks"
    ]);
    await act(async () => tree!.unmount());
  });

  it("offers the deaths list from the add form, moves the URL to it and shows loading, not empty, while it loads", async () => {
    mockBootstrap.capabilities = { intake: false, registerDeath: true, registeredDeaths: true, coding: false, reviewing: false };
    let resolvePage!: (page: { cases: never[]; next_cursor: null }) => void;
    mockGetCases.mockReturnValueOnce(new Promise((resolve) => { resolvePage = resolve; }));
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<DeathRegistrationScreen />); });
    await settle();
    expect(tree!.root.findByProps({ "data-field": "deceased_name" })).toBeDefined();

    await act(async () => tree!.root.findByProps({ "data-label": "reportedDeaths" }).props.onClick());
    expect(mockSetParams).toHaveBeenCalledWith({ view: "mine" });
    const shown = (key: string) => tree!.root.findAll((node) => node.props.children === key).length > 0;
    expect(shown("loading")).toBe(true);
    expect(shown("noReportedDeaths")).toBe(false);

    await act(async () => { resolvePage({ cases: [], next_cursor: null }); await Promise.resolve(); });
    expect(shown("noReportedDeaths")).toBe(true);
    expect(shown("loading")).toBe(false);

    // The list's primary action opens the form.
    await act(async () => tree!.root.findByProps({ "data-label": "registerDeath" }).props.onClick());
    expect(mockSetParams).toHaveBeenLastCalledWith({ view: undefined });
    await act(async () => tree!.unmount());
  });

  it("confirms a saved registration on the deaths list", async () => {
    mockBootstrap.capabilities = { intake: false, registerDeath: true, registeredDeaths: true, coding: false, reviewing: false };
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<DeathRegistrationScreen />); });
    await settle();
    const findField = (field: string) => tree!.root.findByProps({ "data-field": field });
    await act(async () => {
      findField("deceased_name").props.onClick("Asha");
      findField("date_of_birth").props.onClick("1987-04-12");
      findField("date_of_death").props.onClick("2026-09-30");
    });
    await act(async () => tree!.root.findByProps({ "data-label": "sexFemale" }).props.onClick());
    await act(async () => tree!.root.findByProps({ "data-label": "registerSaveStart" }).props.onClick());
    await settle();

    expect(mockRegisterDeath).toHaveBeenCalledTimes(1);
    expect(mockSetParams).toHaveBeenCalledWith({ view: "mine" });
    expect(mockGetCases).toHaveBeenCalled();
    expect(tree!.root.findAll((node) => node.props.accessibilityRole === "alert" && node.props.children === "savedDeath").length).toBeGreaterThan(0);
    await act(async () => tree!.unmount());
  });

  it("lists the deaths of the interviewer's scope with status and starts an interview directly", async () => {
    mockParams = { view: "mine" };
    mockBootstrap.capabilities = { intake: true, registerDeath: true, registeredDeaths: true, coding: false, reviewing: false };
    mockGetCases.mockResolvedValue({ cases: [
      { death_id: "d1", unique_id: "U1", deceased_name: "Asha", state: "registered", project_id: "P1", site_id: "S1" },
      { death_id: "d2", unique_id: "U2", deceased_name: "Bina", state: "completed", project_id: "P1", site_id: "S1" },
    ], next_cursor: null });
    const ownPage = jest.spyOn(sharedApi, "getRegisteredDeaths");
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<DeathRegistrationScreen />); });
    await settle();

    const text = JSON.stringify(tree!.toJSON());
    expect(text).toContain("state:registered");
    expect(text).toContain("state:completed");
    expect(ownPage).not.toHaveBeenCalled();
    const starts = tree!.root.findAllByProps({ "data-label": "startInterview" });
    expect(starts).toHaveLength(1);
    await act(async () => starts[0].props.onClick());
    expect(mockPush).toHaveBeenCalledWith({ pathname: "/interview", params: { deathId: "d1" } });
    await act(async () => tree!.unmount());
  });

  describe("supervision preset", () => {
    const labels = (tree: ReturnType<typeof create>) => tree.root.findAll((n) => n.type === "button").map((n) => n.props["data-label"]);
    const panels = (tree: ReturnType<typeof create>) => tree.root.findAll((n) => n.props["data-supervision-panel"] === "true");

    async function mount(roles: string[], params: Record<string, string>, caps: Record<string, boolean>) {
      mockParams = params;
      mockBootstrap.access = { ...access("death_register"), roles };
      mockBootstrap.capabilities = { ...mockBootstrap.capabilities, ...caps };
      let tree!: ReturnType<typeof create>;
      await act(async () => { tree = create(<DeathRegistrationScreen />); });
      await settle();
      return tree;
    }

    it("offers a supervisor the switch and shows the panel under preset=supervision", async () => {
      const tree = await mount(["interviewer", "interview_supervisor"], { view: "mine", preset: "supervision" }, { intake: true, registeredDeaths: true });
      expect(labels(tree)).toContain("supervisionViewAttention");
      expect(labels(tree)).toContain("supervisionViewAll");
      expect(panels(tree)).toHaveLength(1);
      await act(async () => tree.root.findByProps({ "data-label": "supervisionViewAll" }).props.onClick());
      expect(mockSetParams).toHaveBeenCalledWith({ preset: undefined });
      await act(async () => tree.unmount());
    });

    it("keeps the plain Deaths list as the default and switches to the panel on demand", async () => {
      const tree = await mount(["interviewer", "interview_supervisor"], { view: "mine" }, { intake: true, registeredDeaths: true });
      expect(panels(tree)).toHaveLength(0);
      expect(labels(tree)).toContain("supervisionViewAttention");
      await act(async () => tree.root.findByProps({ "data-label": "supervisionViewAttention" }).props.onClick());
      expect(mockSetParams).toHaveBeenCalledWith({ preset: "supervision" });
      await act(async () => tree.unmount());
    });

    it("gives a supervisor with no deaths of their own the panel and no switch", async () => {
      const tree = await mount(["interview_supervisor"], {}, { intake: false, registerDeath: false, registeredDeaths: false });
      expect(panels(tree)).toHaveLength(1);
      expect(labels(tree)).not.toContain("supervisionViewAll");
      await act(async () => tree.unmount());
    });

    it("shows a non-supervisor no switch and no panel, whatever the URL says", async () => {
      const tree = await mount(["interviewer"], { view: "mine", preset: "supervision" }, { intake: true, registeredDeaths: true });
      expect(labels(tree)).toContain("registerDeath");
      expect(labels(tree)).not.toContain("supervisionViewAttention");
      expect(labels(tree)).not.toContain("supervisionViewAll");
      expect(panels(tree)).toHaveLength(0);
      await act(async () => tree.unmount());
    });
  });

  it("shows a reporter its own deaths from the case list without interview actions", async () => {
    mockParams = { view: "mine" };
    mockBootstrap.capabilities = { intake: false, registerDeath: true, registeredDeaths: true, coding: false, reviewing: false };
    mockBootstrap.access = { ...access("death_register"), roles: ["death_reporter"] };
    mockGetCases.mockResolvedValue({ cases: [
      { death_id: "d1", unique_id: "U1", deceased_name: "Private Name", state: "registered", project_id: "P1", site_id: "S1", registered_by_me: true, can_interview: false },
    ], next_cursor: null });
    const ownPage = jest.spyOn(sharedApi, "getRegisteredDeaths");
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<DeathRegistrationScreen />); });
    await settle();

    expect(mockGetCases).toHaveBeenCalledWith(mockBootstrap.links.intakeCases, mockBootstrap.csrf, null, undefined, false);
    expect(ownPage).not.toHaveBeenCalled();
    expect(JSON.stringify(tree!.toJSON())).toContain("Private Name");
    expect(tree!.root.findAllByProps({ "data-label": "startInterview" })).toHaveLength(0);
    expect(tree!.root.findAllByProps({ "data-label": "viewDetails" })).toHaveLength(0);
    await act(async () => tree!.root.findByProps({ "data-label": "editRegistration" }).props.onClick());
    expect(mockPush).toHaveBeenCalledWith({ pathname: "/death-registration", params: { deathId: "d1", registered: "mine" } });
    expect(mockRegisterDeath).not.toHaveBeenCalled();
    expect(mockStartDraft).not.toHaveBeenCalled();
    await act(async () => tree!.unmount());
  });

  it("redirects a reporter deep link to the deaths list without requesting case detail", async () => {
    mockParams = { deathId: "d1" };
    mockBootstrap.capabilities = { intake: false, registerDeath: true, registeredDeaths: true, coding: false, reviewing: false };
    mockBootstrap.access = access("death_register");
    mockGetCases.mockResolvedValue({ cases: [{ death_id: "d1", unique_id: "U1", deceased_name: "Private Name", registered_by_me: true }], next_cursor: null });
    const getDetail = jest.spyOn(sharedApi, "getCaseDetail");
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<DeathRegistrationScreen />); });
    await settle();

    expect(getDetail).not.toHaveBeenCalled();
    expect(mockReplace).toHaveBeenCalledWith({ pathname: "/death-registration", params: { view: "mine" } });
    expect(JSON.stringify(tree!.toJSON())).toContain("Private Name");
    await act(async () => tree!.unmount());
  });

  it("PATCHes only changed values and sends a blank clear with the detail timestamp", async () => {
    mockParams = { deathId: "d1" };
    const detail = {
      death_id: "d1", project_id: "P1", site_id: "S1", org_unit_id: null, state: "registered",
      updated_at: "2026-10-06T12:00:00+00:00", details_pending: false, other_complete_interview: false,
      deceased: { name: "Asha", sex: "female", date_of_death: "2026-09-30", date_of_birth: "1987-04-12", date_of_birth_partial: null, age_years: 39 },
      household_address: { address: "Old address" }, informant: {}, remarks: null,
      links: { self: "/case/d1", attempts: "/attempts", visit: "/visit" }
    };
    const getDetail = jest.spyOn(sharedApi, "getCaseDetail").mockResolvedValue({ case: detail } as never);
    const patchDeath = jest.spyOn(sharedApi, "requestClientJson").mockResolvedValue({
      case: { ...detail, updated_at: "2026-10-06T12:05:00+00:00" }
    } as never);
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<DeathRegistrationScreen />); });
    await settle();
    expect(getDetail).toHaveBeenCalledWith("/api/v1/intake/cases", "d1", mockBootstrap.csrf);
    await act(async () => tree!.root.findByProps({ "data-field": "address" }).props.onClick(""));
    await act(async () => tree!.root.findByProps({ "data-label": "save" }).props.onClick());
    await settle();
    expect(patchDeath).toHaveBeenCalledWith("/api/v1/intake/deaths/d1", {
      method: "PATCH",
      json: { address: "", if_updated_at: "2026-10-06T12:00:00+00:00" },
      csrf: mockBootstrap.csrf
    });
    expect(mockRegisterDeath).not.toHaveBeenCalled();
    expect(mockStartDraft).not.toHaveBeenCalled();
    await act(async () => tree!.unmount());
  });

  it("reloads an authorised detail after a stale refusal and requires a fresh edit", async () => {
    mockParams = { deathId: "d1" };
    const detail = {
      death_id: "d1", project_id: "P1", site_id: "S1", org_unit_id: null, state: "registered",
      updated_at: "2026-10-06T12:00:00+00:00", deceased: { name: "Asha", sex: "female", date_of_death: "2026-09-30", date_of_birth: "1987-04-12", age_years: 39 },
      household_address: { address: "Old address" }, informant: {}, remarks: null, links: {}
    };
    const getDetail = jest.spyOn(sharedApi, "getCaseDetail").mockResolvedValueOnce({ case: detail } as never).mockResolvedValueOnce({
      case: { ...detail, updated_at: "2026-10-06T12:05:00+00:00", household_address: { address: "New address" } }
    } as never);
    jest.spyOn(sharedApi, "requestClientJson").mockRejectedValue(new sharedApi.ApiError(409, "death_stale"));
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<DeathRegistrationScreen />); });
    await settle();
    await act(async () => tree!.root.findByProps({ "data-field": "address" }).props.onClick("My change"));
    await act(async () => tree!.root.findByProps({ "data-label": "save" }).props.onClick());
    await settle();
    expect(getDetail).toHaveBeenCalledTimes(2);
    expect(tree!.root.findByProps({ "data-field": "address" }).props["data-value"]).toBe("New address");
    expect(JSON.stringify(tree!.toJSON())).toContain("Review the latest values");
    await act(async () => tree!.unmount());
  });

  it("keeps entered values when PATCH validation fails", async () => {
    mockParams = { deathId: "d1" };
    const detail = {
      death_id: "d1", project_id: "P1", site_id: "S1", org_unit_id: null, state: "registered",
      updated_at: "2026-10-06T12:00:00+00:00", deceased: { name: "Asha", sex: "female", date_of_death: "2026-09-30", date_of_birth: "1987-04-12", age_years: 39 },
      household_address: { address: "Old address" }, informant: {}, remarks: null, links: {}
    };
    jest.spyOn(sharedApi, "getCaseDetail").mockResolvedValue({ case: detail } as never);
    jest.spyOn(sharedApi, "requestClientJson").mockRejectedValue(new sharedApi.ApiError(422, "invalid_death"));
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<DeathRegistrationScreen />); });
    await settle();
    await act(async () => tree!.root.findByProps({ "data-field": "address" }).props.onClick("Keep this edit"));
    await act(async () => tree!.root.findByProps({ "data-label": "save" }).props.onClick());
    await settle();
    expect(tree!.root.findByProps({ "data-field": "address" }).props["data-value"]).toBe("Keep this edit");
    expect(mockRegisterDeath).not.toHaveBeenCalled();
    await act(async () => tree!.unmount());
  });

  it("keeps the typed edit and its error after a business 403 and an unchanged access re-read", async () => {
    mockParams = { deathId: "d1" };
    const detail = {
      death_id: "d1", project_id: "P1", site_id: "S1", org_unit_id: null, state: "registered",
      updated_at: "2026-10-06T12:00:00+00:00", deceased: { name: "Asha", sex: "female", date_of_death: "2026-09-30", date_of_birth: "1987-04-12", age_years: 39 },
      household_address: { address: "Old address" }, informant: {}, remarks: null, links: {}
    };
    jest.spyOn(sharedApi, "getCaseDetail").mockResolvedValue({ case: detail } as never);
    // IDENTIFIER_FORBIDDEN reaches the browser as 403 `forbidden`.
    jest.spyOn(sharedApi, "requestClientJson").mockRejectedValue(new sharedApi.ApiError(403, "forbidden"));
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<DeathRegistrationScreen />); });
    await settle();
    await act(async () => tree!.root.findByProps({ "data-field": "address" }).props.onClick("Keep this edit"));
    await act(async () => tree!.root.findByProps({ "data-label": "save" }).props.onClick());
    await settle();
    const alert = () => tree!.root.findAll((node) => node.props.accessibilityRole === "alert" && node.props.children === "error");
    expect(alert().length).toBeGreaterThan(0);
    // A tab resume re-reads /me/access; AppState keeps the same bootstrap object when nothing changed.
    await act(async () => { tree!.update(<DeathRegistrationScreen />); });
    await settle();
    expect(tree!.root.findByProps({ "data-field": "address" }).props["data-value"]).toBe("Keep this edit");
    expect(alert().length).toBeGreaterThan(0);
    await act(async () => tree!.unmount());
  });

  it("refetches an own reporter record from the bounded own list after a stale conflict", async () => {
    mockParams = { deathId: "d1", registered: "mine" };
    mockBootstrap.capabilities = { intake: true, registerDeath: true, registeredDeaths: true, coding: false, reviewing: false };
    const ownPage = jest.spyOn(sharedApi, "getRegisteredDeaths").mockResolvedValue({
      deaths: [{
        death_id: "d1", unique_id: "U1", project_id: "P1", site_id: "S1", status: "registered",
        deceased_name: "Asha", deceased_sex: "female", date_of_death: "2026-09-30",
        date_of_birth: "1987-04-12", age_years: 39, address: "Old address"
      }], next_cursor: null
    });
    const getDetail = jest.spyOn(sharedApi, "getCaseDetail");
    jest.spyOn(sharedApi, "requestClientJson").mockRejectedValue(new sharedApi.ApiError(409, "death_stale"));
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<DeathRegistrationScreen />); });
    await settle();
    expect(tree!.root.findByProps({ "data-field": "address" }).props["data-value"]).toBe("Old address");
    await act(async () => tree!.root.findByProps({ "data-field": "address" }).props.onClick("My change"));
    await act(async () => tree!.root.findByProps({ "data-label": "save" }).props.onClick());
    await settle();
    expect(ownPage).toHaveBeenCalledTimes(2);
    expect(ownPage).toHaveBeenNthCalledWith(1, mockBootstrap.csrf, true, undefined, false);
    expect(ownPage).toHaveBeenNthCalledWith(2, mockBootstrap.csrf, true, undefined, false);
    expect(getDetail).not.toHaveBeenCalled();
    await act(async () => tree!.unmount());
  });

  it("hides the previous bootstrap owner before effects and discards its pending list", async () => {
    mockParams = { view: "mine" };
    mockBootstrap.capabilities = { intake: true, registerDeath: true, registeredDeaths: true, coding: false, reviewing: false };
    mockBootstrap.access = access("death_register");
    let resolveA!: (page: { cases: never[]; next_cursor: null }) => void;
    mockGetCases
      .mockReturnValueOnce(new Promise((resolve) => { resolveA = resolve; }))
      .mockResolvedValue({ cases: [{ death_id: "b1", unique_id: "UB1", project_id: "P1", site_id: "S1", state: "registered", deceased_name: "Person B" }], next_cursor: null });
    jest.spyOn(sharedApi, "getRegisteredDeaths").mockResolvedValue({
      deaths: [{
        death_id: "b1", unique_id: "UB1", project_id: "P1", site_id: "S1", status: "registered",
        deceased_name: "Person B", date_of_death: "2026-09-30", address: "B address"
      }], next_cursor: null
    } as never);
    let tree: ReturnType<typeof create>;
    let captureTransition = false;
    const transitionViews: string[] = [];
    const screen = () => (
      <Profiler id="death-registration" onRender={() => {
        if (captureTransition) transitionViews.push(JSON.stringify(tree?.toJSON()));
      }}>
        <DeathRegistrationScreen />
      </Profiler>
    );
    await act(async () => { tree = create(screen()); });
    await settle();

    const accountA = mockBootstrap;
    mockBootstrap = createBootstrap("u2", "Interviewer B");
    mockBootstrap.capabilities = { intake: true, registerDeath: true, registeredDeaths: true, coding: false, reviewing: false };
    mockBootstrap.access = access("death_register", "u2", "Interviewer B");
    captureTransition = true;
    await act(async () => tree!.update(screen()));
    captureTransition = false;
    expect(transitionViews[0]).not.toContain("Person A");
    expect(transitionViews[0]).not.toContain("UA1");

    await act(async () => {
      resolveA({ cases: [{ death_id: "a1", unique_id: "UA1", deceased_name: "Person A" }] as never[], next_cursor: null });
      await Promise.resolve();
    });
    await settle();
    expect(JSON.stringify(tree!.toJSON())).toContain("Person B");
    expect(JSON.stringify(tree!.toJSON())).not.toContain("Person A");

    // B opens its own registration; switching back to A hides B's form at once.
    mockParams = { deathId: "b1", registered: "mine" };
    await act(async () => tree!.update(screen()));
    await settle();
    expect(tree!.root.findByProps({ "data-field": "deceased_name" }).props["data-value"]).toBe("Person B");
    // A has no such registration (the mocks would otherwise answer A with B's rows).
    jest.spyOn(sharedApi, "getRegisteredDeaths").mockResolvedValue({ deaths: [], next_cursor: null });
    mockGetCases.mockResolvedValue({ cases: [], next_cursor: null });
    mockBootstrap = accountA;
    captureTransition = true;
    await act(async () => tree!.update(screen()));
    captureTransition = false;
    expect(transitionViews.at(-1)).not.toContain("Person B");
    expect(transitionViews.at(-1)).not.toContain("B address");
    await act(async () => tree!.unmount());
  });

  it("refreshes a page-two reporter edit with its source cursor and omits an absent timestamp", async () => {
    mockParams = { deathId: "d2", registered: "mine" };
    mockBootstrap.capabilities = { intake: true, registerDeath: true, registeredDeaths: true, coding: false, reviewing: false };
    const ownPage = jest.spyOn(sharedApi, "getRegisteredDeaths")
      .mockResolvedValueOnce({ deaths: [], next_cursor: "page-two" })
      .mockResolvedValueOnce({
        deaths: [{
          death_id: "d2", unique_id: "U2", project_id: "P1", site_id: "S1", status: "registered",
          deceased_name: "Asha", deceased_sex: "female", date_of_death: "2026-09-30",
          date_of_birth: "1987-04-12", age_years: 39, address: "Old address"
        }], next_cursor: null
      })
      .mockResolvedValueOnce({ deaths: [{
        death_id: "d2", unique_id: "U2", project_id: "P1", site_id: "S1", status: "registered",
        updated_at: "2026-10-06T12:05:00+00:00", deceased_name: "Asha", deceased_sex: "female",
        date_of_death: "2026-09-30", date_of_birth: "1987-04-12", age_years: 39, address: "Latest address"
      }], next_cursor: null });
    const patch = jest.spyOn(sharedApi, "requestClientJson")
      .mockRejectedValue(new sharedApi.ApiError(409, "death_stale"));
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<DeathRegistrationScreen />); });
    await settle();
    expect(ownPage).toHaveBeenNthCalledWith(2, mockBootstrap.csrf, true, "page-two", false);
    await act(async () => tree!.root.findByProps({ "data-field": "address" }).props.onClick("My change"));
    await act(async () => tree!.root.findByProps({ "data-label": "save" }).props.onClick());
    await settle();

    expect(patch).toHaveBeenCalledWith("/api/v1/intake/deaths/d2", {
      method: "PATCH", json: { address: "My change" }, csrf: mockBootstrap.csrf
    });
    expect(ownPage).toHaveBeenNthCalledWith(3, mockBootstrap.csrf, true, "page-two", false);
    expect(tree!.root.findByProps({ "data-field": "address" }).props["data-value"]).toBe("Latest address");
    await act(async () => tree!.unmount());
  });

  it("discards a pending deaths-list response when the browser is hidden", async () => {
    mockParams = { view: "mine" };
    mockBootstrap.capabilities = { intake: true, registerDeath: true, registeredDeaths: true, coding: false, reviewing: false };
    let resolvePage!: (page: { cases: never[]; next_cursor: null }) => void;
    mockGetCases.mockReturnValueOnce(new Promise((resolve) => { resolvePage = resolve; }));
    const originalDocument = global.document;
    let visibilityHandler: (() => void) | undefined;
    const testDocument = {
      visibilityState: "visible",
      addEventListener: (name: string, handler: () => void) => {
        if (name === "visibilitychange") visibilityHandler = handler;
      },
      removeEventListener: jest.fn(),
    } as unknown as Document;
    Object.defineProperty(global, "document", { configurable: true, value: testDocument });
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<DeathRegistrationScreen />); });
    await settle();

    (testDocument as { visibilityState: string }).visibilityState = "hidden";
    await act(async () => visibilityHandler?.());
    await act(async () => {
      resolvePage({ cases: [{ death_id: "d1", unique_id: "U1", deceased_name: "Private Name" }] as never[], next_cursor: null });
      await Promise.resolve();
    });
    expect(JSON.stringify(tree!.toJSON())).not.toContain("Private Name");
    expect(tree!.root.findAllByProps({ "data-label": "reportedDeaths" })).toHaveLength(0);
    await act(async () => tree!.unmount());
    Object.defineProperty(global, "document", { configurable: true, value: originalDocument });
  });

  it("allows an unrelated correction to an age-only registration", async () => {
    mockParams = { deathId: "d1", registered: "mine" };
    mockBootstrap.capabilities = { intake: true, registerDeath: true, registeredDeaths: true, coding: false, reviewing: false };
    jest.spyOn(sharedApi, "getRegisteredDeaths").mockResolvedValue({
      deaths: [{
        death_id: "d1", unique_id: "U1", project_id: "P1", site_id: "S1", status: "registered",
        updated_at: "2026-10-06T12:00:00+00:00", deceased_name: "Asha", deceased_sex: "female",
        date_of_death: "2026-09-30", date_of_birth: null, date_of_birth_partial: null, age_years: 39,
        address: "Old address"
      }], next_cursor: null
    });
    const patch = jest.spyOn(sharedApi, "requestClientJson").mockResolvedValue({
      case: { death_id: "d1", updated_at: "2026-10-06T12:05:00+00:00" }
    } as never);
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<DeathRegistrationScreen />); });
    await settle();
    expect(tree!.root.findByProps({ "data-label": "dobUnknown" })).toBeDefined();
    expect(tree!.root.findAllByProps({ "data-field": "date_of_birth" })).toHaveLength(0);
    await act(async () => tree!.root.findByProps({ "data-field": "address" }).props.onClick("New address"));
    await act(async () => tree!.root.findByProps({ "data-label": "save" }).props.onClick());
    await settle();
    expect(patch).toHaveBeenCalledWith("/api/v1/intake/deaths/d1", {
      method: "PATCH",
      json: { address: "New address", if_updated_at: "2026-10-06T12:00:00+00:00" },
      csrf: mockBootstrap.csrf
    });
    await act(async () => tree!.unmount());
  });

  it("says so when an own registration to edit is not in the own list", async () => {
    mockParams = { deathId: "gone", registered: "mine" };
    mockBootstrap.capabilities = { intake: false, registerDeath: true, registeredDeaths: true, coding: false, reviewing: false };
    const ownPage = jest.spyOn(sharedApi, "getRegisteredDeaths").mockResolvedValue({ deaths: [], next_cursor: null });
    const getDetail = jest.spyOn(sharedApi, "getCaseDetail");
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<DeathRegistrationScreen />); });
    await settle();
    expect(ownPage).toHaveBeenCalledTimes(1);
    expect(getDetail).not.toHaveBeenCalled();
    expect(JSON.stringify(tree!.toJSON())).toContain("serverError");
    await act(async () => tree!.unmount());
  });

  it("clears a saved DOB when age is retained and unknown precision is selected", async () => {
    mockParams = { deathId: "d1" };
    const detail = {
      death_id: "d1", project_id: "P1", site_id: "S1", org_unit_id: null, state: "registered",
      updated_at: "2026-10-06T12:00:00+00:00", deceased: { name: "Asha", sex: "female", date_of_death: "2026-09-30", date_of_birth: "1987-04-12", age_years: 39 },
      household_address: { address: "Old address" }, informant: {}, remarks: null, links: {}
    };
    jest.spyOn(sharedApi, "getCaseDetail").mockResolvedValue({ case: detail } as never);
    const patch = jest.spyOn(sharedApi, "requestClientJson").mockResolvedValue({
      case: { death_id: "d1", updated_at: "2026-10-06T12:05:00+00:00" }
    } as never);
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<DeathRegistrationScreen />); });
    await settle();
    await act(async () => tree!.root.findByProps({ "data-label": "dobUnknown" }).props.onClick());
    expect(tree!.root.findAllByProps({ "data-field": "date_of_birth" })).toHaveLength(0);
    await act(async () => tree!.root.findByProps({ "data-label": "save" }).props.onClick());
    await settle();
    expect(patch).toHaveBeenCalledWith("/api/v1/intake/deaths/d1", {
      method: "PATCH",
      json: { date_of_birth: "", if_updated_at: "2026-10-06T12:00:00+00:00" },
      csrf: mockBootstrap.csrf
    });
    await act(async () => tree!.unmount());
  });

  it("submits an explicitly unknown birth date with a valid age and no DOB", async () => {
    mockBootstrap.capabilities = { intake: false, registerDeath: true, registeredDeaths: false, coding: false, reviewing: false };
    mockBootstrap.access = access("death_register");
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<DeathRegistrationScreen />); });
    await settle();
    await act(async () => tree!.root.findByProps({ "data-label": "dobUnknown" }).props.onClick());
    const field = (name: string) => tree!.root.findByProps({ "data-field": name });
    await act(async () => {
      field("deceased_name").props.onClick("Asha");
      field("date_of_death").props.onClick("2026-09-30");
      field("age_years").props.onClick("39");
      tree!.root.findByProps({ "data-label": "sexFemale" }).props.onClick();
    });
    await act(async () => tree!.root.findByProps({ "data-label": "registerSaveStart" }).props.onClick());
    await settle();
    expect(mockRegisterDeath).toHaveBeenCalledWith("/api/v1/intake/deaths", expect.objectContaining({
      deceased_name: "Asha", deceased_sex: "female", date_of_death: "2026-09-30", age_years: "39"
    }), mockBootstrap.csrf);
    expect(mockRegisterDeath.mock.calls[0][1]).not.toHaveProperty("date_of_birth");
    expect(mockRegisterDeath.mock.calls[0][1]).not.toHaveProperty("date_of_birth_partial");
    await act(async () => tree!.unmount());
  });

  describe("age information is required", () => {
    const field = (tree: ReturnType<typeof create>, name: string) => tree.root.findByProps({ "data-field": name });
    async function fillAndSave(tree: ReturnType<typeof create>) {
      await act(async () => {
        field(tree, "deceased_name").props.onClick("Asha");
        field(tree, "date_of_death").props.onClick("2026-09-30");
        tree.root.findByProps({ "data-label": "sexFemale" }).props.onClick();
      });
      await act(async () => tree.root.findByProps({ "data-label": "registerSaveStart" }).props.onClick());
      await settle();
    }

    it.each([
      ["dobExact", "date_of_birth", "1987-04-12"],
      ["dobMonthYear", "date_of_birth_partial", "1987-04"],
      ["dobYear", "date_of_birth_partial", "1987"],
    ])("accepts %s", async (mode, key, value) => {
      let tree: ReturnType<typeof create>;
      await act(async () => { tree = create(<DeathRegistrationScreen />); });
      await settle();
      await act(async () => tree!.root.findByProps({ "data-label": mode }).props.onClick());
      await act(async () => field(tree!, key).props.onClick(value));
      await fillAndSave(tree!);
      expect(mockRegisterDeath).toHaveBeenCalledWith("/api/v1/intake/deaths", expect.objectContaining({ [key]: value }), mockBootstrap.csrf);
      await act(async () => tree!.unmount());
    });

    it("blocks a registration with no birth date and no age, naming the missing fields", async () => {
      let tree: ReturnType<typeof create>;
      await act(async () => { tree = create(<DeathRegistrationScreen />); });
      await settle();
      await fillAndSave(tree!);
      expect(mockRegisterDeath).not.toHaveBeenCalled();
      expect(field(tree!, "date_of_birth").props["data-issue"]).toBe("errBirthOrAge");
      await act(async () => tree!.root.findByProps({ "data-label": "dobUnknown" }).props.onClick());
      await fillAndSave(tree!);
      expect(mockRegisterDeath).not.toHaveBeenCalled();
      expect(field(tree!, "age_years").props["data-issue"]).toBe("errRequired");
      await act(async () => tree!.unmount());
    });

    it("shows the error when focus leaves the birth block empty, not while focus stays inside it", async () => {
      let tree: ReturnType<typeof create>;
      await act(async () => { tree = create(<DeathRegistrationScreen />); });
      await settle();
      const birthBlock = () => tree!.root.findAll((node) => node.props.onBlur?.name === "birthBlur")[0];
      const block = birthBlock();
      await act(async () => block.props.onBlur({ currentTarget: { contains: () => true }, relatedTarget: {} }));
      expect(field(tree!, "date_of_birth").props["data-issue"]).toBeUndefined();
      await act(async () => block.props.onBlur({ currentTarget: { contains: () => false }, relatedTarget: {} }));
      expect(field(tree!, "date_of_birth").props["data-issue"]).toBe("errBirthOrAge");
      await act(async () => field(tree!, "date_of_birth").props.onClick("1987-04-12"));
      expect(field(tree!, "date_of_birth").props["data-issue"]).toBeUndefined();
      await act(async () => birthBlock().props.onBlur({}));
      expect(field(tree!, "date_of_birth").props["data-issue"]).toBeUndefined();
      await act(async () => tree!.unmount());
    });

    describe("editing", () => {
      const legacy = {
        death_id: "d1", project_id: "P1", site_id: "S1", org_unit_id: null, state: "registered",
        updated_at: "2026-10-06T12:00:00+00:00", details_pending: false, other_complete_interview: false,
        deceased: { name: "Asha", sex: "female", date_of_death: "2026-09-30", date_of_birth: null, date_of_birth_partial: null, age_years: null },
        household_address: { address: "Old address" }, informant: {}, remarks: null,
        links: { self: "/case/d1", attempts: "/attempts", visit: "/visit" }
      };
      async function openEdit(detail: unknown) {
        mockParams = { deathId: "d1" };
        jest.spyOn(sharedApi, "getCaseDetail").mockResolvedValue({ case: detail } as never);
        const patch = jest.spyOn(sharedApi, "requestClientJson").mockResolvedValue({ case: { death_id: "d1", updated_at: "2026-10-06T12:05:00+00:00" } } as never);
        let tree: ReturnType<typeof create>;
        await act(async () => { tree = create(<DeathRegistrationScreen />); });
        await settle();
        return { tree: tree!, patch };
      }

      it("lets a stored row without age information be corrected while the age fields stay untouched", async () => {
        const { tree, patch } = await openEdit(legacy);
        await act(async () => field(tree, "address").props.onClick("New address"));
        await act(async () => tree.root.findByProps({ "data-label": "save" }).props.onClick());
        await settle();
        expect(patch).toHaveBeenCalledWith("/api/v1/intake/deaths/d1", expect.objectContaining({
          method: "PATCH", json: { address: "New address", if_updated_at: "2026-10-06T12:00:00+00:00" }
        }));
        await act(async () => tree.unmount());
      });

      it("refuses clearing the birth date of a row that had one, without an age", async () => {
        const { tree, patch } = await openEdit({ ...legacy, deceased: { ...legacy.deceased, date_of_birth: "1987-04-12" } });
        await act(async () => field(tree, "date_of_birth").props.onClick(""));
        await act(async () => tree.root.findByProps({ "data-label": "save" }).props.onClick());
        await settle();
        expect(patch).not.toHaveBeenCalled();
        expect(field(tree, "date_of_birth").props["data-issue"]).toBe("errBirthOrAge");
        await act(async () => tree.unmount());
      });
    });
  });

  it("does not restore a stale reload after the browser becomes hidden", async () => {
    mockParams = { deathId: "d1" };
    const detail = {
      death_id: "d1", project_id: "P1", site_id: "S1", org_unit_id: null, state: "registered",
      updated_at: "2026-10-06T12:00:00+00:00", deceased: { name: "Asha", sex: "female", date_of_death: "2026-09-30", date_of_birth: "1987-04-12", age_years: 39 },
      household_address: { address: "Old address" }, informant: {}, remarks: null, links: {}
    };
    let resolveReload!: (value: { case: typeof detail }) => void;
    const getDetail = jest.spyOn(sharedApi, "getCaseDetail")
      .mockResolvedValueOnce({ case: detail } as never)
      .mockReturnValueOnce(new Promise((resolve) => { resolveReload = resolve; }) as never);
    jest.spyOn(sharedApi, "requestClientJson").mockRejectedValue(new sharedApi.ApiError(409, "death_stale"));
    const originalDocument = global.document;
    let visibilityHandler: (() => void) | undefined;
    const testDocument = {
      visibilityState: "visible",
      addEventListener: (name: string, handler: () => void) => {
        if (name === "visibilitychange") visibilityHandler = handler;
      },
      removeEventListener: jest.fn(),
    } as unknown as Document;
    Object.defineProperty(global, "document", { configurable: true, value: testDocument });
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<DeathRegistrationScreen />); });
    await settle();
    await act(async () => tree!.root.findByProps({ "data-field": "address" }).props.onClick("My change"));
    await act(async () => tree!.root.findByProps({ "data-label": "save" }).props.onClick());
    await settle();
    expect(getDetail).toHaveBeenCalledTimes(2);

    (testDocument as { visibilityState: string }).visibilityState = "hidden";
    await act(async () => visibilityHandler?.());
    await act(async () => {
      resolveReload({ case: { ...detail, household_address: { address: "Fresh address" } } });
      await Promise.resolve();
    });
    expect(tree!.root.findAllByProps({ "data-field": "address" })).toHaveLength(0);
    expect(JSON.stringify(tree!.toJSON())).not.toContain("Fresh address");
    await act(async () => tree!.unmount());
    Object.defineProperty(global, "document", { configurable: true, value: originalDocument });
  });

  it("keeps typed values when the browser tab is hidden and shown again, and nothing is on screen meanwhile", async () => {
    mockParams = {};
    const originalDocument = global.document;
    let visibilityHandler: (() => void) | undefined;
    const testDocument = {
      visibilityState: "visible",
      addEventListener: (name: string, handler: () => void) => {
        if (name === "visibilitychange") visibilityHandler = handler;
      },
      removeEventListener: jest.fn(),
    } as unknown as Document;
    Object.defineProperty(global, "document", { configurable: true, value: testDocument });
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<DeathRegistrationScreen />); });
    await settle();
    await act(async () => tree!.root.findByProps({ "data-field": "deceased_name" }).props.onClick("Asha"));
    expect(tree!.root.findByProps({ "data-field": "deceased_name" }).props["data-value"]).toBe("Asha");

    (testDocument as { visibilityState: string }).visibilityState = "hidden";
    await act(async () => visibilityHandler?.());
    expect(tree!.root.findAllByProps({ "data-field": "deceased_name" })).toHaveLength(0);
    (testDocument as { visibilityState: string }).visibilityState = "visible";
    await act(async () => visibilityHandler?.());
    expect(tree!.root.findByProps({ "data-field": "deceased_name" }).props["data-value"]).toBe("Asha");
    await act(async () => tree!.unmount());
    Object.defineProperty(global, "document", { configurable: true, value: originalDocument });
  });

  it("guards leaving once something is typed, and not before", async () => {
    mockParams = {};
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<DeathRegistrationScreen />); });
    await settle();
    const clean = jest.fn();
    guardedNavigate(clean);
    expect(clean).toHaveBeenCalledTimes(1);

    await act(async () => tree!.root.findByProps({ "data-field": "deceased_name" }).props.onClick("Asha"));
    const dirty = jest.fn();
    guardedNavigate(dirty);
    expect(dirty).not.toHaveBeenCalled();
    expect(leaveDialogOpen()).toBe(true);
    stayOnPage();
    expect(leaveDialogOpen()).toBe(false);
    await act(async () => tree!.unmount());
  });

  describe("death-site GPS fix", () => {
    const FIX = { latitude: 28.613939, longitude: 77.209021, accuracy_m: 12.4 };
    const detail = {
      death_id: "d1", project_id: "P1", site_id: "S1", org_unit_id: null, state: "registered",
      updated_at: "2026-10-06T12:00:00+00:00", details_pending: false, other_complete_interview: false,
      deceased: { name: "Asha", sex: "female", date_of_death: "2026-09-30", date_of_birth: "1987-04-12", age_years: 39 },
      household_address: { address: "Old", ...FIX }, informant: {}, remarks: null,
      links: { self: "/case/d1", attempts: "/attempts", visit: "/visit" }
    };

    async function openEdit() {
      mockParams = { deathId: "d1" };
      jest.spyOn(sharedApi, "getCaseDetail").mockResolvedValue({ case: detail } as never);
      const patch = jest.spyOn(sharedApi, "requestClientJson").mockResolvedValue({ case: { ...detail, updated_at: "2026-10-06T12:05:00+00:00" } } as never);
      let tree: ReturnType<typeof create>;
      await act(async () => { tree = create(<DeathRegistrationScreen />); });
      await settle();
      return { tree: tree!, patch };
    }

    it("registers with the captured fix, and without one sends no location keys", async () => {
      for (const withFix of [true, false]) {
        mockRegisterDeath.mockClear();
        let tree: ReturnType<typeof create>;
        await act(async () => { tree = create(<DeathRegistrationScreen />); });
        await settle();
        const field = (name: string) => tree!.root.findByProps({ "data-field": name });
        await act(async () => {
          field("deceased_name").props.onClick("Asha");
          field("date_of_death").props.onClick("2026-09-30");
          field("date_of_birth").props.onClick("1987-04-12");
        });
        await act(async () => tree!.root.findByProps({ "data-label": "sexFemale" }).props.onClick());
        if (withFix) await act(async () => tree!.root.find((n) => "data-location" in n.props).props.onClick(FIX));
        await act(async () => tree!.root.findByProps({ "data-label": "registerSaveStart" }).props.onClick());
        await settle();
        const body = mockRegisterDeath.mock.calls[0][1];
        if (withFix) expect(body).toMatchObject(FIX);
        else expect(Object.keys(body).filter((key) => ["latitude", "longitude", "accuracy_m"].includes(key))).toEqual([]);
        await act(async () => tree!.unmount());
      }
    });

    it("shows the stored fix in the edit and omits it from a PATCH that does not touch it", async () => {
      const { tree, patch } = await openEdit();
      expect(JSON.parse(tree.root.find((n) => "data-location" in n.props).props["data-location"])).toEqual(FIX);
      await act(async () => tree.root.findByProps({ "data-field": "address" }).props.onClick("New"));
      await act(async () => tree.root.findByProps({ "data-label": "save" }).props.onClick());
      await settle();
      expect((patch.mock.calls[0][1] as { json: unknown }).json).toEqual({ address: "New", if_updated_at: "2026-10-06T12:00:00+00:00" });
      await act(async () => tree.unmount());
    });

    it("PATCHes a replaced fix, and explicit nulls to clear it", async () => {
      const replacement = { latitude: 19.076, longitude: 72.8777, accuracy_m: null };
      for (const [next, expected] of [
        [replacement, replacement],
        [null, { latitude: null, longitude: null, accuracy_m: null }]
      ] as const) {
        const { tree, patch } = await openEdit();
        await act(async () => tree.root.find((n) => "data-location" in n.props).props.onClick(next));
        await act(async () => tree.root.findByProps({ "data-label": "save" }).props.onClick());
        await settle();
        expect((patch.mock.calls[0][1] as { json: unknown }).json).toEqual({ ...expected, if_updated_at: "2026-10-06T12:00:00+00:00" });
        await act(async () => tree.unmount());
        jest.restoreAllMocks();
      }
    });
  });

  it.each([
    ["death_register", true],
    ["direct", false],
    ["both", true],
    ["off", false],
    [undefined, false]
  ] as const)("allows registration only when the project mode includes it: %s", async (mode, canRegister) => {
    mockBootstrap.access = access(mode);
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<DeathRegistrationScreen />);
    });
    await settle();
    expect(tree!.root.findAll((node) => node.props["data-label"] === "registerSaveStart")).toHaveLength(canRegister ? 1 : 0);
    await act(async () => tree!.unmount());
  });

  describe("registration numbers", () => {
    const TYPES = [
      { code: "mccd", label: "MCCD number", min_length: 5, max_length: 20, char_type: "letters_digits_hyphen_slash", pattern: null, example: "MCCD/2026/1", required_at_report: false, sort_order: 1 },
    ];
    const input = (tree: ReturnType<typeof create>) => tree.root.findByProps({ testID: "identifier-input-mccd" }) as unknown as { props: { value: string; onChangeText: (v: string) => void } };
    const fillCore = async (tree: ReturnType<typeof create>) => {
      const field = (name: string) => tree.root.findByProps({ "data-field": name });
      await act(async () => {
        field("deceased_name").props.onClick("Asha");
        field("date_of_death").props.onClick("2026-09-30");
        field("date_of_birth").props.onClick("1987-04-12");
      });
      await act(async () => tree.root.findByProps({ "data-label": "sexFemale" }).props.onClick());
    };

    it("upper-cases as typed and sends identifiers only when set", async () => {
      jest.spyOn(identifiersApi, "loadIdentifierTypes").mockResolvedValue(TYPES as never);
      let tree: ReturnType<typeof create>;
      await act(async () => { tree = create(<DeathRegistrationScreen />); });
      await settle();
      await fillCore(tree!);
      await act(async () => tree!.root.findByProps({ "data-label": "registerSaveStart" }).props.onClick());
      await settle();
      expect(mockRegisterDeath.mock.calls[0][1]).not.toHaveProperty("identifiers");
      mockRegisterDeath.mockClear();
      await act(async () => input(tree!).props.onChangeText(" mccd/2026/1"));
      expect(input(tree!).props.value).toBe("MCCD/2026/1");
      await act(async () => tree!.root.findByProps({ "data-label": "registerSaveStart" }).props.onClick());
      await settle();
      expect(mockRegisterDeath.mock.calls[0][1]).toMatchObject({ identifiers: { mccd: "MCCD/2026/1" } });
      await act(async () => tree!.unmount());
    });

    it("does not send a number its own rules refuse", async () => {
      jest.spyOn(identifiersApi, "loadIdentifierTypes").mockResolvedValue(TYPES as never);
      let tree: ReturnType<typeof create>;
      await act(async () => { tree = create(<DeathRegistrationScreen />); });
      await settle();
      await fillCore(tree!);
      await act(async () => input(tree!).props.onChangeText("ab"));
      await act(async () => tree!.root.findByProps({ "data-label": "registerSaveStart" }).props.onClick());
      await settle();
      expect(mockRegisterDeath).not.toHaveBeenCalled();
      expect(JSON.stringify(tree!.toJSON())).toContain("idErrLength");
      await act(async () => tree!.unmount());
    });

    it("pauses on a duplicate warning: Continue goes on, nothing was blocked", async () => {
      jest.spyOn(identifiersApi, "loadIdentifierTypes").mockResolvedValue(TYPES as never);
      mockRegisterDeath.mockResolvedValue({
        case: { death_id: "d1", links: { start_interview: "/s" } },
        warnings: [{ code: "identifier_in_use", field: "identifiers.mccd", message: "In use on another case." }],
      });
      let tree: ReturnType<typeof create>;
      await act(async () => { tree = create(<DeathRegistrationScreen />); });
      await settle();
      await fillCore(tree!);
      await act(async () => input(tree!).props.onChangeText("mccd/2026/1"));
      await act(async () => tree!.root.findByProps({ "data-label": "registerSaveStart" }).props.onClick());
      await settle();
      expect(JSON.stringify(tree!.toJSON())).toContain("In use on another case.");
      expect(mockStartDraft).not.toHaveBeenCalled();
      await act(async () => tree!.root.findByProps({ "data-label": "idWarnContinue" }).props.onClick());
      await settle();
      expect(mockStartDraft).toHaveBeenCalledTimes(1);
      await act(async () => tree!.unmount());
    });

    it("Edit on a duplicate warning reopens the saved case in the edit form", async () => {
      jest.spyOn(identifiersApi, "loadIdentifierTypes").mockResolvedValue(TYPES as never);
      mockRegisterDeath.mockResolvedValue({
        case: { death_id: "d1", links: {} },
        warnings: [{ code: "identifier_in_use", field: "identifiers.mccd", message: "In use." }],
      });
      let tree: ReturnType<typeof create>;
      await act(async () => { tree = create(<DeathRegistrationScreen />); });
      await settle();
      await fillCore(tree!);
      await act(async () => input(tree!).props.onChangeText("mccd/2026/1"));
      await act(async () => tree!.root.findByProps({ "data-label": "registerSaveStart" }).props.onClick());
      await settle();
      await act(async () => tree!.root.findByProps({ "data-label": "idWarnEdit" }).props.onClick());
      expect(mockReplace).toHaveBeenCalledWith({ pathname: "/death-registration", params: { deathId: "d1" } });
      await act(async () => tree!.unmount());
    });

    it("prefills an edit from the stored numbers and PATCHes only the changed code", async () => {
      jest.spyOn(identifiersApi, "loadIdentifierTypes").mockResolvedValue([
        ...TYPES, { ...TYPES[0], code: "cert", label: "Certificate", sort_order: 2 },
      ] as never);
      mockParams = { deathId: "d1" };
      const detail = {
        death_id: "d1", project_id: "P1", site_id: "S1", org_unit_id: null, state: "registered",
        updated_at: "2026-10-06T12:00:00+00:00", details_pending: false, other_complete_interview: false,
        deceased: { name: "Asha", sex: "female", date_of_death: "2026-09-30", date_of_birth: "1987-04-12", age_years: 39 },
        household_address: { address: "A" }, informant: {}, remarks: null, links: {},
        identifiers: [{ code: "mccd", label: "MCCD number", value: "MCCD/2026/1" }],
      };
      jest.spyOn(sharedApi, "getCaseDetail").mockResolvedValue({ case: detail } as never);
      const patch = jest.spyOn(sharedApi, "requestClientJson").mockResolvedValue({ case: { ...detail, updated_at: "2026-10-06T12:05:00+00:00" } } as never);
      let tree: ReturnType<typeof create>;
      await act(async () => { tree = create(<DeathRegistrationScreen />); });
      await settle();
      expect(input(tree!).props.value).toBe("MCCD/2026/1");
      const cert = tree!.root.findByProps({ testID: "identifier-input-cert" }) as unknown as { props: { onChangeText: (v: string) => void } };
      await act(async () => cert.props.onChangeText("c-77/ab"));
      await act(async () => tree!.root.findByProps({ "data-label": "save" }).props.onClick());
      await settle();
      expect(patch).toHaveBeenCalledWith("/api/v1/intake/deaths/d1", {
        method: "PATCH",
        json: { identifiers: { cert: "C-77/AB" }, if_updated_at: "2026-10-06T12:00:00+00:00" },
        csrf: mockBootstrap.csrf,
      });
      await act(async () => tree!.unmount());
    });

    it("never sends a change for a deactivated type and shows its value read-only", async () => {
      jest.spyOn(identifiersApi, "loadIdentifierTypes").mockResolvedValue(TYPES as never);
      mockParams = { deathId: "d1" };
      const detail = {
        death_id: "d1", project_id: "P1", site_id: "S1", org_unit_id: null, state: "registered",
        updated_at: "2026-10-06T12:00:00+00:00", details_pending: false, other_complete_interview: false,
        deceased: { name: "Asha", sex: "female", date_of_death: "2026-09-30", date_of_birth: "1987-04-12", age_years: 39 },
        household_address: { address: "A" }, informant: {}, remarks: null, links: {},
        identifiers: [
          { code: "mccd", label: "MCCD number", value: "MCCD/2026/1" },
          { code: "old", label: "Old certificate", value: "OLD-77" },
        ],
      };
      jest.spyOn(sharedApi, "getCaseDetail").mockResolvedValue({ case: detail } as never);
      const patch = jest.spyOn(sharedApi, "requestClientJson").mockResolvedValue({ case: { ...detail, updated_at: "2026-10-06T12:05:00+00:00" } } as never);
      let tree: ReturnType<typeof create>;
      await act(async () => { tree = create(<DeathRegistrationScreen />); });
      await settle();
      expect(tree!.root.findAllByProps({ testID: "identifier-input-old" })).toHaveLength(0);
      expect(tree!.root.findAllByProps({ testID: "identifier-inactive" }).length).toBeGreaterThan(0);
      expect(JSON.stringify(tree!.toJSON())).toContain("OLD-77");
      await act(async () => tree!.root.findByProps({ "data-field": "deceased_name" }).props.onClick("Asha K"));
      await act(async () => tree!.root.findByProps({ "data-label": "save" }).props.onClick());
      await settle();
      expect(patch).toHaveBeenCalledTimes(1);
      const body = (patch.mock.calls[0][1] as { json: Record<string, unknown> }).json;
      expect(body).toMatchObject({ deceased_name: "Asha K" });
      expect(body).not.toHaveProperty("identifiers");
      await act(async () => tree!.unmount());
    });

    it("says so when the types cannot be loaded instead of hiding the section silently", async () => {
      jest.spyOn(identifiersApi, "loadIdentifierTypes").mockRejectedValue(new Error("offline"));
      let tree: ReturnType<typeof create>;
      await act(async () => { tree = create(<DeathRegistrationScreen />); });
      await settle();
      expect(tree!.root.findAllByProps({ testID: "identifier-types-error" }).length).toBeGreaterThan(0);
      expect(JSON.stringify(tree!.toJSON())).toContain("idTypesLoadFailed");
      await act(async () => tree!.unmount());
    });

    it("shows a server refusal under the field it names", async () => {
      jest.spyOn(identifiersApi, "loadIdentifierTypes").mockResolvedValue(TYPES as never);
      mockRegisterDeath.mockRejectedValue(new sharedApi.ApiError(422, "invalid_registration", undefined, undefined, { error: "MCCD number must look like MCCD/2026/1", fields: ["identifiers.mccd"] }));
      let tree: ReturnType<typeof create>;
      await act(async () => { tree = create(<DeathRegistrationScreen />); });
      await settle();
      await fillCore(tree!);
      await act(async () => input(tree!).props.onChangeText("zzzzz"));
      await act(async () => tree!.root.findByProps({ "data-label": "registerSaveStart" }).props.onClick());
      await settle();
      expect(JSON.stringify(tree!.toJSON())).toContain("MCCD number must look like MCCD/2026/1");
      await act(async () => tree!.unmount());
    });

    it("gives a badge-only viewer no input unless the case says they may write", async () => {
      jest.spyOn(identifiersApi, "loadIdentifierTypes").mockResolvedValue(TYPES as never);
      mockParams = { deathId: "d1" };
      const detail = {
        death_id: "d1", project_id: "P1", site_id: "S1", state: "registered", updated_at: "t", details_pending: false,
        deceased: { name: "Asha", sex: "female", date_of_death: "2026-09-30", date_of_birth: "1987-04-12", age_years: 39 },
        household_address: {}, informant: {}, links: {}, identifiers: [{ code: "mccd", label: "MCCD number", present: true }],
      };
      jest.spyOn(sharedApi, "getCaseDetail").mockResolvedValue({ case: detail } as never);
      let tree: ReturnType<typeof create>;
      await act(async () => { tree = create(<DeathRegistrationScreen />); });
      await settle();
      expect(tree!.root.findAllByType(TextInput)).toHaveLength(0);
      await act(async () => tree!.unmount());
    });
  });
});
