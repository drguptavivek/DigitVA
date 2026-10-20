import React, { type ReactNode } from "react";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";

import {
  createMentorInstituteStaff,
  getMentoringSummary,
  listMentorInstituteStaff,
  removeMentorInstituteStaff,
  type MentoringSummary,
} from "../src/api";
import { openServerPage } from "../src/web/roleHome";

const mockPush = jest.fn();

jest.mock("expo-router", () => ({
  useRouter: () => ({ push: mockPush }),
}));

let mockBootstrap: any;

jest.mock("../src/AppState", () => ({
  useAppState: () => ({ bootstrap: mockBootstrap }),
}));

jest.mock("../src/web/common", () => ({
  WebShell: ({ children }: { children: ReactNode }) => <>{children}</>,
  browserErrorText: (e: any) => e?.message || "server error",
}));

jest.mock("../src/web/roleHome", () => {
  const actual = jest.requireActual("../src/web/roleHome");
  return {
    ...actual,
    openServerPage: jest.fn(),
  };
});

jest.mock("../src/api", () => {
  const actual = jest.requireActual("../src/api");
  return {
    ...actual,
    getMentoringSummary: jest.fn(),
    listMentorInstituteStaff: jest.fn(),
    createMentorInstituteStaff: jest.fn(),
    removeMentorInstituteStaff: jest.fn(),
  };
});

import MentoringScreen from "../src/web/MentoringScreen";

function allText(treeOrInstance: ReactTestRenderer | ReactTestInstance): string {
  const out: string[] = [];
  const walk = (node: any) => {
    if (typeof node === "string") {
      out.push(node);
    } else if (node?.children) {
      node.children.forEach(walk);
    }
  };
  const json = "toJSON" in treeOrInstance ? treeOrInstance.toJSON() : treeOrInstance;
  walk(json);
  return out.join(" ");
}

function findButtonsByLabel(treeOrRoot: ReactTestRenderer | ReactTestInstance, label: string): ReactTestInstance[] {
  const root = "root" in treeOrRoot ? treeOrRoot.root : treeOrRoot;
  return root.findAll(
    (node) =>
      node.props.accessibilityRole === "button" &&
      node.props.accessibilityLabel === label &&
      (!node.parent || node.parent.props.accessibilityRole !== "button"),
  );
}

function pressButton(button: ReactTestInstance) {
  if (button.props.onPress) {
    button.props.onPress();
  } else if (button.props.onClick) {
    button.props.onClick();
  }
}

