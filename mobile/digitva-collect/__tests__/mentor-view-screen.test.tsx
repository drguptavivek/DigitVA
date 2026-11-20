import React, { type ReactNode } from "react";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";

import {
  createMentorNote,
  getMentorCoderCases,
  getMentorCoders,
  getMentorDistricts,
  getMyMentorFeedback,
  markMentorFeedbackRead,
} from "../src/api";

jest.mock("expo-router", () => ({ useRouter: () => ({ push: jest.fn() }) }));

const mockBootstrap = { user: { user_id: "u1", name: "Mentor" }, csrf: { header: "X-CSRFToken", token: "t" } };
jest.mock("../src/AppState", () => ({ useAppState: () => ({ bootstrap: mockBootstrap }) }));
jest.mock("../src/web/common", () => ({
  WebShell: ({ children }: { children: ReactNode }) => <>{children}</>,
  browserErrorText: (e: any) => e?.message || "server error",
}));
jest.mock("../src/web/roleHome", () => ({ openServerPage: jest.fn() }));
jest.mock("../src/api", () => ({
  ...jest.requireActual("../src/api"),
  getMentorDistricts: jest.fn(),
  getMentorCoders: jest.fn(),
  getMentorCoderCases: jest.fn(),
  createMentorNote: jest.fn(),
  retractMentorNote: jest.fn(),
  getMyMentorFeedback: jest.fn(),
  markMentorFeedbackRead: jest.fn(),
}));

import MentorViewScreen, { MentorFeedbackPanel, PII_WARNING } from "../src/web/MentorViewScreen";

const DISTRICT = { district_id: "d1", code: "D01", name: "District One", project_id: "P1", project_name: "Proj" };
const ROW = {
  label: "Alpha Coder", coder_id: "c1", ready: 4, coded: 3, reviewed_agreed: 1, reviewed_changed: 1,
  not_codeable: 0, recodes: 1, last_active: "2026-11-19",
};
const NOTE = {
  note_id: "n1", va_sid: "sid-1", body: "Check the fever history.", created_at: "2026-11-20T00:00:00+00:00",
  read: false, author_name: "Dr M", author_basis: "mentor", institute_name: "MC One", mine: false, can_retract: false,
};

function text(tree: ReactTestRenderer): string {
  const out: string[] = [];
  const walk = (node: any) => {
    if (typeof node === "string") out.push(node);
    else if (Array.isArray(node)) node.forEach(walk);
    else if (node?.children) node.children.forEach(walk);
  };
  walk(tree.toJSON());
  return out.join(" ");
}

function button(tree: ReactTestRenderer, label: string): ReactTestInstance {
  return tree.root.findAll((n) => n.props.accessibilityRole === "button" && n.props.accessibilityLabel === label)[0];
}

async function settle() {
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
}

describe("MentorViewScreen", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (getMentorDistricts as jest.Mock).mockResolvedValue({ districts: [DISTRICT] });
  });

  it("shows the per-coder table and drills down to cases with notes", async () => {
    (getMentorCoders as jest.Mock).mockResolvedValue({ names_visible: true, coders: [ROW], truncated: false });
    (getMentorCoderCases as jest.Mock).mockResolvedValue({
      cases: [{ va_sid: "sid-1", coded_at: "2026-11-20T00:00:00", final_cod: "A01", review_outcome: "agreed", notes: [NOTE] }],
      next: null,
    });
    (createMentorNote as jest.Mock).mockResolvedValue({ ...NOTE, note_id: "n2", body: "Second note", mine: true, can_retract: true });
    let tree!: ReactTestRenderer;
    await act(async () => { tree = create(<MentorViewScreen />); });
    await settle();
    expect(getMentorCoders).toHaveBeenCalledWith("d1", "all", mockBootstrap.csrf);
    expect(text(tree)).toContain("Alpha Coder");
    expect(text(tree)).toContain("Ready for them 4");

    await act(async () => { button(tree, "View coded cases").props.onPress(); });
    await settle();
    expect(getMentorCoderCases).toHaveBeenCalledWith("d1", "c1", "all", null, mockBootstrap.csrf);
    expect(text(tree)).toContain("Reviewer agreed");
    expect(text(tree)).toContain("Check the fever history.");
    expect(text(tree)).toContain(PII_WARNING);

    const input = tree.root.findAll((n) => n.props.accessibilityLabel === "Note on sid-1" && n.props.onChangeText)[0];
    await act(async () => { input.props.onChangeText("Second note"); });
    await act(async () => { button(tree, "Add note").props.onPress(); });
    await settle();
    expect(createMentorNote).toHaveBeenCalledWith("sid-1", "Second note", mockBootstrap.csrf);
    expect(text(tree)).toContain("Second note");
    expect(button(tree, "Retract")).toBeTruthy();
  });

  it("offers no drill-down when names are hidden", async () => {
    const { coder_id: _omit, ...pseudonym } = ROW;
    (getMentorCoders as jest.Mock).mockResolvedValue({
      names_visible: false, coders: [{ ...pseudonym, label: "Coder 1", last_active: null }], truncated: false,
    });
    let tree!: ReactTestRenderer;
    await act(async () => { tree = create(<MentorViewScreen />); });
    await settle();
    expect(text(tree)).toContain("Coder 1");
    expect(button(tree, "View coded cases")).toBeUndefined();
  });

  it("shows the server's refusal", async () => {
    (getMentorDistricts as jest.Mock).mockRejectedValue(new Error("The mentor view is for mentoring institutes."));
    let tree!: ReactTestRenderer;
    await act(async () => { tree = create(<MentorViewScreen />); });
    await settle();
    expect(text(tree)).toContain("The mentor view is for mentoring institutes.");
    expect(getMentorCoders).not.toHaveBeenCalled();
  });
});

describe("MentorFeedbackPanel", () => {
  it("lists the coder's notes and marks one read", async () => {
    (getMyMentorFeedback as jest.Mock).mockResolvedValue({ notes: [NOTE], unread_count: 1, next: null });
    (markMentorFeedbackRead as jest.Mock).mockResolvedValue(undefined);
    let tree!: ReactTestRenderer;
    await act(async () => { tree = create(<MentorFeedbackPanel csrf={mockBootstrap.csrf} />); });
    await settle();
    expect(text(tree)).toContain("Feedback from mentors (1 unread)");
    expect(text(tree)).toContain("Dr M, MC One");
    await act(async () => { button(tree, "Mark as read").props.onPress(); });
    await settle();
    expect(markMentorFeedbackRead).toHaveBeenCalledWith("n1", mockBootstrap.csrf);
    expect(text(tree)).toContain("Feedback from mentors");
    expect(text(tree)).not.toContain("unread");
  });

  it("renders nothing without notes", async () => {
    (getMyMentorFeedback as jest.Mock).mockResolvedValue({ notes: [], unread_count: 0, next: null });
    let tree!: ReactTestRenderer;
    await act(async () => { tree = create(<MentorFeedbackPanel csrf={mockBootstrap.csrf} />); });
    await settle();
    expect(tree.toJSON()).toBeNull();
  });
});
