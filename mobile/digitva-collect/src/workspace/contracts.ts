/**
 * Runtime contracts for the coding and review workspace API. Required fields
 * consumed by the Expo screens are parsed here; unrelated additive fields are
 * ignored. Opaque certificates and engine results are validated as JSON trees.
 */
export type JsonValue = string | number | boolean | null | JsonValue[] | JsonObject;
export interface JsonObject { [key: string]: JsonValue }

export class WorkspaceContractError extends Error {
  constructor(readonly field: string) {
    super(`invalid_workspace_response:${field}`);
    this.name = "WorkspaceContractError";
  }
}

export type WorkspaceMode = "coding" | "reviewing" | "view";
export type CodingStep = "initial" | "final" | "done" | "view";
export type ProjectMode = "masked_simple" | "masked_doris" | "unmasked_simple" | "unmasked_doris";

export interface WorkspaceIdentity {
  vaSid: string;
  mode: WorkspaceMode;
}

/** Stable identity shared by DORIS, media, and workspace-owned components. */
export interface WorkspaceExtensionProps {
  identity: WorkspaceIdentity;
}

export interface DorisEditorProps extends WorkspaceExtensionProps {
  seed: NonNullable<WorkspacePayload["doris"]>;
  onProcess: (clientRevision: number, certificate: JsonObject) => Promise<DorisProcessReply>;
  onTerms: (query: string, limit?: number, subtreeUris?: string[]) => Promise<DorisTermsReply>;
  onCodeInfo: (code: string) => Promise<DorisCodeInfoReply>;
  onSelectionCheck: (code: string, uri: string) => Promise<DorisCodeInfoReply>;
}

export interface WorkspaceMediaProps extends WorkspaceExtensionProps {
  attachmentPath: string;
}

export interface DorisTerm {
  code: string;
  title: string;
  uri: string;
  release: string;
  matching_text: string;
  postcoordination: boolean;
  postcoordination_availability: JsonValue;
  related_maternal: boolean;
  related_perinatal: boolean;
  has_coding_note: boolean;
}

export interface DorisTermsReply {
  schema_version: 1;
  items: DorisTerm[];
  truncated: boolean;
  next_cursor: string | null;
}

export interface DorisCodeInfoItem extends JsonObject {
  code: string;
  title: string;
  uri: string;
  release: string;
  postcoordination: boolean;
}

export interface DorisCodeInfoReply {
  schema_version: 1;
  item: DorisCodeInfoItem;
}

export interface DorisProcessEngine {
  status: "completed" | "rejected" | "timeout" | "malformed_response" | "unavailable";
  result: JsonObject | null;
}

export interface DorisProcessReply {
  schema_version: 1;
  client_revision: number;
  icd_release: string;
  certificate: JsonObject;
  certificate_digest: string;
  result_digest: string;
  doris: DorisProcessEngine;
  codedit: DorisProcessEngine;
  process_token: string;
}

export interface WorkspaceCategoryNav {
  code: string;
  label: string;
  nav_label: string;
  render_mode: string;
}

export interface WorkspaceAssessment {
  id?: string;
  immediate_cod?: string | null;
  antecedent_cod?: string | null;
  conclusive_cod?: string | null;
  other_conditions?: string | string[] | null;
  remark?: string | null;
  reason?: string | null;
  other?: string | null;
  created_at?: string;
}

export interface NarrativeQuestion {
  key: string;
  label: string;
  options: Array<{ value: number; label: string }>;
}

export interface NarrativeQuality {
  fields: NarrativeQuestion[];
  max_score: number;
  saved: NarrativeSaved | null;
}

export interface NarrativeSaved {
  cannot_grade: boolean;
  values: Record<string, number>;
  score: number;
  rating: "Good" | "Fair" | "Poor" | "Cannot Grade";
}

export interface SocialAutopsyQuestion {
  delay_level: string;
  title: string;
  options: Array<{ option_code: string; label: string; description: string }>;
}

export interface SocialAutopsy {
  questions: SocialAutopsyQuestion[];
  saved: null | {
    selected_options: Array<{ delay_level: string; option_code: string }>;
    remark: string | null;
  };
}

