import { parseCategory, parseCoderHistory, parseCoderProjects, parseWorkspace, WorkspaceContractError } from "../src/workspace/contracts";

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

test("survey_state is optional and nullable but must be a string", () => {
  expect(parseWorkspace(payload(), "coding").case).not.toHaveProperty("survey_state");
  expect(parseWorkspace(payload({ survey_state: "Madhya Pradesh" }), "coding").case.survey_state).toBe("Madhya Pradesh");
  expect(parseWorkspace(payload({ survey_state: null }), "coding").case.survey_state).toBeNull();
  expect(() => parseWorkspace(payload({ survey_state: 7 }), "coding")).toThrow(new WorkspaceContractError("workspace.case.survey_state"));
});

test("survey_district is optional and nullable but must be a string", () => {
  expect(parseWorkspace(payload(), "coding").case).not.toHaveProperty("survey_district");
  expect(parseWorkspace(payload({ survey_district: "Raisen" }), "coding").case.survey_district).toBe("Raisen");
  expect(parseWorkspace(payload({ survey_district: null }), "coding").case.survey_district).toBeNull();
  expect(() => parseWorkspace(payload({ survey_district: 7 }), "coding")).toThrow(new WorkspaceContractError("workspace.case.survey_district"));
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

test("accepts additive evidence provenance and rejects a malformed source", () => {
  const category = { code: "cod", label: "COD", render_mode: "workflow_panel", summary_items: [], subcategories: [{ code: "history", label: "History", render_mode: "default", source_category: "diagnoses", items: [] }] };
  expect(parseCategory(category, "coding").subcategories[0].source_category).toBe("diagnoses");
  expect(() => parseCategory({ ...category, subcategories: [{ ...category.subcategories[0], source_category: 3 }] }, "coding")).toThrow(WorkspaceContractError);
  expect(parseCategory({ ...category, subcategories: [{ code: "old", label: "Old", render_mode: "default", items: [] }] }, "coding").subcategories[0].source_category).toBeUndefined();
});

describe("offline station coding fields", () => {
  const row = {
    va_sid: "VA-1", va_uniqueid_masked: "U-1", va_form_id: "WHO_2022_VA", project_id: "P1", site_id: "S1",
    va_submission_date: "2026-10-21", va_deceased_age: "68", va_deceased_gender: "male",
    va_coding_date: "2026-10-21", va_code_status: "coded", recodeable: true,
  };
  const page = (history: unknown[]) => ({ history, count: history.length, limit: 50, offset: 0, has_more: false });

  it("keeps the server's status and code, and drops an unknown status", () => {
    const parsed = parseCoderHistory(page([
      { ...row, server_status: "refused", server_code: "invalid_doris" },
      { ...row, va_sid: "VA-2", server_status: null, server_code: null },
      { ...row, va_sid: "VA-3", server_status: "accepted", server_code: "x" },
    ]), 50, 0).history;
    expect([parsed[0].server_status, parsed[0].server_code]).toEqual(["refused", "invalid_doris"]);
    expect("server_status" in parsed[1]).toBe(false);
    expect("server_status" in parsed[2]).toBe(false);
    expect(() => parseCoderHistory(page([{ ...row, server_status: "pending", server_code: 5 }]), 50, 0)).toThrow(WorkspaceContractError);
  });

  it("reads station_coding_disabled only when true", () => {
    const base = { projects: [], project_options: [], last_project_id: null };
    expect(parseCoderProjects({ ...base, station_coding_disabled: true }).station_coding_disabled).toBe(true);
    expect("station_coding_disabled" in parseCoderProjects({ ...base, station_coding_disabled: false })).toBe(false);
  });
});
