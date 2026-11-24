/** Pins the Add Staff form's validation messages, their order, and the payload it sends (digitva-r8nh.26). */
import React, { type ReactNode } from "react";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";

import { createMentorInstituteStaff, getMentoringSummary, listMentorInstituteStaff } from "../src/api";

jest.mock("expo-router", () => ({ useRouter: () => ({ push: jest.fn() }) }));
const mockBootstrap = {
  user: { user_id: "user-1", name: "Dr. Alice" },
  csrf: { header: "X-CSRFToken", token: "t" },
  access: { user: { user_id: "user-1", name: "Dr. Alice" }, is_admin: false, roles: [], projects: [] },
};
jest.mock("../src/AppState", () => ({ useAppState: () => ({ bootstrap: mockBootstrap }) }));
jest.mock("../src/web/common", () => ({
  WebShell: ({ children }: { children: ReactNode }) => <>{children}</>,
  browserErrorText: (e: any) => e?.message || "server error",
}));
jest.mock("../src/api", () => ({
  ...jest.requireActual("../src/api"),
  getMentoringSummary: jest.fn(),
  listMentorInstituteStaff: jest.fn(),
  createMentorInstituteStaff: jest.fn(),
  removeMentorInstituteStaff: jest.fn(),
}));

import MentoringScreen from "../src/web/MentoringScreen";

const summary = (withLanguages: boolean) => ({
  is_member: true,
  is_institute_admin: true,
  institutes: [{ institute_code: "I1", institute_name: "Inst", is_active: true, is_admin: true, districts: [] }],
  languages: withLanguages ? [{ language_code: "hi", language_name: "Hindi" }] : [],
});

const button = (root: ReactTestInstance, label: string) =>
  root.findAll((n) => n.props.accessibilityRole === "button" && n.props.accessibilityLabel === label && (!n.parent || n.parent.props.accessibilityRole !== "button"))[0];

async function open(withLanguages: boolean): Promise<ReactTestRenderer> {
  (getMentoringSummary as jest.Mock).mockResolvedValue(summary(withLanguages));
  (listMentorInstituteStaff as jest.Mock).mockResolvedValue({ staff: [] });
  let r!: ReactTestRenderer;
  await act(async () => {
    r = create(<MentoringScreen />);
  });
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  await act(async () => {
    button(r.root, "Add Faculty / Resident Staff").props.onPress();
  });
  return r;
}

interface Fields { name?: string; email?: string; confirm?: string; job?: string; phone?: string; hindi?: boolean }

async function submit(r: ReactTestRenderer, f: Fields): Promise<string | undefined> {
  const inputs = r.root.findAllByType("TextInput" as any);
  const emails = inputs.filter((i) => i.props.keyboardType === "email-address");
  await act(async () => {
    inputs.find((i) => i.props.placeholder === "Dr. Full Name")!.props.onChangeText(f.name ?? "");
    emails[0].props.onChangeText(f.email ?? "");
    emails[1].props.onChangeText(f.confirm ?? "");
    inputs.find((i) => i.props.placeholder === "Assistant Professor, Community Medicine")!.props.onChangeText(f.job ?? "");
    inputs.find((i) => i.props.keyboardType === "phone-pad")!.props.onChangeText(f.phone ?? "");
    if (f.hindi) button(r.root, "Hindi").props.onPress();
  });
  await act(async () => {
    button(r.root, "Send Invitation").props.onPress();
  });
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  return r.root.findAll((n) => n.props.role === "alert" && typeof n.props.children === "string")[0]?.props.children;
}

beforeEach(() => jest.clearAllMocks());

describe("Add Staff form validation", () => {
  const cases: Array<[string, Fields, string]> = [
    ["nothing", {}, "Full Name is required."],
    ["blank name", { name: "   ", email: "a@b.c", confirm: "a@b.c", hindi: true }, "Full Name is required."],
    ["no email", { name: "N", hindi: true }, "Email is required."],
    ["no confirm", { name: "N", email: "a@b.c", hindi: true }, "Confirm Email is required."],
    ["mismatch", { name: "N", email: "a@b.c", confirm: "a@b.d", hindi: true }, "Email confirmation does not match."],
    ["no language", { name: "N", email: "a@b.c", confirm: "a@b.c" }, "At least one coding language must be selected."],
    ["short phone", { name: "N", email: "a@b.c", confirm: "a@b.c", hindi: true, phone: "12345" }, "Enter a valid 10-digit mobile number."],
    ["lettered phone", { name: "N", email: "a@b.c", confirm: "a@b.c", hindi: true, phone: "98765abcde" }, "Enter a valid 10-digit mobile number."],
    ["name is checked before email", { email: "x", confirm: "y", phone: "1" }, "Full Name is required."],
    ["email is checked before language and phone", { name: "N", phone: "1" }, "Email is required."],
    ["language is checked before phone", { name: "N", email: "a@b.c", confirm: "a@b.c", phone: "1" }, "At least one coding language must be selected."],
  ];
  it.each(cases)("%s shows its message and sends nothing", async (_n, fields, message) => {
    const r = await open(true);
    expect(await submit(r, fields)).toBe(message);
    expect(createMentorInstituteStaff).not.toHaveBeenCalled();
  });

  const created = { staff: { user_id: "u2", name: "N", email: "a@b.c", is_admin: false, account_status: "invited" } };

  it("needs no language when the institute offers none", async () => {
    (createMentorInstituteStaff as jest.Mock).mockResolvedValue(created);
    const r = await open(false);
    expect(await submit(r, { name: "N", email: "a@b.c", confirm: "a@b.c" })).toBeUndefined();
    expect(createMentorInstituteStaff).toHaveBeenCalledWith("I1", { name: "N", email: "a@b.c", email_confirm: "a@b.c", languages: [] }, expect.anything());
  });

  it("trims, lowercases emails, strips spaces and dashes from the phone, and omits a blank job title", async () => {
    (createMentorInstituteStaff as jest.Mock).mockResolvedValue(created);
    const r = await open(true);
    expect(await submit(r, { name: " N ", email: " A@B.c ", confirm: "a@B.C", job: "  ", phone: " 98765-43 210 ", hindi: true })).toBeUndefined();
    expect(createMentorInstituteStaff).toHaveBeenCalledWith(
      "I1",
      { name: "N", email: "a@b.c", email_confirm: "a@b.c", languages: ["hi"], phone: "9876543210" },
      expect.anything(),
    );
  });

  it("keeps a trimmed job title in the payload", async () => {
    (createMentorInstituteStaff as jest.Mock).mockResolvedValue(created);
    const r = await open(true);
    await submit(r, { name: "N", email: "a@b.c", confirm: "a@b.c", job: " Prof ", hindi: true });
    expect((createMentorInstituteStaff as jest.Mock).mock.calls[0][1].job_title).toBe("Prof");
  });
});
