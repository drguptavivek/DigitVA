import React from "react";
import { StyleSheet, Text } from "react-native";
import { act, create } from "react-test-renderer";

import { radius, roleToneName } from "../src/theme";
import { RoleChip, RoleSentence } from "../src/ui/RoleChip";
import { roleCodeOfLabel } from "../src/web/roleHome";

const ROLES = [
  "death_reporter", "interviewer", "interview_supervisor", "coder", "reviewer", "data_manager",
  "project_pi", "site_pi", "admin", "coding_tester", "collaborator", "collaborator_pii",
];

const render = (node: React.ReactElement) => {
  let tree!: ReturnType<typeof create>;
  act(() => { tree = create(node); });
  return tree;
};

describe("role chips", () => {
  it("maps the six named roles, PI and admin to distinct tones; the rest are neutral", () => {
    const named = ["death_reporter", "interviewer", "interview_supervisor", "coder", "reviewer", "data_manager", "project_pi", "admin"];
    expect(new Set(named.map(roleToneName)).size).toBe(named.length);
    expect(roleToneName("site_pi")).toBe(roleToneName("project_pi"));
    for (const role of ["coding_tester", "collaborator", "collaborator_pii", "unknown"]) expect(roleToneName(role)).toBe("neutral");
  });

  it.each(ROLES)("%s chip is a square tag with its name written", (role) => {
    const tree = render(<RoleChip role={role} />);
    const style = StyleSheet.flatten(tree.root.findByProps({ testID: `role-chip-${role}` }).props.style);
    expect(style.borderRadius).toBe(radius.sm);
    expect(style.borderRadius).toBeLessThan(radius.md);
    expect(tree.root.findByType(Text).props.children).toBeTruthy();
  });

  it("writes the cadre in brackets and honours a label override", () => {
    const tree = render(<><RoleChip role="coder" cadre="Medical Officer" /><RoleChip role="coder" label="Code" /></>);
    const texts = tree.root.findAllByType(Text).map((n) => n.props.children);
    expect(texts).toEqual(["Coder (Medical Officer)", "Code"]);
  });

  it("puts the chips where {roles} sits in the translation", () => {
    const tree = render(<RoleSentence k="orgYouRoles" roles={[{ role: "coder" }, { role: "reviewer" }]} textStyle={{}} />);
    expect(tree.root.findAllByType(Text).map((n) => n.props.children)).toEqual(["You:", "Coder", "Reviewer"]);
  });

  it("reads server labels back to role codes", () => {
    expect(roleCodeOfLabel("Interview Supervisor")).toBe("interview_supervisor");
    expect(roleCodeOfLabel("Viewer (with PII)")).toBe("collaborator_pii");
    expect(roleCodeOfLabel("Nonsense")).toBeNull();
  });
});
