/** Shared typed API for coding, reviewing, and read-only workspace screens. */
import { ApiError } from "../api";
import {
  parseAllocation,
  parseCategory,
  parseCoderHistory,
  parseCodingSave,
  parseCodingStats,
  parseCoderProjects,
  parseCoderQueue,
  parseDorisCodeInfo,
  parseDorisProcess,
  parseDorisTerms,
  parseCodingWrite,
  parseIcdSearch,
  parseNote,
  parseOptionalAllocation,
  parseReviewerHistory,
  parseReviewerQueue,
  parseReviewerStats,
  parseWorkflowEvents,
  parseWorkspace,
  parseJsonValue,
  WorkspaceContractError,
  type AllocationReply,
  type CategoryPayload,
  type CoderHistory,
  type CoderProjects,
  type CoderQueue,
  type CodingSaveReply,
  type CodingStats,
  type CodingWriteReply,
  type DorisCodeInfoReply,
  type DorisProcessReply,
  type DorisTermsReply,
  type IcdSearchItem,
  type JsonObject,
  type NotePayload,
  type ReviewerHistory,
  type ReviewerQueue,
  type ReviewerStats,
  type WorkspaceMode,
  type WorkspacePayload,
  type WorkflowEvents,
} from "./contracts";

export interface WorkspaceRequestInit {
  method?: "GET" | "POST" | "PUT";
  json?: unknown;
}

export type JsonRequester = (path: string, init?: WorkspaceRequestInit) => Promise<unknown>;

export interface WorkspaceApi {
  getWorkspace(vaSid: string, mode: WorkspaceMode): Promise<WorkspacePayload>;
  getCategory(vaSid: string, code: string, mode: WorkspaceMode): Promise<CategoryPayload>;
  getCodingStats(projectId?: string): Promise<CodingStats>;
  getCodingAvailable(options?: { projectId?: string; limit?: number; offset?: number }): Promise<CoderQueue>;
  getCodingHistory(options?: { projectId?: string; limit?: number; offset?: number }): Promise<CoderHistory>;
  getCodingProjects(): Promise<CoderProjects>;
  getCodingAllocation(): Promise<{ va_sid: string } | null>;
  getReviewerStats(projectId?: string): Promise<ReviewerStats>;
  getReviewerAvailable(options?: { projectId?: string; limit?: number; offset?: number }): Promise<ReviewerQueue>;
  getReviewerHistory(options?: { projectId?: string; limit?: number; offset?: number }): Promise<ReviewerHistory>;
  getReviewerAllocation(): Promise<{ va_sid: string } | null>;
  allocateCoding(vaSid?: string, projectId?: string): Promise<AllocationReply>;
  codeOwnSubmission(vaSid: string): Promise<AllocationReply>;
  recode(vaSid: string): Promise<AllocationReply>;
  releaseCoding(): Promise<CodingSaveReply>;
  allocateReviewer(vaSid: string): Promise<AllocationReply>;
  releaseReviewer(): Promise<CodingSaveReply>;
  searchIcd(vaSid: string, classification: "icd10" | "icd11", query: string): Promise<IcdSearchItem[]>;
  saveInitial(vaSid: string, body: JsonObject, mode?: "coding" | "reviewing"): Promise<CodingWriteReply>;
  saveFinal(vaSid: string, body: JsonObject, mode?: "coding" | "reviewing"): Promise<CodingWriteReply>;
  saveNotCodeable(vaSid: string, body: JsonObject): Promise<CodingSaveReply>;
  saveNarrativeQuality(vaSid: string, body: JsonObject, mode?: "coding" | "reviewing"): Promise<JsonObject>;
  saveSocialAutopsy(vaSid: string, body: JsonObject, mode?: "coding" | "reviewing"): Promise<JsonObject>;
  getNote(vaSid: string, mode: "coding" | "reviewing"): Promise<NotePayload>;
  saveNote(vaSid: string, mode: "coding" | "reviewing", content: string): Promise<NotePayload>;
  searchDorisTerms(vaSid: string, query: string, options?: { limit?: number; subtreeUris?: string[] }): Promise<DorisTermsReply>;
  getDorisCodeInfo(vaSid: string, code: string): Promise<DorisCodeInfoReply>;
  checkDorisSelection(vaSid: string, code: string, uri: string): Promise<DorisCodeInfoReply>;
  processDoris(vaSid: string, role: "coder" | "reviewer", clientRevision: number, certificate: JsonObject): Promise<DorisProcessReply>;
  getWorkflowEvents(vaSid: string, options?: { limit?: number; cursor?: string }): Promise<WorkflowEvents>;
}

const API = "/api/v1";

function id(value: string): string {
  if (!value) throw new WorkspaceContractError("request.id");
  return encodeURIComponent(value);
}