async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe("MentoringScreen", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockBootstrap = {
      user: { user_id: "user-1", name: "Dr. Alice" },
      csrf: { header: "X-CSRFToken", token: "test-csrf-token" },
      access: {
        user: { user_id: "user-1", name: "Dr. Alice" },
        is_admin: false,
        roles: ["coder"],
        demo_coding: { available: false, project_ids: [] },
        projects: [
          {
            project_id: "PRJ-1",
            project_name: "Project State A",
            has_tree: true,
            grants: [
              {
                role: "coder",
                scope: "org_unit",
                org_unit_id: "unit-1",
                unit_name: "Bhopal District",
                codes: true,
                active: true,
                source: "assigned",
              },
            ],
            sites: [{ site_id: "site-1", site_name: "Site One", roles: ["coder"] }],
            actions: { interview: [], register_death: [] },
            units: [
              {
                org_unit_id: "unit-1",
                unit_code: "BPL-DIST",
                unit_name: "Bhopal District",
                level_code: "district",
                path: "1",
                is_active: true,
                selectable: true,
                roles: ["coder"],
                can_code: true,
              },
            ],
            levels: [{ level_code: "district", level_name: "District", depth: 1 }],
          },
        ],
      },
    };
  });

  it("renders mentor staff view with institute, supported districts, 'Within Area' roles, and layman guide", async () => {
    const summary: MentoringSummary = {
      is_member: true,
      is_institute_admin: false,
      institutes: [
        {
          institute_code: "AIIMS_BPL",
          institute_name: "AIIMS Bhopal",
          is_active: true,
          is_admin: false,
          districts: [
            {
              project_id: "PRJ-1",
              project_name: "Project State A",
              org_unit_id: "unit-1",
              unit_code: "BPL-DIST",
              unit_name: "Bhopal District",
            },
          ],
        },
      ],
      languages: [],
    };

    (getMentoringSummary as jest.Mock).mockResolvedValue(summary);

    let renderer!: ReactTestRenderer;
    await act(async () => {
      renderer = create(<MentoringScreen />);
    });
    await settle();

    const text = allText(renderer.root);

    // Section 1: Guide
    expect(text).toContain("Mentoring Institution Guide");
    expect(text).toContain("3. Coding");
    expect(text).toContain("4. Review");
    expect(text).toContain("5. Summary Reports");
    expect(text).toContain("District Programme Managers or Project Leads");

    // Section 2: Institute & districts
    expect(text).toContain("AIIMS Bhopal");
    expect(text).toContain("AIIMS_BPL");
    expect(text).toContain("Faculty / Mentor Staff");
    expect(text).toContain("Bhopal District (BPL-DIST) in Project State A");

    // Section 3: Assigned roles & Within Area
    expect(text).toContain("Project State A (PRJ-1)");
    expect(text).toContain("Within Area: Bhopal District");

    // Action button: 3. Coding
    const codingButtons = findButtonsByLabel(renderer.root, "3. Coding");
    expect(codingButtons.length).toBeGreaterThan(0);
    await act(async () => {
      pressButton(codingButtons[0]);
    });
    expect(mockPush).toHaveBeenCalledWith({
      pathname: "/coding",
      params: { project: "PRJ-1" },
    });

    // Help guide button
    const helpButtons = findButtonsByLabel(renderer.root, "Help & Guide for Mentoring Staff");
    expect(helpButtons.length).toBeGreaterThan(0);
    await act(async () => {
      pressButton(helpButtons[0]);
    });
    expect(openServerPage).toHaveBeenCalledWith("user-1", "/help/mentoring-institutes");
  });

  it("renders pending-grant mentor view and explains who assigns district roles", async () => {
    // User belongs to institute, but has no grants in bootstrap
    mockBootstrap.access.projects = [];

    const summary: MentoringSummary = {
      is_member: true,
      is_institute_admin: false,
      institutes: [
        {
          institute_code: "AIIMS_BPL",
          institute_name: "AIIMS Bhopal",
          is_active: true,
          is_admin: false,
          districts: [
            {
              project_id: "PRJ-1",
              project_name: "Project State A",
              org_unit_id: "unit-1",
              unit_code: "BPL-DIST",
              unit_name: "Bhopal District",
            },
          ],
        },
      ],
      languages: [],
    };

    (getMentoringSummary as jest.Mock).mockResolvedValue(summary);

    let renderer!: ReactTestRenderer;
    await act(async () => {
      renderer = create(<MentoringScreen />);
    });
    await settle();

    const text = allText(renderer.root);

    // Reassuring layman status box
    expect(text).toContain(
      "Your account is linked to your Mentoring Institution, but no District or Block role has been assigned yet. Ask the District Programme Manager or Project Lead of your supported district to assign your Coding, Review, or Viewer role.",
    );
  });

  it("renders institute admin view, lists staff, adds new staff, and removes staff with confirmation", async () => {
    const summary: MentoringSummary = {
      is_member: true,
      is_institute_admin: true,
      institutes: [
        {
          institute_code: "AIIMS_BPL",
          institute_name: "AIIMS Bhopal",
          is_active: true,
          is_admin: true,
          districts: [
            {
              project_id: "PRJ-1",
              project_name: "Project State A",
              org_unit_id: "unit-1",
              unit_code: "BPL-DIST",
              unit_name: "Bhopal District",
            },
          ],
        },
      ],
      languages: [
        { language_code: "hi", language_name: "Hindi" },
        { language_code: "en", language_name: "English" },
      ],
    };

    const initialStaff = [
      {
        user_id: "user-1",
        email: "alice@aiims.edu",
        name: "Dr. Alice",
        job_title: "Professor",
        is_admin: true,
        account_status: "active",
      },
      {
        user_id: "user-2",
        email: "sharma@aiims.edu",
        name: "Dr. Sharma",
        job_title: "Senior Resident",
        is_admin: false,
        account_status: "active",
      },
    ];

    (getMentoringSummary as jest.Mock).mockResolvedValue(summary);
    (listMentorInstituteStaff as jest.Mock).mockResolvedValue({ staff: initialStaff });

    let renderer!: ReactTestRenderer;
    await act(async () => {
      renderer = create(<MentoringScreen />);
    });
    await settle();

    const text = allText(renderer.root);

    // Section 4: Roster
    expect(text).toContain("Staff Roster — AIIMS Bhopal");
    expect(text).toContain("Dr. Alice");
    expect(text).toContain("Dr. Sharma");
    expect(text).toContain("sharma@aiims.edu");
    expect(text).toContain("Senior Resident");

    // Self user-1 has no remove button, but user-2 has one
    const removeButtons = findButtonsByLabel(renderer.root, "Remove from Institute");
    expect(removeButtons.length).toBe(1);

    // Add new staff flow
    const addStaffToggle = findButtonsByLabel(renderer.root, "Add Faculty / Resident Staff");
    expect(addStaffToggle.length).toBeGreaterThan(0);
    await act(async () => {
      pressButton(addStaffToggle[0]);
    });

    // Inputs inside the form
    const textInputs = renderer.root.findAllByType("TextInput" as any);
    expect(textInputs.length).toBeGreaterThanOrEqual(3);

    // Find inputs by placeholder or value
    const nameInput = textInputs.find((i) => i.props.placeholder === "Dr. Full Name");
    const emailInput = textInputs.find((i) => i.props.keyboardType === "email-address" && i.props.value === "");
    const confirmInput = textInputs.filter((i) => i.props.keyboardType === "email-address")[1];
    const jobInput = textInputs.find((i) => (i.props.placeholder || "").includes("Assistant Professor"));

    expect(nameInput).toBeDefined();
    expect(emailInput).toBeDefined();
    expect(confirmInput).toBeDefined();

    await act(async () => {
      nameInput!.props.onChangeText("Dr. New Member");
      emailInput!.props.onChangeText("new.member@aiims.edu");
      confirmInput!.props.onChangeText("new.member@aiims.edu");
      jobInput?.props.onChangeText("Junior Resident");
    });

    // Select a language chip (Hindi)
    const hindiChips = findButtonsByLabel(renderer.root, "Hindi");
    expect(hindiChips.length).toBeGreaterThan(0);
    await act(async () => {
      pressButton(hindiChips[0]);
    });

    const newStaffMember = {
      user_id: "user-3",
      email: "new.member@aiims.edu",
      name: "Dr. New Member",
      job_title: "Junior Resident",
      is_admin: false,
      account_status: "invited",
    };
    (createMentorInstituteStaff as jest.Mock).mockResolvedValue({ staff: newStaffMember });

    const submitButton = findButtonsByLabel(renderer.root, "Send Invitation");
    expect(submitButton.length).toBeGreaterThan(0);
    await act(async () => {
      pressButton(submitButton[0]);
    });
    await settle();

    expect(createMentorInstituteStaff).toHaveBeenCalledWith(
      "AIIMS_BPL",
      {
        name: "Dr. New Member",
        email: "new.member@aiims.edu",
        email_confirm: "new.member@aiims.edu",
        job_title: "Junior Resident",
        languages: ["hi"],
      },
      mockBootstrap.csrf,
    );

    const updatedText = allText(renderer.root);
    expect(updatedText).toContain("Invitation sent to new.member@aiims.edu");
    expect(updatedText).toContain("Dr. New Member");

    // Remove staff member flow with confirmation
    const currentRemoveButtons = findButtonsByLabel(renderer.root, "Remove from Institute");
    expect(currentRemoveButtons.length).toBe(2); // user-2 and user-3

    // Click remove on first removable staff (Dr. Sharma)
    await act(async () => {
      pressButton(currentRemoveButtons[0]);
    });

    const confirmText = allText(renderer.root);
    expect(confirmText).toContain("Remove Dr. Sharma from AIIMS Bhopal?");
    expect(confirmText).toContain("Any active mentoring roles they hold in this institute's districts will be deactivated.");

    (removeMentorInstituteStaff as jest.Mock).mockResolvedValue({
      user_id: "user-2",
      account_deactivated: false,
      grants_deactivated: 1,
    });

    const confirmButton = findButtonsByLabel(renderer.root, "Confirm Removal");
    expect(confirmButton.length).toBe(1);
    await act(async () => {
      pressButton(confirmButton[0]);
    });
    await settle();

    expect(removeMentorInstituteStaff).toHaveBeenCalledWith("AIIMS_BPL", "user-2", mockBootstrap.csrf);
    const postRemoveText = allText(renderer.root);
    expect(postRemoveText).toContain("Dr. Sharma removed from AIIMS Bhopal.");
  });
});
