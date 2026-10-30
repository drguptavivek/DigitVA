/**
 * The Collect Plus "Try DORIS" demo (Help, no sign-in): the offline DORIS editor over the on-phone engine with
 * nothing behind it. It reuses the offline coding path (createOfflineDorisEditor, createGuidanceRequester) and answers
 * only the four DORIS data calls; every other WorkspaceApi call refuses, so the demo can reach no server, no case, no
 * store and no queue. Certificates are never logged or kept.
 */
import { ApiError } from "../api";
import { t } from "../i18n";
import examplesFile from "../../assets/doris-help-examples.json";
import type { OfflineEngine } from "../offlineEngine";
import type { WorkspaceApi } from "./api";
import type { JsonObject, WorkspacePayload } from "./contracts";
import { createOfflineDorisEditor, type OfflineDorisEditor } from "./offlineDoris";

export interface DorisDemoExample {
  id: string;
  label: string;
  purpose: string;
  certificate: JsonObject;
}

/** The id of the blank certificate. */
export const DORIS_DEMO_BLANK = "blank";

/**
 * WHO's six synthetic certificates (assets/doris-help-examples.json, a build-time copy of
 * resource/doris_help_examples.json: Metro does not watch outside the app root). Only id, label, purpose and
 * certificate are kept: WHO's recorded `observed` results are dropped here, so no screen can show them.
 */
export const DORIS_DEMO_EXAMPLES: readonly DorisDemoExample[] = examplesFile.examples.map(({ id, label, purpose, certificate }) => ({
  id, label, purpose, certificate: certificate as unknown as JsonObject,
}));

const deepCopy = (value: JsonObject): JsonObject => JSON.parse(JSON.stringify(value)) as JsonObject;

/** The certificate DORIS starts from: a copy of the example, else (blank or unknown id) the empty certificate. */
export function demoCertificate(exampleId: string): JsonObject {
  const example = DORIS_DEMO_EXAMPLES.find((item) => item.id === exampleId);
  return example ? deepCopy(example.certificate) : { ICDVersion: "ICD11" };
}

/** One id per load (example id and a load counter): DorisPanel keys its editor state on it, so every load starts clean. */
export const demoVaSid = (exampleId: string, load = 0): string => `demo-${exampleId}-${load}`;

/** The workspace DorisPanel opens on: Step 1, unmasked, no assessments, no interview prefill. */
export function demoWorkspace(exampleId: string, load = 0): WorkspacePayload {
  const vaSid = demoVaSid(exampleId, load);
  return {
    case: {
      va_sid: vaSid,
      instance_name: vaSid,
      form_type_code: "DORIS_DEMO",
      project_mode: "unmasked_doris",
      icd_classification: "icd11",
      workflow_state: "coding",
      narrative_qa_enabled: false,
      social_autopsy_enabled: false,
    },
    categories: [],
    default_category: "",
    step: "initial",
    assessments: { initial: null, initial_prefill: null, final: null, not_codeable: null },
    smartva: null,
    other_conditions_options: null,
    doris: { initial_certificate: demoCertificate(exampleId), prefill_provenance: {}, saved_processing: null },
    narrative_qa: null,
    social_autopsy: null,
  };
}

const refuse = (): Promise<never> => Promise.reject(new Error("doris_demo_unavailable"));

/** The editor over the engine with a store that refuses: the demo's editor can never persist or read a coding. */
export function createDorisDemoEditor(engine: OfflineEngine): OfflineDorisEditor {
  return createOfflineDorisEditor(engine, { save: refuse, get: refuse });
}

/** The save buttons stay in DorisPanel; pressing one shows this and writes nothing. */
function noSave(): Promise<never> {
  const message = t("dorisDemoNoSave");
  return Promise.reject(new ApiError(400, "doris_demo", undefined, undefined, { error: message, messages: [message] }));
}

/**
 * The WorkspaceApi DorisPanel gets: the four DORIS data calls (each first checks `allowed`, the device-wide
 * ICD-11 / DORIS switch), no VA definitions, saves that say the demo keeps nothing, and a refusal for the rest.
 */
export function createDorisDemoApi(editor: OfflineDorisEditor, allowed: () => Promise<void>): WorkspaceApi {
  return {
    getWorkspace: refuse,
    getCategory: refuse,
    getCodingStats: refuse,
    getCodingAvailable: refuse,
    getCodingHistory: refuse,
    getCodingProjects: refuse,
    getCodingAllocation: refuse,
    getReviewerProjects: refuse,
    getReviewerStats: refuse,
    getReviewerAvailable: refuse,
    getReviewerHistory: refuse,
    getReviewerAllocation: refuse,
    allocateCoding: refuse,
    codeOwnSubmission: refuse,
    recode: refuse,
    releaseCoding: refuse,
    allocateReviewer: refuse,
    releaseReviewer: refuse,
    searchIcd: refuse,
    runSmartva: refuse,
    getSmartvaStatus: refuse,
    saveNarrativeQuality: refuse,
    saveSocialAutopsy: refuse,
    getNote: refuse,
    saveNote: refuse,
    getWorkflowEvents: refuse,
    saveInitial: noSave,
    saveFinal: noSave,
    saveNotCodeable: noSave,
    // VA causes are a coding-workflow crosswalk; the demo has none.
    getVaDefinitionForIcd: async () => null,
    async searchDorisTerms(_vaSid, query, options) {
      await allowed();
      return editor.onTerms(query, options?.limit, options?.subtreeUris);
    },
    async getDorisCodeInfo(_vaSid, code) { await allowed(); return editor.onCodeInfo(code); },
    async checkDorisSelection(_vaSid, code, uri) { await allowed(); return editor.onSelectionCheck(code, uri); },
    async processDoris(_vaSid, _role, clientRevision, certificate) {
      await allowed();
      return editor.onProcess(clientRevision, certificate);
    },
  };
}