function projectQuery(projectId?: string): string {
  return projectId ? `?${new URLSearchParams({ project_id: projectId })}` : "";
}

function pagingQuery(options: { projectId?: string; limit?: number; offset?: number } = {}): string {
  const params = new URLSearchParams();
  if (options.projectId) params.set("project_id", options.projectId);
  if (options.limit !== undefined) {
    if (!Number.isInteger(options.limit) || options.limit < 1 || options.limit > 200) throw new WorkspaceContractError("request.limit");
    params.set("limit", String(options.limit));
  }
  if (options.offset !== undefined) {
    if (!Number.isInteger(options.offset) || options.offset < 0 || options.offset > 1_000_000) throw new WorkspaceContractError("request.offset");
    params.set("offset", String(options.offset));
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

function parsed<T>(value: unknown, parse: (value: unknown) => T): T {
  return parse(value);
}

function jsonObject(value: unknown, field: string): JsonObject {
  const result = parseJsonValue(value, field);
  if (result === null || Array.isArray(result) || typeof result !== "object") throw new WorkspaceContractError(field);
  return result;
}

function normalizeDorisError(error: unknown): never {
  if (!(error instanceof ApiError) || !error.payload || typeof error.payload !== "object") throw error;
  const payload = error.payload;
  const nested = payload.error;
  if (!nested || typeof nested !== "object" || Array.isArray(nested)) throw error;
  const nestedError = nested as Record<string, unknown>;
  if (payload.schema_version !== 1 || typeof nestedError.code !== "string" || typeof nestedError.message !== "string") throw new WorkspaceContractError("doris.error");
  const normalized = new ApiError(error.status, nestedError.code, error.redirectUrl, error.csrf, payload);
  normalized.message = nestedError.message;
  throw normalized;
}

/**
 * Create route methods without acquiring an allocation or touching storage.
 * The injected requester owns credentials, browser CSRF, and native refresh.
 */
export function createWorkspaceApi(request: JsonRequester): WorkspaceApi {
  const get = (path: string) => request(`${API}${path}`);
  const post = (path: string, json?: unknown) => request(`${API}${path}`, { method: "POST", ...(json !== undefined ? { json } : {}) });

  return {
    async getWorkspace(vaSid, mode) {
      const value = await get(`/va/${id(vaSid)}/workspace?mode=${encodeURIComponent(mode)}`);
      return parsed(value, body => parseWorkspace(body, mode));
    },
    async getCategory(vaSid, code, mode) {
      const value = await get(`/va/${id(vaSid)}/categories/${id(code)}?mode=${encodeURIComponent(mode)}`);
      return parsed(value, body => parseCategory(body, mode));
    },
    async getCodingStats(projectId) { return parsed(await get(`/coding/stats${projectQuery(projectId)}`), parseCodingStats); },
    async getCodingAvailable(options) {
      const limit = options?.limit ?? 50;
      const offset = options?.offset ?? 0;
      const query = pagingQuery({ projectId: options?.projectId, limit, offset });
      return parsed(await get(`/coding/available${query}`), value => parseCoderQueue(value, limit, offset));
    },
    async getCodingHistory(options) {
      const limit = options?.limit ?? 50;
      const offset = options?.offset ?? 0;
      const query = pagingQuery({ projectId: options?.projectId, limit, offset });
      return parsed(await get(`/coding/history${query}`), value => parseCoderHistory(value, limit, offset));
    },
    async getCodingProjects() { return parsed(await get("/coding/projects"), parseCoderProjects); },
    async getCodingAllocation() { return parsed(await get("/coding/allocation"), parseOptionalAllocation); },
    async getReviewerStats(projectId) { return parsed(await get(`/reviewing/stats${projectQuery(projectId)}`), parseReviewerStats); },
    async getReviewerAvailable(options) {
      const limit = options?.limit ?? 50;
      const offset = options?.offset ?? 0;
      return parsed(await get(`/reviewing/available${pagingQuery({ ...options, limit, offset })}`), value => parseReviewerQueue(value, limit, offset));
    },
    async getReviewerHistory(options) {
      const limit = options?.limit ?? 50;
      const offset = options?.offset ?? 0;
      return parsed(await get(`/reviewing/history${pagingQuery({ ...options, limit, offset })}`), value => parseReviewerHistory(value, limit, offset));
    },
    async getReviewerAllocation() { return parsed(await get("/reviewing/allocation"), parseOptionalAllocation); },
    async allocateCoding(vaSid, projectId) {
      if (vaSid !== undefined && !vaSid) throw new WorkspaceContractError("request.vaSid");
      return parsed(await post("/coding/allocation", { ...(vaSid ? { sid: vaSid } : {}), ...(projectId ? { project_id: projectId } : {}) }), parseAllocation);
    },
    async codeOwnSubmission(vaSid) { return parsed(await post(`/coding/submissions/${id(vaSid)}/code-now`), parseAllocation); },
    async recode(vaSid) { return parsed(await post(`/coding/recode/${id(vaSid)}`), parseAllocation); },
    async releaseCoding() { return parsed(await post("/coding/allocation/release"), parseCodingSave); },
    async allocateReviewer(vaSid) { return parsed(await post(`/reviewing/allocation/${id(vaSid)}`), parseAllocation); },
    async releaseReviewer() { return parsed(await post("/reviewing/allocation/release"), parseCodingSave); },
    async searchIcd(vaSid, classification, query) {
      const path = classification === "icd10"
        ? `/icd10/2019-2/coding-search/${id(vaSid)}`
        : `/icd11/coding-search/${id(vaSid)}`;
      const value = await get(`${path}?${new URLSearchParams({ q: query })}`);
      return parsed(value, parseIcdSearch);
    },
    async saveInitial(vaSid, body, mode = "coding") {
      const path = mode === "reviewing" ? `/reviewing/initial/${id(vaSid)}` : `/coding/initial/${id(vaSid)}`;
      return parsed(await post(path, body), parseCodingWrite);
    },
    async saveFinal(vaSid, body, mode = "coding") {
      const path = mode === "reviewing" ? `/reviewing/finalize/${id(vaSid)}` : `/coding/finalize/${id(vaSid)}`;
      return parsed(await post(path, body), parseCodingWrite);
    },
    async saveNotCodeable(vaSid, body) { return parsed(await post(`/coding/not-codeable/${id(vaSid)}`, body), parseCodingSave); },
    async saveNarrativeQuality(vaSid, body, mode = "coding") { return jsonObject(await post(`/va/${id(vaSid)}/narrative-qa`, { ...body, va_actiontype: mode === "reviewing" ? "varesumereviewing" : "varesumecoding" }), "narrative_qa.save"); },
    async saveSocialAutopsy(vaSid, body, mode = "coding") { return jsonObject(await post(`/va/${id(vaSid)}/social-autopsy`, { ...body, va_actiontype: mode === "reviewing" ? "varesumereviewing" : "varesumecoding" }), "social_autopsy.save"); },
    async getNote(vaSid, mode) { return parsed(await get(`/va/${id(vaSid)}/note?mode=${mode}`), parseNote); },
    async saveNote(vaSid, mode, content) { return parsed(await request(`${API}/va/${id(vaSid)}/note?mode=${mode}`, { method: "PUT", json: { content } }), parseNote); },
    async searchDorisTerms(vaSid, query, options = {}) {
      try {
        const limit = options.limit ?? 20;
        if (!Number.isInteger(limit) || limit < 1 || limit > 20) throw new WorkspaceContractError("request.doris.limit");
        return parsed(await post(`/doris-clinical/terms/${id(vaSid)}`, { schema_version: 1, query, limit, ...(options.subtreeUris ? { subtree_uris: options.subtreeUris } : {}) }), parseDorisTerms);
      } catch (error) { return normalizeDorisError(error); }
    },
    async getDorisCodeInfo(vaSid, code) {
      try { return parsed(await post(`/doris-clinical/codeinfo/${id(vaSid)}`, { schema_version: 1, code }), parseDorisCodeInfo); }
      catch (error) { return normalizeDorisError(error); }
    },
    async checkDorisSelection(vaSid, code, uri) {
      try { return parsed(await post(`/doris-clinical/selection-check/${id(vaSid)}`, { schema_version: 1, code, uri }), parseDorisCodeInfo); }
      catch (error) { return normalizeDorisError(error); }
    },
    async processDoris(vaSid, role, clientRevision, certificate) {
      try { return parsed(await post(`/doris-clinical/process/${id(vaSid)}`, { schema_version: 1, role, client_revision: clientRevision, certificate }), parseDorisProcess); }
      catch (error) { return normalizeDorisError(error); }
    },
    async getWorkflowEvents(vaSid, options) {
      const limit = options?.limit ?? 50;
      if (!Number.isInteger(limit) || limit < 1 || limit > 200) throw new WorkspaceContractError("request.limit");
      const cursor = options?.cursor;
      if (cursor !== undefined && (typeof cursor !== "string" || cursor.length === 0)) throw new WorkspaceContractError("request.cursor");
      const params = new URLSearchParams({ limit: String(limit) });
      if (cursor !== undefined) params.set("cursor", cursor);
      return parsed(await get(`/workflow/events/${id(vaSid)}?${params}`), value => parseWorkflowEvents(value, vaSid, limit));
    },
  };
}
