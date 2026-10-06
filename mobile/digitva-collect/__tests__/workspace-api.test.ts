import * as auth from "../src/auth";
import * as transport from "../src/api";
import { createWorkspaceApi } from "../src/workspace/api";
import { parseWorkspace, WorkspaceContractError } from "../src/workspace/contracts";
import { createNativeWorkspaceTransport } from "../src/workspace/transport.native";
import { createWebWorkspaceTransport } from "../src/workspace/transport.web";

const view = {
  case: {
    va_sid: "sid/1", instance_name: "MASKED-1", form_type_code: "FORM",
    project_mode: "masked_simple", icd_classification: "icd10", workflow_state: "finalized",
    narrative_qa_enabled: false, social_autopsy_enabled: false,
  },
  categories: [{ code: "a/b", label: "A", nav_label: "A", render_mode: "table" }],
  default_category: "a/b", step: "view", blocked_by: [],
  assessments: { initial: null, initial_prefill: null, final: null, not_codeable: null },
  smartva: null, other_conditions_options: null, doris: null, narrative_qa: null, social_autopsy: null,
};

describe("workspace contracts and API", () => {
  test("view mode preserves withheld masked references and rejects edits leaking into the view", () => {
    expect(parseWorkspace(view, "view")).not.toHaveProperty("blocked_by");
    expect(() => parseWorkspace({ ...view, blocked_by: ["review"] }, "view")).toThrow("workspace.view");
    expect(() => parseWorkspace({ ...view, doris: {} }, "view")).toThrow(WorkspaceContractError);
    expect(() => parseWorkspace({ ...view, step: "initial" }, "view")).toThrow(WorkspaceContractError);
  });

  test("masked coding Step 1 fails closed if SmartVA or final COD is present", () => {
    const step1 = {
      ...view,
      case: { ...view.case, project_mode: "masked_doris", narrative_qa_enabled: true },
      step: "initial",
      assessments: { ...view.assessments, initial: null, initial_prefill: null },
      narrative_qa: { fields: [], max_score: 10, saved: null },
    };
    expect(parseWorkspace(step1, "coding").step).toBe("initial");
    expect(() => parseWorkspace({ ...step1, smartva: { causes: [] } }, "coding")).toThrow("workspace.masked_step1");
    expect(() => parseWorkspace({ ...step1, assessments: { ...step1.assessments, final: { id: "hidden" } } }, "coding")).toThrow("workspace.masked_step1");
  });

  test("encodes route identifiers and validates additively while preserving server order", async () => {
    const calls: Array<{ path: string; init?: unknown }> = [];
    const api = createWorkspaceApi(async (path, init) => {
      calls.push({ path, init });
      return path.includes("/categories/") ? {
        code: "a/b", label: "A", render_mode: "table", summary_items: [],
        blocked_by: [],
        subcategories: [{ code: "one", label: "One", render_mode: "table", items: [{ label: "x", value: "y", flip: true, info: false }] }],
        future_field: "ignored",
      } : { ...view, case: { ...view.case, future_field: true }, future_field: "ignored" };
    });
    await api.getWorkspace("sid/1", "view");
    const category = await api.getCategory("sid/1", "a/b", "view");
    expect(calls[0].path).toBe("/api/v1/va/sid%2F1/workspace?mode=view");
    expect(calls[1].path).toBe("/api/v1/va/sid%2F1/categories/a%2Fb?mode=view");
    expect(category).not.toHaveProperty("blocked_by");
    expect(category.subcategories.map(item => item.code)).toEqual(["one"]);
    expect(category.subcategories[0]?.items[0]).toMatchObject({ flip: true, info: false });
  });

  test("rejects a nonempty category blocker in view mode", async () => {
    const api = createWorkspaceApi(async () => ({
      code: "a/b", label: "A", render_mode: "table", summary_items: [],
      subcategories: [], blocked_by: ["coding"],
    }));
    await expect(api.getCategory("sid/1", "a/b", "view")).rejects.toThrow("category.blocked_by");
  });

  test("validates reviewer paging and keeps project allocation and reviewer NQA bodies explicit", async () => {
    const calls: Array<{ path: string; init?: { method?: string; json?: unknown } }> = [];
    const api = createWorkspaceApi(async (path, init) => {
      calls.push({ path, init });
      if (path.includes("/reviewing/available")) return { cases: [], count: 0, limit: 200, offset: 1_000_000, has_more: false };
      if (path.includes("/coding/allocation")) return { va_sid: "sid", actiontype: "vapickcoding" };
      return { va_sid: "sid", saved: true };
    });
    await api.getReviewerAvailable({ limit: 200, offset: 1_000_000, projectId: "p & 1" });
    await expect(api.getReviewerAvailable({ limit: Number.NaN })).rejects.toThrow("request.limit");
    await api.allocateCoding("sid", "project 1");
    await api.saveNarrativeQuality("sid", {}, "reviewing");
    expect(calls[0].path).toContain("limit=200");
    expect(calls[0].path).toContain("offset=1000000");
    expect(calls[0].path).toContain("project_id=p+%26+1");
    expect(calls[1].init).toEqual({ method: "POST", json: { sid: "sid", project_id: "project 1" } });
    expect(calls[2].init).toEqual({ method: "POST", json: { va_actiontype: "varesumereviewing" } });
  });

  test("normalizes nested DORIS errors and leaves COD processing conflicts intact", async () => {
    const nested = new transport.ApiError(422, undefined, undefined, undefined, {
      schema_version: 1, error: { code: "INVALID_INPUT", message: "Certificate rejected." },
    });
    const api = createWorkspaceApi(async (path) => {
      if (path.includes("doris-clinical")) throw nested;
      throw nested;
    });
    await expect(api.processDoris("sid", "coder", 2, {})).rejects.toMatchObject({ status: 422, code: "INVALID_INPUT", message: "Certificate rejected." });

    const processing = { fresh: true };
    const conflict = new transport.ApiError(409, "DORIS_CERTIFICATE_CHANGED", undefined, undefined, { error: "Changed", code: "DORIS_CERTIFICATE_CHANGED", processing });
    const conflictApi = createWorkspaceApi(async () => { throw conflict; });
    await expect(conflictApi.saveFinal("sid", {})).rejects.toBe(conflict);
    expect(conflict.payload?.processing).toBe(processing);
  });

  test("parses consumed DORIS term and process fields and rejects malformed envelopes", async () => {
    const api = createWorkspaceApi(async (path) => {
      if (path.includes("/terms/")) return { schema_version: 1, truncated: false, next_cursor: null, items: [{
        code: "1A00", title: "Example", uri: "https://id.who.int/icd/entity/1", release: "2025-01",
        matching_text: "Example", postcoordination: false, postcoordination_availability: [],
        related_maternal: false, related_perinatal: false, has_coding_note: false, future_field: true,
      }] };
      return {
        schema_version: 1, client_revision: 3, icd_release: "2025-01", certificate: { Identification: {} },
        certificate_digest: "cert-digest", result_digest: "result-digest", process_token: "proof",
        doris: { status: "completed", result: { code: "1A00" } },
        codedit: { status: "timeout", result: null }, future_field: true,
      };
    });
    const terms = await api.searchDorisTerms("sid", "example");
    expect(terms.items[0]?.code).toBe("1A00");
    expect(terms.items[0]).not.toHaveProperty("future_field");
    const processed = await api.processDoris("sid", "coder", 3, { Identification: {} });
    expect(processed.doris.result?.code).toBe("1A00");

    const malformedApi = createWorkspaceApi(async () => ({
      schema_version: 1, client_revision: 3, icd_release: "2025-01", certificate: {},
      certificate_digest: "cert", result_digest: "result", process_token: "proof",
      doris: { status: "mystery", result: null }, codedit: { status: "timeout", result: null },
    }));
    await expect(malformedApi.processDoris("sid", "coder", 3, {})).rejects.toThrow(WorkspaceContractError);
  });

  test("adapters use existing CSRF and bearer refresh request helpers", async () => {
    const web = jest.spyOn(transport, "requestClientJson").mockResolvedValue({ ok: true });
    const native = jest.spyOn(auth, "authedRequest").mockResolvedValue({ status: 200, body: { ok: true } });
    const csrf = { header: "X-CSRFToken" as const, token: "csrf-value" };
    const webRequest = createWebWorkspaceTransport(csrf);
    const nativeRequest = createNativeWorkspaceTransport("user-1");
    await webRequest("/api/v1/va/sid/note?mode=coding", { method: "PUT", json: { content: "note" } });
    await nativeRequest("/api/v1/va/sid/note?mode=coding", { method: "PUT", json: { content: "note" } });
    expect(web).toHaveBeenCalledWith("/api/v1/va/sid/note?mode=coding", { method: "PUT", json: { content: "note" }, csrf });
    expect(native).toHaveBeenCalledWith("user-1", "/api/v1/va/sid/note?mode=coding", { method: "PUT", body: { content: "note" } });
    web.mockRestore();
    native.mockRestore();
  });
});