export interface WorkspacePayload {
  case: {
    va_sid: string;
    instance_name: string;
    form_type_code: string;
    project_mode: ProjectMode;
    icd_classification: "icd10" | "icd11";
    workflow_state: string;
    narrative_qa_enabled: boolean;
    social_autopsy_enabled: boolean;
  };
  categories: WorkspaceCategoryNav[];
  default_category: string;
  step: CodingStep;
  blocked_by?: string[];
  assessments: {
    initial: WorkspaceAssessment | null;
    initial_prefill: WorkspaceAssessment | null;
    final: WorkspaceAssessment | null;
    not_codeable: WorkspaceAssessment | null;
    coder_initial?: WorkspaceAssessment | null;
    reviewer_initial?: WorkspaceAssessment | null;
    reviewer_final?: WorkspaceAssessment | null;
  };
  smartva: JsonValue;
  other_conditions_options: string[] | null;
  doris: null | {
    initial_certificate: JsonObject;
    prefill_provenance: JsonValue;
    saved_processing?: JsonObject | null;
    step1_certificate?: JsonObject | null;
    step1_processing?: JsonObject | null;
  };
  narrative_qa: NarrativeQuality | null;
  social_autopsy: SocialAutopsy | null;
}

export interface CategoryPayload {
  code: string;
  label: string;
  render_mode: string;
  summary_items: JsonValue[];
  subcategories: Array<{
    code: string;
    label: string;
    render_mode: string;
    items: Array<{ label: string; value: JsonValue; flip: boolean; info: boolean }>;
  }>;
  blocked_by?: string[];
}

export interface QueueCase {
  va_sid: string;
  va_uniqueid_masked: string;
  va_form_id: string;
  project_id: string;
  site_id: string;
  va_submission_date: string;
  va_data_collector: string | null;
  va_deceased_age: string | number | null;
  va_deceased_gender: string | null;
  va_narration_language: string | null;
  va_reviewed_at?: string;
  recodeable?: boolean;
}

export interface CodingStats {
  [key: string]: JsonValue;
}

