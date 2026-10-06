import React, { Profiler, type ReactNode } from "react";
import { act, create } from "react-test-renderer";

let mockLocale = "en";
let mockParams: Record<string, string> = {};
const mockReplace = jest.fn();

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

jest.mock("expo-router", () => ({ useRouter: () => ({ replace: mockReplace, back: jest.fn() }), useLocalSearchParams: () => mockParams }));
jest.mock("../src/AppState", () => ({ useAppState: () => ({ bootstrap: mockBootstrap }) }));
jest.mock("../src/i18n", () => ({ t: (key: string) => (mockLocale === "hi" ? `hi:${key}` : key) }));
jest.mock("../src/ui", () => ({
  Button: ({ label, onPress }: { label: string; onPress: () => void }) => <button data-label={label} onClick={onPress} />,
  useUiStyles: () => ({ error: {}, muted: {}, input: {}, card: {}, text: {}, row: {} })
}));
jest.mock("../src/web/common", () => ({ WebShell: ({ children }: { children: ReactNode }) => <>{children}</>, browserErrorText: () => "error" }));
jest.mock("../src/web/registrationControls", () => {
  const React = require("react") as typeof import("react");
  return {
    RegistrationFieldControl: ({ field, value, dateAppearance, onChange, onIssue, issueMessage }: { field: string; value: string; dateAppearance?: string; onChange: (value: string) => void; onIssue: (issue?: string) => void; issueMessage?: string }) =>
      React.createElement("button", { "data-field": field, "data-value": value, "data-appearance": dateAppearance, "data-issue": issueMessage, onClick: onChange as unknown as () => void, onIssue } as Record<string, unknown>)
  };
});
jest.mock("../src/client/api", () => ({
  INTAKE_API: "/api/v1/intake",
  getIntakeContext: jest.fn(),
  registerDeath: jest.fn(),
  startDraft: jest.fn()
}));

import DeathRegistrationScreen from "../src/web/DeathRegistrationScreen";
import { registerDeath, startDraft } from "../src/client/api";
import * as sharedApi from "../src/api";

