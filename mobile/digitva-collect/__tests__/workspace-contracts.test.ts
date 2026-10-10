import { parseWorkspace, WorkspaceContractError } from "../src/workspace/contracts";

function payload(overrides: Record<string, unknown> = {}) {
  return {
    case: {
      va_sid: "sid-1", instance_name: "form-1", form_type_code: "WHO",
      project_mode: "masked_simple", icd_classification: "icd10", workflow_state: "coding_in_progress",
      narrative_qa_enabled: false, social_autopsy_enabled: false, ...overrides,
    },
    categories: [{ code: "general", label: "General", nav_label: "General", render_mode: "table_sections" }],
    default_category: "general", step: "initial", blocked_by: [],
    assessments: { initial: null, initial_prefill: null, final: null, not_codeable: null },
    smartva: null, other_conditions_options: null, doris: null, narrative_qa: null, social_autopsy: null,
  };
}

test("accepts optional browser workspace metadata and configured category badges", () => {
  const result = parseWorkspace({
    ...payload({ project_code: "P1", site_code: null, age: 46, gender: "male", is_demo_project: true }),
    categories: [{ code: "general", label: "General", nav_label: "General", render_mode: "table_sections", icon_name: "fa-user", count: 3, attachment_count: 2 }],
  }, "coding");

  expect(result.case).toMatchObject({ project_code: "P1", site_code: null, age: 46, gender: "male", is_demo_project: true });
  expect(result.categories[0]).toMatchObject({ icon_name: "fa-user", count: 3, attachment_count: 2 });
});

test.each([
  ["negative attachment count", { categories: [{ code: "general", label: "General", nav_label: "General", render_mode: "table_sections", attachment_count: -1 }] }, "workspace.categories[0].attachment_count"],
  ["negative category count", { categories: [{ code: "general", label: "General", nav_label: "General", render_mode: "table_sections", count: -1 }] }, "workspace.categories[0].count"],
  ["fractional category count", { categories: [{ code: "general", label: "General", nav_label: "General", render_mode: "table_sections", count: 1.5 }] }, "workspace.categories[0].count"],
  ["malformed icon name", { categories: [{ code: "general", label: "General", nav_label: "General", render_mode: "table_sections", icon_name: "fa user" }] }, "workspace.categories[0].icon_name"],
  ["malformed age", { case: { ...payload().case, age: { value: 46 } } }, "workspace.case.age"],
] as const)("rejects %s", (_label, override, field) => {
  expect(() => parseWorkspace({ ...payload(), ...override }, "coding")).toThrow(new WorkspaceContractError(field));
});
