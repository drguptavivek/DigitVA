import React, { type ReactNode } from "react";
import { act, create } from "react-test-renderer";

let mockLocale = "en";

const mockBootstrap = {
  user: { user_id: "u1", name: "Interviewer" },
  csrf: { header: "X-CSRFToken", token: "csrf" },
  capabilities: { intake: true, coding: false, reviewing: false },
  links: { intakeCases: "/api/v1/intake/cases", intakeDrafts: "/api/v1/intake/drafts" }
};

jest.mock("expo-router", () => ({ useRouter: () => ({ replace: jest.fn(), back: jest.fn() }) }));
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
import { getIntakeContext, registerDeath, startDraft } from "../src/client/api";

const mockGetIntakeContext = getIntakeContext as jest.Mock;
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
    jest.clearAllMocks();
    mockGetIntakeContext.mockResolvedValue({ context: [{ project_id: "P1", site_id: "S1", web_intake_mode: "death_register" }] });
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

  it.each([
    ["death_register", true],
    ["direct", false],
    ["both", true],
    ["off", false],
    [undefined, false]
  ] as const)("allows registration only when the project mode includes it: %s", async (mode, canRegister) => {
    mockGetIntakeContext.mockResolvedValue({ context: [{ project_id: "P1", site_id: "S1", web_intake_mode: mode }] });
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<DeathRegistrationScreen />);
    });
    await settle();
    expect(tree!.root.findAll((node) => node.props["data-label"] === "registerSaveStart")).toHaveLength(canRegister ? 1 : 0);
    await act(async () => tree!.unmount());
  });
});