const mockRegisterDeath = registerDeath as jest.Mock;
const mockStartDraft = startDraft as jest.Mock;

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
    jest.restoreAllMocks();
    jest.clearAllMocks();
    mockBootstrap = createBootstrap();
    mockBootstrap.capabilities = { intake: true, registerDeath: true, registeredDeaths: false, coding: false, reviewing: false };
    mockBootstrap.access = access("death_register");
    mockRegisterDeath.mockResolvedValue({ case: { death_id: "d1" } });
    mockStartDraft.mockResolvedValue({ draft: { draft_id: "draft1" } });
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
    expect(issueFor("date_of_birth")).toBe("errRequired");
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
    expect(tree!.root.findByProps({ "data-field": "date_of_birth" }).props["data-issue"]).toBe("hi:errRequired");
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

  it("clears a partial value when birth precision changes", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<DeathRegistrationScreen />);
    });
    await settle();
    await act(async () => tree!.root.findByProps({ "data-label": "dobMonthYear" }).props.onClick());
    const partial = () => tree!.root.findByProps({ "data-field": "date_of_birth_partial" });
    await act(async () => partial().props.onClick("1987-04"));
    expect(partial().props["data-value"]).toBe("1987-04");
    await act(async () => tree!.root.findByProps({ "data-label": "dobYear" }).props.onClick());
    expect(partial().props["data-value"]).toBe("");
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
      "date_of_birth",
      "date_of_death",
      "address",
      "informant_name",
      "informant_phone",
      "remarks"
    ]);
    await act(async () => tree!.unmount());
  });

  it("shows only the reporter's bounded own-death page without loading interview data", async () => {
    mockParams = { view: "mine" };
    mockBootstrap.capabilities = { intake: false, registerDeath: true, registeredDeaths: true, coding: false, reviewing: false };
    mockBootstrap.access = access("death_register");
    const ownPage = jest.spyOn(sharedApi, "getRegisteredDeaths").mockResolvedValue({
      deaths: [{ death_id: "d1", unique_id: "U1", deceased_name: "Private Name", date_of_death: "2026-09-30" }],
      next_cursor: null,
    });
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<DeathRegistrationScreen />); });
    await settle();

    expect(ownPage).toHaveBeenCalledWith(mockBootstrap.csrf, false, undefined);
    expect(JSON.stringify(tree!.toJSON())).toContain("Private Name");
    expect(mockRegisterDeath).not.toHaveBeenCalled();
    expect(mockStartDraft).not.toHaveBeenCalled();
    ownPage.mockRestore();
    await act(async () => tree!.unmount());
  });

  it("redirects a reporter deep link to the bounded own list without requesting case detail", async () => {
    mockParams = { deathId: "d1" };
    mockBootstrap.capabilities = { intake: false, registerDeath: true, registeredDeaths: true, coding: false, reviewing: false };
    mockBootstrap.access = access("death_register");
    const ownPage = jest.spyOn(sharedApi, "getRegisteredDeaths").mockResolvedValue({
      deaths: [{ death_id: "d1", unique_id: "U1", deceased_name: "Private Name" }],
      next_cursor: null,
    });
    const getDetail = jest.spyOn(sharedApi, "getCaseDetail");
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<DeathRegistrationScreen />); });
    await settle();

    expect(getDetail).not.toHaveBeenCalled();
    expect(mockReplace).toHaveBeenCalledWith({ pathname: "/death-registration", params: { view: "mine" } });
    expect(ownPage).toHaveBeenCalledWith(mockBootstrap.csrf, false, undefined);
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

  it("refetches an own reporter record from the bounded own list after a stale conflict", async () => {
    mockParams = { view: "mine" };
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
    await act(async () => tree!.root.findByProps({ "data-label": "editRegistration" }).props.onClick());
    await act(async () => tree!.root.findByProps({ "data-field": "address" }).props.onClick("My change"));
    await act(async () => tree!.root.findByProps({ "data-label": "save" }).props.onClick());
    await settle();
    expect(ownPage).toHaveBeenCalledTimes(2);
    expect(ownPage).toHaveBeenNthCalledWith(1, mockBootstrap.csrf, true, undefined);
    expect(ownPage).toHaveBeenNthCalledWith(2, mockBootstrap.csrf, true, undefined);
    expect(getDetail).not.toHaveBeenCalled();
    await act(async () => tree!.unmount());
  });

  it("hides the previous bootstrap owner before effects and discards its pending list", async () => {
    mockParams = { view: "mine" };
    mockBootstrap.capabilities = { intake: true, registerDeath: true, registeredDeaths: true, coding: false, reviewing: false };
    mockBootstrap.access = access("death_register");
    let resolveA!: (page: { deaths: never[]; next_cursor: null }) => void;
    const list = jest.spyOn(sharedApi, "getRegisteredDeaths")
      .mockReturnValueOnce(new Promise((resolve) => { resolveA = resolve; }) as never)
      .mockResolvedValue({
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
      resolveA({ deaths: [{ death_id: "a1", unique_id: "UA1", deceased_name: "Person A" }] as never[], next_cursor: null });
      await Promise.resolve();
    });
    await settle();
    expect(JSON.stringify(tree!.toJSON())).toContain("Person B");
    expect(JSON.stringify(tree!.toJSON())).not.toContain("Person A");

    await act(async () => tree!.root.findByProps({ "data-label": "editRegistration" }).props.onClick());
    expect(tree!.root.findByProps({ "data-field": "deceased_name" }).props["data-value"]).toBe("Person B");
    mockBootstrap = accountA;
    captureTransition = true;
    await act(async () => tree!.update(screen()));
    captureTransition = false;
    expect(transitionViews.at(-1)).not.toContain("Person B");
    expect(transitionViews.at(-1)).not.toContain("B address");
    expect(list).toHaveBeenCalledTimes(2);
    await act(async () => tree!.unmount());
  });

  it("refreshes a page-two reporter edit with its source cursor and omits an absent timestamp", async () => {
    mockParams = { view: "mine" };
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
    await act(async () => tree!.root.findByProps({ "data-label": "loadMore" }).props.onClick());
    await settle();
    await act(async () => tree!.root.findByProps({ "data-label": "editRegistration" }).props.onClick());
    await act(async () => tree!.root.findByProps({ "data-field": "address" }).props.onClick("My change"));
    await act(async () => tree!.root.findByProps({ "data-label": "save" }).props.onClick());
    await settle();

    expect(patch).toHaveBeenCalledWith("/api/v1/intake/deaths/d2", {
      method: "PATCH", json: { address: "My change" }, csrf: mockBootstrap.csrf
    });
    expect(ownPage).toHaveBeenNthCalledWith(3, mockBootstrap.csrf, true, "page-two");
    expect(tree!.root.findByProps({ "data-field": "address" }).props["data-value"]).toBe("Latest address");
    await act(async () => tree!.unmount());
  });

  it("discards a pending own-list response when the browser is hidden", async () => {
    mockParams = { view: "mine" };
    mockBootstrap.capabilities = { intake: true, registerDeath: true, registeredDeaths: true, coding: false, reviewing: false };
    let resolvePage!: (page: { deaths: never[]; next_cursor: null }) => void;
    jest.spyOn(sharedApi, "getRegisteredDeaths").mockReturnValueOnce(
      new Promise((resolve) => { resolvePage = resolve; }) as never
    );
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
      resolvePage({ deaths: [{ death_id: "d1", unique_id: "U1", deceased_name: "Private Name" }] as never[], next_cursor: null });
      await Promise.resolve();
    });
    expect(JSON.stringify(tree!.toJSON())).not.toContain("Private Name");
    expect(tree!.root.findAllByProps({ "data-label": "myRegisteredDeaths" })).toHaveLength(0);
    await act(async () => tree!.unmount());
    Object.defineProperty(global, "document", { configurable: true, value: originalDocument });
  });

  it("allows an unrelated correction to an age-only registration", async () => {
    mockParams = { view: "mine" };
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
    await act(async () => tree!.root.findByProps({ "data-label": "editRegistration" }).props.onClick());
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
});