export interface CoderQueue {
  forms: CoderAvailableCase[];
  count: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface CoderAvailableCase {
  va_sid: string;
  va_uniqueid_masked: string;
  va_form_id: string;
  project_id: string;
  site_id: string;
  va_submission_date: string;
  va_data_collector: string | null;
  va_deceased_age: string | number | null;
  va_deceased_gender: string | null;
}

export interface CoderHistoryCase {
  va_sid: string;
  va_uniqueid_masked: string;
  va_form_id: string;
  project_id: string;
  site_id: string;
  va_submission_date: string;
  va_deceased_age: string | number | null;
  va_deceased_gender: string | null;
  va_coding_date: string;
  va_code_status: string;
  recodeable: boolean;
}

export interface CoderHistory {
  history: CoderHistoryCase[];
  count: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface CoderProjects {
  projects: string[];
  project_options: Array<{ project_id: string; project_name: string }>;
}

export interface ReviewerStats {
  in_scope: number;
  completed: number;
  available: number;
  allocation: { va_sid: string } | null;
}

export interface ReviewerQueue {
  cases: QueueCase[];
  count: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface ReviewerHistory {
  history: QueueCase[];
  count: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface AllocationReply {
  va_sid: string;
  actiontype?: string;
  workflow_state?: string;
}

export interface AllocationSnapshot {
  va_sid: string;
}

export interface CodingWriteReply {
  va_sid: string;
  workflow_state?: string;
  initial_assessment_id?: string;
  reviewer_initial_assessment_id?: string;
  final_assessment_id?: string;
  reviewer_final_assessment_id?: string;
}

export interface IcdSearchItem {
  icd_code: string | null;
  icd_to_display: string;
  title?: string;
  linearization_uri?: string;
  class_kind?: string;
  tier?: string;
}

export interface CodingSaveReply {
  va_sid: string;
  workflow_state: string;
  initial_assessment_id?: string;
  final_assessment_id?: string;
  odk_synced?: boolean;
}

export interface NotePayload {
  va_sid: string;
  content: string | null;
  updated_at: string | null;
}

export interface WorkflowEvents {
  va_sid: string;
  events: Array<{
    event_id: string;
    transition_id: string;
    previous_state: string | null;
    current_state: string;
    actor_kind: string;
    actor_role: string | null;
    transition_reason: string | null;
    event_created_at: string;
  }>;
  limit: number;
  next_cursor: string | null;
}

function record(value: unknown, field: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new WorkspaceContractError(field);
  return value as Record<string, unknown>;
}

function string(value: unknown, field: string): string {
  if (typeof value !== "string") throw new WorkspaceContractError(field);
  return value;
}

function nullableString(value: unknown, field: string): string | null {
  return value === null ? null : string(value, field);
}

function boolean(value: unknown, field: string): boolean {
  if (typeof value !== "boolean") throw new WorkspaceContractError(field);
  return value;
}

function number(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) throw new WorkspaceContractError(field);
  return value;
}

function array<T>(value: unknown, field: string, parse: (item: unknown, field: string) => T): T[] {
  if (!Array.isArray(value)) throw new WorkspaceContractError(field);
  return value.map((item, index) => parse(item, `${field}[${index}]`));
}

export function parseJsonValue(value: unknown, field = "json"): JsonValue {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (Array.isArray(value)) return value.map((item, index) => parseJsonValue(item, `${field}[${index}]`));
  const source = record(value, field);
  const result: JsonObject = {};
  for (const [key, item] of Object.entries(source)) result[key] = parseJsonValue(item, `${field}.${key}`);
  return result;
}

function object(value: unknown, field: string): JsonObject {
  const parsed = parseJsonValue(value, field);
  if (parsed === null || Array.isArray(parsed) || typeof parsed !== "object") throw new WorkspaceContractError(field);
  return parsed;
}

function stringArray(value: unknown, field: string): string[] {
  return array(value, field, string);
}

function assessment(value: unknown, field: string): WorkspaceAssessment | null {
  if (value === null) return null;
  const source = record(value, field);
  const parsed: WorkspaceAssessment = {};
  for (const key of ["id", "created_at"] as const) {
    if (source[key] !== undefined) parsed[key] = string(source[key], `${field}.${key}`);
  }
  for (const key of ["immediate_cod", "antecedent_cod", "conclusive_cod", "remark", "reason", "other"] as const) {
    if (source[key] !== undefined) parsed[key] = nullableString(source[key], `${field}.${key}`);
  }
  if (source.other_conditions !== undefined) {
    if (source.other_conditions === null || typeof source.other_conditions === "string") parsed.other_conditions = source.other_conditions;
    else parsed.other_conditions = stringArray(source.other_conditions, `${field}.other_conditions`);
  }
  return parsed;
}

function question(value: unknown, field: string): NarrativeQuestion {
  const source = record(value, field);
  return { key: string(source.key, `${field}.key`), label: string(source.label, `${field}.label`), options: array(source.options, `${field}.options`, (item, itemField) => {
    const option = record(item, itemField);
    return { value: number(option.value, `${itemField}.value`), label: string(option.label, `${itemField}.label`) };
  }) };
}

function narrative(value: unknown): NarrativeQuality | null {
  if (value === null) return null;
  const source = record(value, "narrative_qa");
  const savedSource = source.saved === null ? null : record(source.saved, "narrative_qa.saved");
  let saved: NarrativeQuality["saved"] = null;
  if (savedSource) {
    const valuesSource = record(savedSource.values, "narrative_qa.saved.values");
    const values: Record<string, number> = {};
    for (const [key, answer] of Object.entries(valuesSource)) values[key] = number(answer, `narrative_qa.saved.values.${key}`);
    const ratingValue = string(savedSource.rating, "narrative_qa.saved.rating");
    let rating: NarrativeSaved["rating"];
    switch (ratingValue) {
      case "Good":
      case "Fair":
      case "Poor":
      case "Cannot Grade":
        rating = ratingValue;
        break;
      default:
        throw new WorkspaceContractError("narrative_qa.saved.rating");
    }
    saved = { cannot_grade: boolean(savedSource.cannot_grade, "narrative_qa.saved.cannot_grade"), values, score: number(savedSource.score, "narrative_qa.saved.score"), rating };
  }
  return { fields: array(source.fields, "narrative_qa.fields", question), max_score: number(source.max_score, "narrative_qa.max_score"), saved };
}

function socialQuestion(value: unknown, field: string): SocialAutopsyQuestion {
  const source = record(value, field);
  return { delay_level: string(source.delay_level, `${field}.delay_level`), title: string(source.title, `${field}.title`), options: array(source.options, `${field}.options`, (item, itemField) => {
    const option = record(item, itemField);
    return { option_code: string(option.option_code, `${itemField}.option_code`), label: string(option.label, `${itemField}.label`), description: string(option.description, `${itemField}.description`) };
  }) };
}

function socialAutopsy(value: unknown): SocialAutopsy | null {
  if (value === null) return null;
  const source = record(value, "social_autopsy");
  const savedSource = source.saved === null ? null : record(source.saved, "social_autopsy.saved");
  const saved = savedSource === null ? null : {
    selected_options: array(savedSource.selected_options, "social_autopsy.saved.selected_options", (item, field) => {
      const option = record(item, field);
      return { delay_level: string(option.delay_level, `${field}.delay_level`), option_code: string(option.option_code, `${field}.option_code`) };
    }),
    remark: nullableString(savedSource.remark, "social_autopsy.saved.remark"),
  };
  return { questions: array(source.questions, "social_autopsy.questions", socialQuestion), saved };
}

export function parseWorkspace(value: unknown, mode: WorkspaceMode): WorkspacePayload {
  const source = record(value, "workspace");
  const caseSource = record(source.case, "workspace.case");
  const projectMode = string(caseSource.project_mode, "workspace.case.project_mode");
  if (!["masked_simple", "masked_doris", "unmasked_simple", "unmasked_doris"].includes(projectMode)) throw new WorkspaceContractError("workspace.case.project_mode");
  const classification = string(caseSource.icd_classification, "workspace.case.icd_classification");
  if (classification !== "icd10" && classification !== "icd11") throw new WorkspaceContractError("workspace.case.icd_classification");
  const step = string(source.step, "workspace.step");
  if (!["initial", "final", "done", "view"].includes(step)) throw new WorkspaceContractError("workspace.step");
  const blockedBy = stringArray(source.blocked_by, "workspace.blocked_by");
  const assessmentsSource = record(source.assessments, "workspace.assessments");
  const dorisSource = source.doris === null ? null : record(source.doris, "workspace.doris");
  const doris = dorisSource === null ? null : {
    initial_certificate: object(dorisSource.initial_certificate, "workspace.doris.initial_certificate"),
    prefill_provenance: parseJsonValue(dorisSource.prefill_provenance, "workspace.doris.prefill_provenance"),
    ...(dorisSource.saved_processing !== undefined ? { saved_processing: dorisSource.saved_processing === null ? null : object(dorisSource.saved_processing, "workspace.doris.saved_processing") } : {}),
    ...(dorisSource.step1_certificate !== undefined ? { step1_certificate: dorisSource.step1_certificate === null ? null : object(dorisSource.step1_certificate, "workspace.doris.step1_certificate") } : {}),
    ...(dorisSource.step1_processing !== undefined ? { step1_processing: dorisSource.step1_processing === null ? null : object(dorisSource.step1_processing, "workspace.doris.step1_processing") } : {}),
  };
  const result: WorkspacePayload = {
    case: {
      va_sid: string(caseSource.va_sid, "workspace.case.va_sid"),
      instance_name: string(caseSource.instance_name, "workspace.case.instance_name"),
      form_type_code: string(caseSource.form_type_code, "workspace.case.form_type_code"),
      project_mode: projectMode as ProjectMode,
      icd_classification: classification,
      workflow_state: string(caseSource.workflow_state, "workspace.case.workflow_state"),
      narrative_qa_enabled: boolean(caseSource.narrative_qa_enabled, "workspace.case.narrative_qa_enabled"),
      social_autopsy_enabled: boolean(caseSource.social_autopsy_enabled, "workspace.case.social_autopsy_enabled"),
    },
    categories: array(source.categories, "workspace.categories", (item, field) => {
      const category = record(item, field);
      return { code: string(category.code, `${field}.code`), label: string(category.label, `${field}.label`), nav_label: string(category.nav_label, `${field}.nav_label`), render_mode: string(category.render_mode, `${field}.render_mode`) };
    }),
    default_category: string(source.default_category, "workspace.default_category"),
    step: step as CodingStep,
    ...(mode === "view" ? {} : { blocked_by: blockedBy }),
    assessments: {
      initial: assessment(assessmentsSource.initial, "workspace.assessments.initial"),
      initial_prefill: assessment(assessmentsSource.initial_prefill, "workspace.assessments.initial_prefill"),
      final: assessment(assessmentsSource.final, "workspace.assessments.final"),
      not_codeable: assessment(assessmentsSource.not_codeable, "workspace.assessments.not_codeable"),
      ...(assessmentsSource.coder_initial !== undefined ? { coder_initial: assessment(assessmentsSource.coder_initial, "workspace.assessments.coder_initial") } : {}),
      ...(assessmentsSource.reviewer_initial !== undefined ? { reviewer_initial: assessment(assessmentsSource.reviewer_initial, "workspace.assessments.reviewer_initial") } : {}),
      ...(assessmentsSource.reviewer_final !== undefined ? { reviewer_final: assessment(assessmentsSource.reviewer_final, "workspace.assessments.reviewer_final") } : {}),
    },
    smartva: parseJsonValue(source.smartva, "workspace.smartva"),
    other_conditions_options: source.other_conditions_options === null ? null : stringArray(source.other_conditions_options, "workspace.other_conditions_options"),
    doris,
    narrative_qa: narrative(source.narrative_qa),
    social_autopsy: socialAutopsy(source.social_autopsy),
  };
  if (mode === "view") {
    if (result.step !== "view" || blockedBy.length || result.doris !== null || result.narrative_qa !== null || result.social_autopsy !== null || result.other_conditions_options !== null || caseSource.narrative_qa_enabled !== false || caseSource.social_autopsy_enabled !== false || result.assessments.initial !== null || result.assessments.initial_prefill !== null) throw new WorkspaceContractError("workspace.view");
  } else if (result.step === "view") {
    throw new WorkspaceContractError("workspace.step");
  }
  if (mode === "coding" && result.case.project_mode.startsWith("masked_") && result.step === "initial" && (result.assessments.final !== null || result.smartva !== null)) throw new WorkspaceContractError("workspace.masked_step1");
  return result;
}

export function parseCategory(value: unknown, mode: WorkspaceMode): CategoryPayload {
  const source = record(value, "category");
  const blockedBy = source.blocked_by === undefined ? undefined : stringArray(source.blocked_by, "category.blocked_by");
  const category: CategoryPayload = {
    code: string(source.code, "category.code"), label: string(source.label, "category.label"), render_mode: string(source.render_mode, "category.render_mode"),
    summary_items: array(source.summary_items, "category.summary_items", parseJsonValue),
    subcategories: array(source.subcategories, "category.subcategories", (item, field) => {
      const subcategory = record(item, field);
      return { code: string(subcategory.code, `${field}.code`), label: string(subcategory.label, `${field}.label`), render_mode: string(subcategory.render_mode, `${field}.render_mode`), items: array(subcategory.items, `${field}.items`, (entry, itemField) => {
        const itemObject = record(entry, itemField);
        return { label: string(itemObject.label, `${itemField}.label`), value: parseJsonValue(itemObject.value, `${itemField}.value`), flip: boolean(itemObject.flip, `${itemField}.flip`), info: boolean(itemObject.info, `${itemField}.info`) };
      }) };
    }),
    ...(blockedBy !== undefined && mode !== "view" ? { blocked_by: blockedBy } : {}),
  };
  if (mode === "view" && blockedBy?.length) throw new WorkspaceContractError("category.blocked_by");
  return category;
}

function queueCase(value: unknown, field: string): QueueCase {
  const source = record(value, field);
  const age = source.va_deceased_age;
  if (age !== null && typeof age !== "string" && typeof age !== "number") throw new WorkspaceContractError(`${field}.va_deceased_age`);
  return {
    va_sid: string(source.va_sid, `${field}.va_sid`), va_uniqueid_masked: string(source.va_uniqueid_masked, `${field}.va_uniqueid_masked`), va_form_id: string(source.va_form_id, `${field}.va_form_id`), project_id: string(source.project_id, `${field}.project_id`), site_id: string(source.site_id, `${field}.site_id`), va_submission_date: string(source.va_submission_date, `${field}.va_submission_date`), va_data_collector: nullableString(source.va_data_collector, `${field}.va_data_collector`), va_deceased_age: age as string | number | null, va_deceased_gender: nullableString(source.va_deceased_gender, `${field}.va_deceased_gender`), va_narration_language: nullableString(source.va_narration_language, `${field}.va_narration_language`),
    ...(source.va_reviewed_at !== undefined ? { va_reviewed_at: string(source.va_reviewed_at, `${field}.va_reviewed_at`) } : {}),
    ...(source.recodeable !== undefined ? { recodeable: boolean(source.recodeable, `${field}.recodeable`) } : {}),
  };
}

function coderAvailableCase(value: unknown, field: string): CoderAvailableCase {
  const source = record(value, field);
  const age = source.va_deceased_age;
  if (age !== null && typeof age !== "string" && typeof age !== "number") throw new WorkspaceContractError(`${field}.va_deceased_age`);
  return {
    va_sid: string(source.va_sid, `${field}.va_sid`),
    va_uniqueid_masked: string(source.va_uniqueid_masked, `${field}.va_uniqueid_masked`),
    va_form_id: string(source.va_form_id, `${field}.va_form_id`),
    project_id: string(source.project_id, `${field}.project_id`),
    site_id: string(source.site_id, `${field}.site_id`),
    va_submission_date: string(source.va_submission_date, `${field}.va_submission_date`),
    va_data_collector: nullableString(source.va_data_collector, `${field}.va_data_collector`),
    va_deceased_age: age as string | number | null,
    va_deceased_gender: nullableString(source.va_deceased_gender, `${field}.va_deceased_gender`),
  };
}

function coderHistoryCase(value: unknown, field: string): CoderHistoryCase {
  const source = record(value, field);
  const age = source.va_deceased_age;
  if (age !== null && typeof age !== "string" && typeof age !== "number") throw new WorkspaceContractError(`${field}.va_deceased_age`);
  return {
    va_sid: string(source.va_sid, `${field}.va_sid`),
    va_uniqueid_masked: string(source.va_uniqueid_masked, `${field}.va_uniqueid_masked`),
    va_form_id: string(source.va_form_id, `${field}.va_form_id`),
    project_id: string(source.project_id, `${field}.project_id`),
    site_id: string(source.site_id, `${field}.site_id`),
    va_submission_date: string(source.va_submission_date, `${field}.va_submission_date`),
    va_deceased_age: age as string | number | null,
    va_deceased_gender: nullableString(source.va_deceased_gender, `${field}.va_deceased_gender`),
    va_coding_date: string(source.va_coding_date, `${field}.va_coding_date`),
    va_code_status: string(source.va_code_status, `${field}.va_code_status`),
    recodeable: boolean(source.recodeable, `${field}.recodeable`),
  };
}

export function parseCodingStats(value: unknown): CodingStats {
  const source = record(value, "coding.stats");
  const parsed: CodingStats = {};
  for (const [key, item] of Object.entries(source)) parsed[key] = parseJsonValue(item, `coding.stats.${key}`);
  return parsed;
}

export function parseCoderQueue(value: unknown, expectedLimit: number, expectedOffset: number): CoderQueue {
  const source = record(value, "coding.available");
  if (Array.isArray(source.forms) && source.forms.length > expectedLimit) throw new WorkspaceContractError("coding.available.paging");
  const forms = array(source.forms, "coding.available.forms", coderAvailableCase);
  const count = number(source.count, "coding.available.count");
  const limit = number(source.limit, "coding.available.limit");
  const offset = number(source.offset, "coding.available.offset");
  const has_more = boolean(source.has_more, "coding.available.has_more");
  if (!Number.isInteger(count) || count !== forms.length || limit !== expectedLimit || offset !== expectedOffset) throw new WorkspaceContractError("coding.available.paging");
  return { forms, count, limit, offset, has_more };
}

export function parseCoderHistory(value: unknown, expectedLimit: number, expectedOffset: number): CoderHistory {
  const source = record(value, "coding.history");
  if (Array.isArray(source.history) && source.history.length > expectedLimit) throw new WorkspaceContractError("coding.history.paging");
  const history = array(source.history, "coding.history.history", coderHistoryCase);
  const count = number(source.count, "coding.history.count");
  const limit = number(source.limit, "coding.history.limit");
  const offset = number(source.offset, "coding.history.offset");
  const has_more = boolean(source.has_more, "coding.history.has_more");
  if (!Number.isInteger(count) || count !== history.length || limit !== expectedLimit || offset !== expectedOffset) throw new WorkspaceContractError("coding.history.paging");
  return { history, count, limit, offset, has_more };
}

export function parseCoderProjects(value: unknown): CoderProjects {
  const source = record(value, "coding.projects");
  return { projects: stringArray(source.projects, "coding.projects.projects"), project_options: array(source.project_options, "coding.projects.project_options", (item, field) => {
    const option = record(item, field);
    return { project_id: string(option.project_id, `${field}.project_id`), project_name: string(option.project_name, `${field}.project_name`) };
  }) };
}

export function parseReviewerStats(value: unknown): ReviewerStats {
  const source = record(value, "reviewing.stats");
  const allocation = source.allocation === null ? null : { va_sid: string(record(source.allocation, "reviewing.stats.allocation").va_sid, "reviewing.stats.allocation.va_sid") };
  return { in_scope: number(source.in_scope, "reviewing.stats.in_scope"), completed: number(source.completed, "reviewing.stats.completed"), available: number(source.available, "reviewing.stats.available"), allocation };
}

export function parseReviewerQueue(value: unknown, expectedLimit: number, expectedOffset: number): ReviewerQueue {
  const source = record(value, "reviewing.available");
  if (Array.isArray(source.cases) && source.cases.length > expectedLimit) throw new WorkspaceContractError("reviewing.available.paging");
  const cases = array(source.cases, "reviewing.available.cases", queueCase);
  const count = number(source.count, "reviewing.available.count");
  const limit = number(source.limit, "reviewing.available.limit");
  const offset = number(source.offset, "reviewing.available.offset");
  const has_more = boolean(source.has_more, "reviewing.available.has_more");
  if (!Number.isInteger(count) || count !== cases.length || limit !== expectedLimit || offset !== expectedOffset) throw new WorkspaceContractError("reviewing.available.paging");
  return { cases, count, limit, offset, has_more };
}

export function parseReviewerHistory(value: unknown, expectedLimit: number, expectedOffset: number): ReviewerHistory {
  const source = record(value, "reviewing.history");
  if (Array.isArray(source.history) && source.history.length > expectedLimit) throw new WorkspaceContractError("reviewing.history.paging");
  const history = array(source.history, "reviewing.history.history", queueCase);
  const count = number(source.count, "reviewing.history.count");
  const limit = number(source.limit, "reviewing.history.limit");
  const offset = number(source.offset, "reviewing.history.offset");
  const has_more = boolean(source.has_more, "reviewing.history.has_more");
  if (!Number.isInteger(count) || count !== history.length || limit !== expectedLimit || offset !== expectedOffset) throw new WorkspaceContractError("reviewing.history.paging");
  return { history, count, limit, offset, has_more };
}

export function parseAllocation(value: unknown): AllocationReply {
  const source = record(value, "allocation");
  return { va_sid: string(source.va_sid, "allocation.va_sid"), ...(source.actiontype !== undefined ? { actiontype: string(source.actiontype, "allocation.actiontype") } : {}), ...(source.workflow_state !== undefined ? { workflow_state: string(source.workflow_state, "allocation.workflow_state") } : {}) };
}

export function parseOptionalAllocation(value: unknown): AllocationSnapshot | null {
  const source = record(value, "allocation.response");
  const allocation = source.allocation;
  return allocation === null ? null : { va_sid: string(record(allocation, "allocation.response.allocation").va_sid, "allocation.response.allocation.va_sid") };
}

export function parseCodingSave(value: unknown): CodingSaveReply {
  const source = record(value, "coding.save");
  const reply: CodingSaveReply = { va_sid: string(source.va_sid, "coding.save.va_sid"), workflow_state: string(source.workflow_state, "coding.save.workflow_state") };
  for (const key of ["initial_assessment_id", "final_assessment_id"] as const) if (source[key] !== undefined) reply[key] = string(source[key], `coding.save.${key}`);
  if (source.odk_synced !== undefined) reply.odk_synced = boolean(source.odk_synced, "coding.save.odk_synced");
  return reply;
}

export function parseCodingWrite(value: unknown): CodingWriteReply {
  const source = record(value, "coding.write");
  const reply: CodingWriteReply = { va_sid: string(source.va_sid, "coding.write.va_sid") };
  for (const key of ["workflow_state", "initial_assessment_id", "reviewer_initial_assessment_id", "final_assessment_id", "reviewer_final_assessment_id"] as const) {
    if (source[key] !== undefined) reply[key] = string(source[key], `coding.write.${key}`);
  }
  if (!reply.initial_assessment_id && !reply.reviewer_initial_assessment_id && !reply.final_assessment_id && !reply.reviewer_final_assessment_id) throw new WorkspaceContractError("coding.write.assessment_id");
  return reply;
}

export function parseIcdSearch(value: unknown): IcdSearchItem[] {
  return array(value, "icd.search", (item, field) => {
    const source = record(item, field);
    const code = source.icd_code;
    if (code !== null && typeof code !== "string") throw new WorkspaceContractError(`${field}.icd_code`);
    const result: IcdSearchItem = { icd_code: code, icd_to_display: string(source.icd_to_display, `${field}.icd_to_display`) };
    for (const key of ["title", "linearization_uri", "class_kind", "tier"] as const) if (source[key] !== undefined) result[key] = string(source[key], `${field}.${key}`);
    return result;
  });
}

export function parseNote(value: unknown): NotePayload {
  const source = record(value, "note");
  return { va_sid: string(source.va_sid, "note.va_sid"), content: nullableString(source.content, "note.content"), updated_at: nullableString(source.updated_at, "note.updated_at") };
}

export function parseWorkflowEvents(value: unknown, expectedVaSid: string, expectedLimit: number): WorkflowEvents {
  const source = record(value, "workflow.events");
  const va_sid = string(source.va_sid, "workflow.events.va_sid");
  const events = array(source.events, "workflow.events.events", (item, field) => {
    const event = record(item, field);
    return { event_id: string(event.event_id, `${field}.event_id`), transition_id: string(event.transition_id, `${field}.transition_id`), previous_state: nullableString(event.previous_state, `${field}.previous_state`), current_state: string(event.current_state, `${field}.current_state`), actor_kind: string(event.actor_kind, `${field}.actor_kind`), actor_role: nullableString(event.actor_role, `${field}.actor_role`), transition_reason: nullableString(event.transition_reason, `${field}.transition_reason`), event_created_at: string(event.event_created_at, `${field}.event_created_at`) };
  });
  const limit = number(source.limit, "workflow.events.limit");
  const next_cursor = nullableString(source.next_cursor, "workflow.events.next_cursor");
  if (va_sid !== expectedVaSid) throw new WorkspaceContractError("workflow.events.va_sid");
  if (!Number.isInteger(limit) || limit !== expectedLimit || events.length > limit) throw new WorkspaceContractError("workflow.events.limit");
  if (next_cursor === "") throw new WorkspaceContractError("workflow.events.next_cursor");
  return { va_sid, events, limit, next_cursor };
}

export function parseDorisTerms(value: unknown): DorisTermsReply {
  const source = record(value, "doris.terms");
  if (source.schema_version !== 1) throw new WorkspaceContractError("doris.terms.schema_version");
  const cursor = source.next_cursor;
  if (cursor !== null && typeof cursor !== "string") throw new WorkspaceContractError("doris.terms.next_cursor");
  return {
    schema_version: 1,
    items: array(source.items, "doris.terms.items", (item, field) => {
      const term = record(item, field);
      return {
        code: string(term.code, `${field}.code`), title: string(term.title, `${field}.title`), uri: string(term.uri, `${field}.uri`), release: string(term.release, `${field}.release`), matching_text: string(term.matching_text, `${field}.matching_text`), postcoordination: boolean(term.postcoordination, `${field}.postcoordination`), postcoordination_availability: parseJsonValue(term.postcoordination_availability, `${field}.postcoordination_availability`), related_maternal: boolean(term.related_maternal, `${field}.related_maternal`), related_perinatal: boolean(term.related_perinatal, `${field}.related_perinatal`), has_coding_note: boolean(term.has_coding_note, `${field}.has_coding_note`),
      };
    }),
    truncated: boolean(source.truncated, "doris.terms.truncated"),
    next_cursor: cursor,
  };
}

export function parseDorisCodeInfo(value: unknown): DorisCodeInfoReply {
  const source = record(value, "doris.codeinfo");
  if (source.schema_version !== 1) throw new WorkspaceContractError("doris.codeinfo.schema_version");
  const rawItem = record(source.item, "doris.codeinfo.item");
  const parsed = parseJsonValue(rawItem, "doris.codeinfo.item");
  if (parsed === null || Array.isArray(parsed) || typeof parsed !== "object") throw new WorkspaceContractError("doris.codeinfo.item");
  return {
    schema_version: 1,
    item: {
      ...parsed,
      code: string(rawItem.code, "doris.codeinfo.item.code"),
      title: string(rawItem.title, "doris.codeinfo.item.title"),
      uri: string(rawItem.uri, "doris.codeinfo.item.uri"),
      release: string(rawItem.release, "doris.codeinfo.item.release"),
      postcoordination: boolean(rawItem.postcoordination, "doris.codeinfo.item.postcoordination"),
    },
  };
}

export function parseDorisProcess(value: unknown): DorisProcessReply {
  const source = record(value, "doris.process");
  if (source.schema_version !== 1) throw new WorkspaceContractError("doris.process.schema_version");
  const revision = number(source.client_revision, "doris.process.client_revision");
  if (!Number.isInteger(revision) || revision < 0) throw new WorkspaceContractError("doris.process.client_revision");
  const engine = (value: unknown, field: string): DorisProcessEngine => {
    const item = record(value, field);
    const status = string(item.status, `${field}.status`);
    if (!["completed", "rejected", "timeout", "malformed_response", "unavailable"].includes(status)) throw new WorkspaceContractError(`${field}.status`);
    return { status: status as DorisProcessEngine["status"], result: item.result === null ? null : object(item.result, `${field}.result`) };
  };
  return {
    schema_version: 1,
    client_revision: revision,
    icd_release: string(source.icd_release, "doris.process.icd_release"),
    certificate: object(source.certificate, "doris.process.certificate"),
    certificate_digest: string(source.certificate_digest, "doris.process.certificate_digest"),
    result_digest: string(source.result_digest, "doris.process.result_digest"),
    doris: engine(source.doris, "doris.process.doris"),
    codedit: engine(source.codedit, "doris.process.codedit"),
    process_token: string(source.process_token, "doris.process.process_token"),
  };
}
