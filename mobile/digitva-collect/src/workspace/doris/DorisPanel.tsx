import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { AppState as NativeAppState, Text, View } from "react-native";

import { ApiError } from "../../api";
import { t as tr } from "../../i18n";
import { errorText } from "../../ui";
import type { JsonRequester, WorkspaceApi } from "../api";
import type { DorisProcessReply, JsonObject, JsonValue, WorkspaceAssessment, WorkspaceIdentity, WorkspacePayload } from "../contracts";
import { parseDorisProcess, parseUcodParts } from "../contracts";
import { radius, ui, useTheme } from "../../theme";
import { Cell, ChipChoice, FieldLabel, IntervalErrorContext, IntervalField, SearchBox, Warn, lineShade } from "./compact";
import { DateField } from "./DateField";
import { todayIso } from "./dateFieldShared";
import { IcdPickerModal } from "./IcdPickerModal";
import type { PickerChoice, PickerInit } from "./pickerBridge";
import { Alert, Badge, Body, Button, ButtonGlyph, Card, CardTitle, Chip, FieldHint, Input, Label, Muted, ReportBox, SectionTitle, Separator, Textarea, chartFor, gap, uiRadius, useLayout, useUi } from "./ui";
import { applyVisibility, derivesAtLoad, deriveEstimatedAge, reportedAge, visibility, warnings, type Age, type Visibility, type Warnings } from "./rules";
import { AssociatedVaCodes, CodeDetailsSheet } from "./CodeDetailsSheet";
import { SmartVaReference } from "../SmartVaReference";
import { UCOD_CLUSTER_EXPLANATION, certificateTitle, collapseBlankLines, icd11Alternatives, summaryChecks, ucodClusterLines } from "./resultSummary";
import { dorisWarningCodes } from "./dorisWarnings";
import { browserDraftGeneration, clearCaseBrowserDraft, clearCodDraft, draftContext, readCodDraft, saveCodDraft } from "./browserDraft";

type CertificateState = {
  owner: { api: WorkspaceApi; request: JsonRequester; vaSid: string; mode: WorkspaceIdentity["mode"]; step: WorkspacePayload["step"]; projectMode: WorkspacePayload["case"]["project_mode"]; fingerprint?: string | null; recoveryGeneration: number };
  certificate: JsonObject;
  revision: number;
  processing: DorisProcessReply | null;
  selectedCause: { code: string; title: string; uri: string } | null;
  error: string;
  notice: string;
  busy: boolean;
  reconfirm: boolean;
  cleared: boolean;
  /** Administrative data was supplied or entered; its card then stays even after every field is cleared. */
  adminSeen: boolean;
  /** EstimatedAge value this editor derived from the two dates last (rules.ts deriveEstimatedAge); null when none. */
  derivedAge: string | null;
  /** The coder's or reviewer's final-COD remark; sent only with the final save. */
  remark: string;
};

type CertificateLine = JsonObject & { Conditions: JsonObject[] };
const NOT_SET_VALUE = "__not_set__";
/** The blank choice, worded as the web editor words it. */
const NOT_STATED = "Not stated";
const DEFAULT_PART1_LINES = 3;
const MAX_PART1_LINES = 5;

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function object(value: unknown): JsonObject {
  return isRecord(value) ? value as JsonObject : {};
}

function array(value: unknown): JsonValue[] {
  return Array.isArray(value) ? value : [];
}

function text(value: JsonValue | undefined): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

/** Adds a condition to a line; a new condition inherits the line's onset interval. */
function appendCondition(line: JsonObject, condition: JsonObject): CertificateLine {
  const conditions = lineConditions(line);
  const interval = text(conditions[0]?.Interval);
  return { ...line, Conditions: [...conditions, { ...condition, ...(interval ? { Interval: interval } : {}) }] };
}

/** `query` is what was typed in the line's search box ("" opens the picker with its own search focused). */
type PickerTarget = ({ kind: "part1"; index: number } | { kind: "part2" } | { kind: "final" }) & { query: string };

function lineTitle(index: number, part2: boolean): string {
  return part2 ? "Significant conditions contributing to death" : index === 0 ? "Immediate cause" : "Due to";
}

/** WHO letter for a Part I line: A is the immediate cause, then B, C, D, E. */
function lineLetter(index: number): string {
  return String.fromCharCode(65 + index);
}

/** A field counts as answered when it holds anything but "" (the editor deletes cleared keys). */
const hasValue = (value: JsonValue | undefined): boolean => value !== undefined && value !== "";

/** "from interview (Id10077)" exactly as the web editor builds it from prefill_provenance; undefined when the field was not prefilled. */
function provenanceBadge(provenance: JsonObject, path: string): string | undefined {
  const entry = object(provenance[path]);
  const sources = array(entry.sources).filter((item): item is string => typeof item === "string");
  if (!sources.length) return undefined;
  return `from interview (${sources.join(", ")}${typeof entry.note === "string" && entry.note ? `; ${entry.note}` : ""})`;
}

function copy(value: JsonObject): JsonObject {
  return JSON.parse(JSON.stringify(value)) as JsonObject;
}

function lineConditions(value: JsonValue | undefined): JsonObject[] {
  return array(object(value).Conditions).filter(isRecord) as JsonObject[];
}

function initialCertificate(workspace: WorkspacePayload): { certificate: JsonObject; derivedAge: string | null } {
  const seed = workspace.doris?.initial_certificate;
  // Age first: a derived age can hide or show sections, so visibility is applied to the dated seed.
  // Only a fresh prefill seed derives here (V7); a saved certificate keeps the EstimatedAge it was saved with.
  const dated = seed && derivesAtLoad(workspace.doris?.prefill_provenance, workspace.doris?.saved_processing) ? deriveEstimatedAge(seed, null) : { certificate: seed ?? {}, derived: null };
  // Hidden sections never enter the editor, so they cannot resurface later if the age or sex is edited.
  const certificate = seed ? applyVisibility(dated.certificate) : { ICDVersion: "ICD11", Part1: [] };
  // The served seed holds only prefilled answers; DORIS rejects a certificate without its version.
  certificate.ICDVersion = "ICD11";
  if (!Array.isArray(certificate.Part1)) certificate.Part1 = [];
  // Immediate cause plus two "Due to" lines; trailing empty lines are dropped by processCertificate.
  while (certificate.Part1.length < DEFAULT_PART1_LINES) certificate.Part1.push({ Conditions: [] });
  return { certificate, derivedAge: dated.derived };
}

function hasAdministrativeData(certificate: JsonObject): boolean {
  return Object.keys(object(certificate.AdministrativeData)).length > 0;
}

/**
 * Unsaved editor drafts, in memory only, per signed-in requester and per `draftKey`. They survive the panel
 * unmounting on a section switch, a hidden tab (the workspace suspends) and the ICD browser tab, and are
 * dropped on a successful save or a lost allocation. browserDraft.ts separately keeps only the
 * owner-approved COD fields and remarks in per-tab storage, without processing proof or demographics.
 */
type Draft = Omit<CertificateState, "owner" | "busy" | "error" | "cleared">;
const drafts = new WeakMap<JsonRequester, Map<string, Draft>>();

function draftKey(owner: CertificateState["owner"]): string {
  return `${owner.vaSid}:${owner.mode}:${owner.step}:${owner.projectMode}:${owner.fingerprint ?? ""}:${owner.recoveryGeneration}`;
}

function draftsFor(request: JsonRequester): Map<string, Draft> {
  let map = drafts.get(request);
  if (!map) drafts.set(request, map = new Map());
  return map;
}

function forgetDraft(owner: CertificateState["owner"]): void {
  drafts.get(owner.request)?.delete(draftKey(owner));
}

/** The remark this coder or reviewer last saved with their final COD. */
function savedRemark(workspace: WorkspacePayload, mode: WorkspaceIdentity["mode"]): string {
  return (mode === "reviewing" ? workspace.assessments.reviewer_final : workspace.assessments.final)?.remark ?? "";
}

/** The saved draft for this owner, else the server seed. */
function initialState(owner: CertificateState["owner"], workspace: WorkspacePayload): CertificateState {
  const draft = drafts.get(owner.request)?.get(draftKey(owner));
  if (draft) return { ...draft, owner, busy: false, error: "", cleared: false, notice: draft.notice || "Unsaved draft restored." };
  const maskedStepTwo = workspace.case.project_mode === "masked_doris" && workspace.step === "final";
  const seeded = maskedStepTwo ? { certificate: {}, derivedAge: null } : initialCertificate(workspace);
  const recovered = readCodDraft(draftContext(workspace, { vaSid: owner.vaSid, mode: owner.mode }), workspace.step);
  const certificate = recovered ? { ...seeded.certificate, ...recovered.certificate } : seeded.certificate;
  return {
    owner,
    certificate,
    adminSeen: hasAdministrativeData(certificate),
    derivedAge: seeded.derivedAge,
    remark: recovered?.remark ?? savedRemark(workspace, owner.mode),
    revision: 0,
    processing: null,
    selectedCause: recovered?.selectedCause ?? null,
    error: "",
    notice: recovered ? "Unsaved COD restored. Process the certificate again before saving." : "",
    busy: false,
    reconfirm: false,
    cleared: false,
  };
}

function sameOwner(left: CertificateState["owner"] | undefined, right: CertificateState["owner"]): boolean {
  return left?.api === right.api && left.request === right.request && left.vaSid === right.vaSid && left.mode === right.mode && left.step === right.step && left.projectMode === right.projectMode && left.fingerprint === right.fingerprint && left.recoveryGeneration === right.recoveryGeneration;
}

function codeFromResult(result: JsonObject | null): string {
  if (!result) return "";
  return typeof result.stemCode === "string" ? result.stemCode : typeof result.code === "string" ? result.code : "";
}

function processingResult(processing: DorisProcessReply | null, engine: "doris" | "codedit"): JsonObject {
  return object(processing?.[engine].result);
}

/** Removes hidden sections/fields (rules.ts) (including the pregnancy follow-ups unless pregnancy is Yes). */
function processCertificate(certificate: JsonObject): JsonObject {
  const result = applyVisibility(certificate);
  result.Part1 = array(result.Part1).filter((raw) => lineConditions(raw).length > 0);
  if (lineConditions(result.Part2).length === 0) delete result.Part2;
  return result;
}

function makeSaveError(error: unknown): string {
  if (!(error instanceof ApiError) || !error.payload) return errorText(error);
  const body = error.payload;
  const messages = Array.isArray(body.messages) ? body.messages.filter((item) => typeof item === "string") : [];
  const blocked = Array.isArray(body.blocked_by) ? body.blocked_by.filter((item) => typeof item === "string") : [];
  const joined = [...messages, ...blocked].join(" ");
  if (joined) return joined;
  const generic = errorText(error);
  // DORIS process errors are {error: {message, fields: [{path, message}]}}: show them like the public demo, keep the Ref line.
  // Only a 422 carries fields worth showing; other statuses (CSRF, session, rate limit) keep errorText's localised line.
  const nested = object(body.error);
  if (error.status !== 422 || typeof nested.message !== "string" || !nested.message) return generic;
  const fields = array(nested.fields).map((item) => object(item)).map((field) => `${text(field.path)} — ${text(field.message)}`);
  const ref = generic.split("\n").slice(1).join("\n");
  return [`${nested.message}${fields.length ? ` Check: ${fields.join("; ")}` : ""}`, ref].filter(Boolean).join("\n");
}

/** Allocation-scoped editor; only whitelisted COD fields survive a web reload. Processing proof stays in memory. */
export function DorisPanel({
  workspace,
  identity,
  api,
  request,
  onSaved,
  onDone,
}: {
  workspace: WorkspacePayload;
  identity: WorkspaceIdentity;
  api: WorkspaceApi;
  request: JsonRequester;
  onSaved: () => Promise<void>;
  onDone: () => void;
}) {
  const owner = { api, request, vaSid: identity.vaSid, mode: identity.mode, step: workspace.step, projectMode: workspace.case.project_mode, fingerprint: workspace.case.doris_draft_context, recoveryGeneration: browserDraftGeneration() };
  const [stored, setStored] = useState<CertificateState>(() => initialState(owner, workspace));
  const [notCodeableReason, setNotCodeableReason] = useState("");
  const [notCodeableOther, setNotCodeableOther] = useState("");
  const [pickerTarget, setPickerTarget] = useState<PickerTarget | null>(null);
  const { mode: colorMode, colors } = useTheme();
  const state = sameOwner(stored.owner, owner) ? stored : initialState(owner, workspace);
  const stateRef = useRef(state);
  stateRef.current = state;
  const ownerRef = useRef(owner);
  ownerRef.current = owner;
  const workspaceRef = useRef(workspace);
  const generation = useRef(0);
  const live = useRef(true);
  const identityKey = `${identity.vaSid}:${identity.mode}:${workspace.step}:${workspace.case.project_mode}:${workspace.case.doris_draft_context ?? ""}:${owner.recoveryGeneration}`;
  const masked = workspace.case.project_mode === "masked_doris";
  const isInitial = workspace.step === "initial";
  const canEdit = identity.mode !== "view" && (workspace.step === "initial" || (workspace.step === "final" && !masked));
  const certificate = state.certificate;
  const revision = state.revision;
  const [detailCode, setDetailCode] = useState<string | null>(null);
  // The Estimated age has a half-typed value (number without unit or unit without number): no date refill (rules.ts).
  const [ageTyped, setAgeTyped] = useState(false);
  // Interval fields hold a pair they could not serialize (field label -> message); Process refuses until each is fixed.
  const intervalErrors = useRef<Record<string, string>>({});
  const reportIntervalError = useCallback((key: string, error: string) => {
    if (error) intervalErrors.current[key] = error;
    else delete intervalErrors.current[key];
  }, []);
  const detailSheet = detailCode ? <CodeDetailsSheet api={api} identity={identity} code={detailCode} onClose={() => setDetailCode(null)} /> : null;
  // The DORIS suggestion's title for the Step 1 quick-add (its certificate line, else WHO's codeinfo title).
  const dorisStem = stemAndKnownTitle(state.processing, state.processing?.certificate ?? {});
  const dorisTitle = useCodeTitle(api, identity.vaSid, dorisStem.stem, dorisStem.known);

  const layout = useLayout();
  // The outer card blends with the case workspace card (app palette); inner primitives keep the zinc tokens.
  const pageCard = { backgroundColor: colors.surface, borderColor: colors.border };
  const update = useCallback((change: (current: CertificateState) => CertificateState) => {
    setStored((current) => {
      if (!live.current || !sameOwner(ownerRef.current, owner)) return current;
      const base = sameOwner(current.owner, owner) ? current : initialState(owner, workspace);
      return change(base);
    });
  }, [api, identity.mode, identity.vaSid, request, workspace]);

  // derivedAge is only passed by the callers that change EstimatedAge or the dates; undefined leaves it as it is.
  const invalidate = useCallback((nextCertificate: JsonObject, message = "Certificate changed. Process it again before saving.", derivedAge?: string | null) => {
    update((current) => ({ ...current, certificate: applyVisibility(nextCertificate), adminSeen: current.adminSeen || hasAdministrativeData(nextCertificate), ...(derivedAge === undefined ? {} : { derivedAge }), revision: current.revision + 1, processing: null, selectedCause: null, reconfirm: false, busy: false, notice: message, error: "" }));
  }, [update, workspace.case.age]);

  const setField = (section: string, key: string, value: JsonValue | undefined) => {
    const next = copy(certificate);
    if (!isRecord(next[section])) next[section] = {};
    const target = next[section] as JsonObject;
    if (value === undefined || value === "") delete target[key];
    else target[key] = value;
    if (!Object.keys(target).length) delete next[section];
    if (section === "AdministrativeData" && (key === "DateBirth" || key === "DateDeath")) {
      // A date change refills an empty or derived age; the value a user typed or cleared is left alone.
      const dated = deriveEstimatedAge(next, state.derivedAge, ageTyped);
      invalidate(dated.certificate, undefined, dated.derived);
      return;
    }
    // Typing or clearing EstimatedAge makes it the user's value: no refill until a date changes.
    invalidate(next, undefined, section === "AdministrativeData" && key === "EstimatedAge" ? null : undefined);
  };

  const updatePart1 = (nextLines: JsonObject[]) => {
    const next = copy(certificate);
    next.Part1 = nextLines;
    invalidate(next);
  };

  useEffect(() => {
    // A busy state only flags an in-flight request; persisting it could re-save a draft a successful save just forgot.
    if (stored.cleared || stored.busy || !sameOwner(stored.owner, ownerRef.current)) return;
    // Back to the server seed (a masked Step 2 choice cleared): nothing unsaved to keep.
    if (stored.revision === 0 && !stored.selectedCause && stored.remark === savedRemark(workspaceRef.current, stored.owner.mode)) {
      forgetDraft(stored.owner);
      return;
    }
    saveCodDraft(draftContext(workspaceRef.current, { vaSid: stored.owner.vaSid, mode: stored.owner.mode }), {
      step: stored.owner.step, certificate: stored.certificate, selectedCause: stored.selectedCause, remark: stored.remark,
    });
    const { certificate: draftCertificate, revision: draftRevision, processing, selectedCause, notice, reconfirm, adminSeen, derivedAge, remark } = stored;
    draftsFor(stored.owner.request).set(draftKey(stored.owner), { certificate: draftCertificate, revision: draftRevision, processing, selectedCause, notice, reconfirm, adminSeen, derivedAge, remark });
  }, [stored]);

  useEffect(() => {
    generation.current += 1;
    live.current = true;
    setStored(initialState(owner, workspace));
    return () => {
      live.current = false;
      generation.current += 1;
    };
  }, [api, identityKey, request]);

  useEffect(() => {
    if (workspaceRef.current === workspace) return;
    workspaceRef.current = workspace;
    if (stateRef.current.cleared) {
      live.current = true;
      setStored(initialState(owner, workspace));
    }
  }, [owner, workspace]);

  useEffect(() => {
    const clear = () => {
      generation.current += 1;
      live.current = false;
      const blank = initialState(owner, workspace);
      blank.certificate = {};
      blank.cleared = true;
      // The picker holds the typed query, which can describe the deceased: it must not come back on return.
      setPickerTarget(null);
      setStored(blank);
    };
    const native = NativeAppState.addEventListener("change", (next) => {
      if (next !== "active") clear();
      else void onSaved().catch(() => undefined);
    });
    const onVisibility = () => {
      if (typeof document !== "undefined" && document.visibilityState !== "visible") clear();
      else void onSaved().catch(() => undefined);
    };
    if (typeof document !== "undefined") document.addEventListener("visibilitychange", onVisibility);
    return () => {
      native.remove();
      if (typeof document !== "undefined") document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [api, identityKey, onSaved, request, workspace]);

  const currentRequest = (requestId: number, sentRevision: number) => live.current && sameOwner(ownerRef.current, owner) && generation.current === requestId && stateRef.current.revision === sentRevision && owner.recoveryGeneration === browserDraftGeneration();

  const clearAllocation = () => {
    if (!live.current || !sameOwner(ownerRef.current, owner) || owner.recoveryGeneration !== browserDraftGeneration()) return;
    forgetDraft(owner);
    clearCaseBrowserDraft(draftContext(workspace, identity));
    generation.current += 1;
    live.current = false;
    setStored((current) => sameOwner(current.owner, owner) ? { ...current, certificate: {}, processing: null, selectedCause: null, busy: false, cleared: true } : current);
    onDone();
  };

  const process = async () => {
    const requestId = ++generation.current;
    const sentRevision = revision;
    const intervalProblems = Object.values(intervalErrors.current);
    if (intervalProblems.length) {
      update((current) => ({ ...current, error: intervalProblems.join(" ") }));
      return;
    }
    const currentCertificate = processCertificate(certificate);
    const sourceLines = array(certificate.Part1).map(lineConditions);
    const lastFilledLine = sourceLines.reduce((last, conditions, index) => conditions.length ? index : last, -1);
    if (sourceLines.slice(0, lastFilledLine + 1).some((conditions) => conditions.length === 0)) {
      update((current) => ({ ...current, error: "Complete each Part I line before the next line, or remove the empty line." }));
      return;
    }
    if (sourceLines.some((conditions) => conditions.some((condition) => conditions.some((other) => other.Interval !== condition.Interval)))) {
      update((current) => ({ ...current, error: "Conditions on the same Part I line must share one interval." }));
      return;
    }
    if (!Array.isArray(currentCertificate.Part1) || currentCertificate.Part1.length === 0) {
      update((current) => ({ ...current, error: "Enter at least one Part I condition." }));
      return;
    }
    if (!text(sourceLines[0]?.[0]?.Text).trim()) {
      update((current) => ({ ...current, error: "Enter the immediate cause text in the first Part I line." }));
      return;
    }
    update((current) => ({ ...current, busy: true, error: "", notice: "Processing with DORIS and CoDEdit…" }));
    try {
      const processing = await api.processDoris(identity.vaSid, identity.mode === "reviewing" ? "reviewer" : "coder", sentRevision, currentCertificate);
      if (!currentRequest(requestId, sentRevision)) return;
      update((current) => ({ ...current, processing, selectedCause: null, busy: false, notice: "Review both results, then independently confirm the final underlying cause." }));
    } catch (processError) {
      if (!currentRequest(requestId, sentRevision)) return;
      if (processError instanceof ApiError && processError.status === 403) {
        clearAllocation();
      } else update((current) => ({ ...current, busy: false, error: makeSaveError(processError) }));
    }
  };

  const save = async () => {
    const requestId = ++generation.current;
    const sentRevision = revision;
    const processing = state.processing;
    if (!processing || processing.client_revision !== sentRevision || !state.selectedCause) {
      update((current) => ({ ...current, error: "Process the current certificate and confirm the final underlying cause before saving." }));
      return;
    }
    const dorisFields: JsonObject = {
      doris_certificate: processing.certificate,
      doris_result: { status: processing.doris.status, result: processing.doris.result },
      codedit_result: { status: processing.codedit.status, result: processing.codedit.result },
      doris_process_token: processing.process_token,
      doris_result_digest: processing.result_digest,
      doris_client_revision: processing.client_revision,
    };
    update((current) => ({ ...current, busy: true, error: "" }));
    try {
      if (isInitial) {
        await api.saveInitial(identity.vaSid, {
          antecedent_cod: state.selectedCause.code,
          ...dorisFields,
        }, identity.mode === "reviewing" ? "reviewing" : "coding");
        if (!currentRequest(requestId, sentRevision)) return;
        forgetDraft(owner);
        clearCodDraft(draftContext(workspace, identity));
        await onSaved();
      } else {
        const body: JsonObject = { conclusive_cod: state.selectedCause.code, remark: state.remark };
        Object.assign(body, dorisFields);
        await api.saveFinal(identity.vaSid, body, identity.mode === "reviewing" ? "reviewing" : "coding");
        if (!currentRequest(requestId, sentRevision)) return;
        forgetDraft(owner);
        clearCaseBrowserDraft(draftContext(workspace, identity));
        onDone();
      }
    } catch (saveError) {
      if (!currentRequest(requestId, sentRevision)) return;
      if (saveError instanceof ApiError && saveError.status === 403) {
        clearAllocation();
        return;
      }
      if (saveError instanceof ApiError && saveError.status === 409 && saveError.code === "DORIS_CERTIFICATE_CHANGED" && saveError.payload?.processing) {
        try {
          const fresh = parseDorisProcess(saveError.payload.processing);
          update((current) => ({ ...current, certificate: fresh.certificate, revision: fresh.client_revision, processing: fresh, selectedCause: null, reconfirm: true, busy: false, notice: "", error: "The certificate changed on the server. Review the fresh results and confirm the final cause again." }));
          return;
        } catch { /* malformed conflict result is shown below */ }
      }
      const message = makeSaveError(saveError);
      if (saveError instanceof ApiError && (saveError.status === 422 || saveError.code === "final_blocked")) {
        try { await onSaved(); } catch { /* preserve the original validation response */ }
      }
      if (!currentRequest(requestId, sentRevision)) return;
      update((current) => ({ ...current, busy: false, error: message }));
    }
  };

  const reportNotCodeable = async () => {
    if (!notCodeableReason || (notCodeableReason === "others" && !notCodeableOther.trim())) return;
    const requestId = ++generation.current;
    const sentRevision = revision;
    update((current) => ({ ...current, busy: true, error: "" }));
    try {
      await api.saveNotCodeable(identity.vaSid, { reason: notCodeableReason, other: notCodeableReason === "others" ? notCodeableOther.trim() : "" });
      if (!currentRequest(requestId, sentRevision)) return;
      forgetDraft(owner);
      clearCaseBrowserDraft(draftContext(workspace, identity));
      onDone();
    } catch (reportError) {
      if (!currentRequest(requestId, sentRevision)) return;
      if (reportError instanceof ApiError && reportError.status === 403) {
        clearAllocation();
      } else update((current) => ({ ...current, busy: false, error: makeSaveError(reportError) }));
    }
  };

  const setRemark = (value: string) => {
    generation.current += 1;
    update((current) => ({ ...current, remark: value, busy: false }));
  };

  const chooseFinalCause = (choice: { code: string; title: string; uri: string } | null) => {
    generation.current += 1;
    update((current) => ({ ...current, selectedCause: choice, busy: false, error: "", notice: choice ? "Final underlying cause selected independently from the DORIS result." : "" }));
  };

  // Clearing also outdates a quick-add still waiting on WHO, so it cannot re-select what was just cleared.
  const resetCertificate = () => {
    generation.current += 1;
    intervalErrors.current = {};
    setPickerTarget(null);
    const currentWorkspace = workspaceRef.current;
    const resetDoris = currentWorkspace.doris;
    const resetSeed = copy(resetDoris?.reset_certificate ?? resetDoris?.initial_certificate ?? {});
    resetSeed.Part1 = [];
    delete resetSeed.Part2;
    const seed = initialCertificate({ ...currentWorkspace, doris: resetDoris ? { ...resetDoris, initial_certificate: resetSeed, prefill_provenance: resetDoris.reset_prefill_provenance ?? resetDoris.prefill_provenance, saved_processing: null } : null });
    update((current) => {
      const next = { ...current, certificate: seed.certificate, derivedAge: seed.derivedAge, revision: current.revision + 1, processing: null, selectedCause: null, reconfirm: false, busy: false, error: "", notice: "DORIS reset to the interview data. Remarks, notes and SmartVA results are retained." };
      saveCodDraft(draftContext(workspaceRef.current, identity), { step: workspaceRef.current.step, certificate: next.certificate, selectedCause: null, remark: next.remark });
      return next;
    });
  };

  const clearFinalCause = () => {
    generation.current += 1;
    chooseFinalCause(null);
  };

  // Quick-add: the first code WHO resolves is confirmed like a searched one (codeinfo, then the selection check).
  const chooseCode = async (codes: string[]) => {
    const requestId = ++generation.current;
    const sentRevision = revision;
    update((current) => ({ ...current, error: "" }));
    for (const code of codes) {
      try {
        const info = await api.getDorisCodeInfo(identity.vaSid, code);
        if (!currentRequest(requestId, sentRevision)) return;
        const check = await api.checkDorisSelection(identity.vaSid, info.item.code, info.item.uri);
        if (!currentRequest(requestId, sentRevision)) return;
        chooseFinalCause({ code: check.item.code, title: check.item.title, uri: check.item.uri });
        return;
      } catch (codeError) {
        if (!currentRequest(requestId, sentRevision)) return;
        if (codeError instanceof ApiError && codeError.status === 403) {
          clearAllocation();
          return;
        }
        // Not resolvable: try the next code.
      }
    }
    if (currentRequest(requestId, sentRevision)) update((current) => ({ ...current, error: "WHO ICD-11 did not confirm that code. Search for the cause instead." }));
  };

  const loseAllocation = () => { setPickerTarget(null); clearAllocation(); };

  const pickerInit = (target: PickerTarget, finalQuery: string): PickerInit => {
    if (target.kind === "final") return { title: isInitial ? "Confirm Step 1 underlying cause" : "Final underlying cause", accent: ui.light.primary, allowUncoded: false, query: target.query || finalQuery, finalMode: true, theme: colorMode };
    const index = target.kind === "part1" ? target.index : 0;
    return { title: lineTitle(index, target.kind === "part2"), accent: lineShade(colorMode, index, target.kind === "part2").bar, allowUncoded: true, query: target.query, theme: colorMode };
  };

  const applyPicked = (target: PickerTarget, condition: JsonObject) => {
    const lines = array(certificate.Part1).filter(isRecord) as JsonObject[];
    if (target.kind === "part1") updatePart1(lines.map((item, index) => index === target.index ? appendCondition(item, condition) : item));
    else if (target.kind === "part2") invalidate({ ...copy(certificate), Part2: appendCondition(object(certificate.Part2), condition) });
  };

  const picker = (finalQuery: string) => pickerTarget ? (
    <IcdPickerModal
      init={pickerInit(pickerTarget, finalQuery)}
      api={api}
      request={request}
      identity={identity}
      revision={revision}
      requestGeneration={generation.current}
      onForbidden={loseAllocation}
      onClose={() => setPickerTarget(null)}
      onUncoded={(value) => { applyPicked(pickerTarget, { Text: value }); setPickerTarget(null); }}
      onSelect={(choice: PickerChoice) => {
        if (pickerTarget.kind === "final") chooseFinalCause(choice);
        else applyPicked(pickerTarget, { Text: choice.title, Code: choice.code, LinearizationURI: choice.uri });
        setPickerTarget(null);
      }}
    />
  ) : null;

  if (identity.mode === "view" || workspace.doris === null || (workspace.step !== "initial" && workspace.step !== "final") || state.cleared) return null;

  if (masked && workspace.step === "final") {
    const step1 = workspace.doris.step1_processing;
    const ownFinal = identity.mode === "reviewing" ? workspace.assessments.reviewer_final : workspace.assessments.final;
    const ownInitial = (identity.mode === "reviewing" ? workspace.assessments.reviewer_initial : workspace.assessments.initial) ?? null;
    const selected = state.selectedCause;
    return (
      <Card style={[layout.panel, pageCard]}>
        <EditorHeading title="Final underlying cause" />
        <Step1AssignedCard initial={ownInitial} />
        <Step1DorisCard saved={step1 ?? null} certificate={workspace.doris.step1_certificate ?? null} api={api} vaSid={identity.vaSid} onDetails={setDetailCode} />
        <CertificateReference certificate={workspace.doris.step1_certificate ?? null} />
        {workspace.smartva !== null ? <SmartVaReference value={workspace.smartva} /> : null}
        {ownFinal?.conclusive_cod ? <Muted>Previously saved final: {ownFinal.conclusive_cod}</Muted> : null}
        <FinalCausePicker api={api} label="Choose and confirm the final underlying cause" value={selected} searching={pickerTarget !== null} onOpen={(query) => setPickerTarget({ kind: "final", query })}
          quick={step2QuickChoices(ownInitial, workspace.smartva)} onQuick={(codes) => void chooseCode(codes)} onDetails={setDetailCode} onClear={clearFinalCause} />
        <Textarea accessibilityLabel="COD remark" placeholder="Remark" value={state.remark} onChangeText={setRemark} />
        {state.error ? <Alert variant="destructive">{state.error}</Alert> : null}
        <Button label="Save final cause" disabled={!selected || state.busy} loading={state.busy} onPress={() => void saveMaskedFinal()} />
        <Separator testID="doris-actions-separator" />
        {identity.mode === "coding" ? <NotCodeableAction reason={notCodeableReason} other={notCodeableOther} busy={state.busy} onReason={setNotCodeableReason} onOther={setNotCodeableOther} onSubmit={() => void reportNotCodeable()} /> : null}
        {picker(ownFinal?.conclusive_cod ?? "")}
        {detailSheet}
        <FieldHint testID="icd11-citation">{tr("icd11Citation")}</FieldHint>
      </Card>
    );
  }

  const part1 = array(certificate.Part1).filter(isRecord) as CertificateLine[];
  const age = reportedAge(certificate);
  const shown = visibility(certificate, age);
  const warns = warnings(certificate, todayIso());
  const provenance = object(workspace.doris.prefill_provenance);
  const processing = state.processing;
  const ownFinal = identity.mode === "reviewing" ? workspace.assessments.reviewer_final : workspace.assessments.final;

  async function saveMaskedFinal() {
    const requestId = ++generation.current;
    const sentRevision = revision;
    if (!state.selectedCause) return;
    update((current) => ({ ...current, busy: true, error: "" }));
    try {
      await api.saveFinal(identity.vaSid, { conclusive_cod: state.selectedCause.code, remark: state.remark }, identity.mode === "reviewing" ? "reviewing" : "coding");
      if (!currentRequest(requestId, sentRevision)) return;
      forgetDraft(owner);
      clearCaseBrowserDraft(draftContext(workspace, identity));
      onDone();
    } catch (saveError) {
      if (!currentRequest(requestId, sentRevision)) return;
      if (saveError instanceof ApiError && saveError.status === 403) {
        clearAllocation();
      } else {
        const message = makeSaveError(saveError);
        if (saveError instanceof ApiError && (saveError.status === 422 || saveError.code === "final_blocked")) {
          try { await onSaved(); } catch { /* keep the save refusal visible */ }
        }
        if (currentRequest(requestId, sentRevision)) update((current) => ({ ...current, busy: false, error: message }));
      }
    }
  }

  return (
    <IntervalErrorContext.Provider value={reportIntervalError}>
    <Card style={[layout.panel, pageCard]}>
      <EditorHeading title="DORIS certificate" subtitle={isInitial ? "Step 1" : "Final cause"} />
      {state.notice ? <Muted>{state.notice}</Muted> : null}
      {workspace.doris.saved_processing ? <ProcessingSummary processing={null} saved={workspace.doris.saved_processing} api={api} vaSid={identity.vaSid} /> : null}
      {state.adminSeen || hasAdministrativeData(certificate) ? <AdministrativeFields certificate={certificate} provenance={provenance} warns={warns} onChange={setField} onAgeTyped={setAgeTyped} /> : <Muted>Administrative data was not supplied for this certificate.</Muted>}
      <SectionTitle style={{ marginTop: gap.xl }}>Frame A: Medical data</SectionTitle>
      <View style={[layout.nowrap, { marginTop: gap.md, paddingRight: gap.xs }]}>
        <SectionTitle numberOfLines={1} style={{ flex: 1, minWidth: 0 }}>Part 1: Cause of death</SectionTitle>
        {part1.length < MAX_PART1_LINES ? <Button label="Add line" variant="secondary" style={{ flexShrink: 0 }} onPress={() => updatePart1([...part1, { Conditions: [] }])} /> : null}
      </View>
      {part1.map((line, index) => (
        <CertificateLine key={`${identityKey}:${index}`} searching={pickerTarget !== null} index={index} line={line} age={age} warning={warns[`Part1.${index}`]} onSearch={(query) => setPickerTarget({ kind: "part1", index, query })} isLast={index === part1.length - 1} onAddBelow={part1.length < MAX_PART1_LINES ? () => updatePart1([...part1.slice(0, index + 1), { Conditions: [] }, ...part1.slice(index + 1)]) : undefined} onChange={(next) => updatePart1(part1.map((item, itemIndex) => itemIndex === index ? next : item))} onRemove={() => updatePart1(part1.filter((_item, itemIndex) => itemIndex !== index))} onMove={(direction) => {
          if ((direction < 0 && index === 0) || (direction > 0 && index === part1.length - 1)) return;
          const next = [...part1];
          [next[index + direction], next[index]] = [next[index], next[index + direction]];
          updatePart1(next);
        }} />
      ))}
      <SectionTitle style={{ marginTop: gap.xl }}>Part 2: Other significant conditions contributing to death</SectionTitle>
      <CertificateLine key={`${identityKey}:part2`} searching={pickerTarget !== null} index={0} line={object(certificate.Part2) as CertificateLine} part2 age={age} warning={warns.Part2} onSearch={(query) => setPickerTarget({ kind: "part2", query })} onChange={(next) => { const copyCert = copy(certificate); copyCert.Part2 = next; invalidate(copyCert); }} onRemove={() => { const next = copy(certificate); delete next.Part2; invalidate(next); }} />
      <CertificateDetails certificate={certificate} provenance={provenance} shown={shown} warns={warns} onChange={setField} />
      {processing ? <ProcessingSummary processing={processing} api={api} vaSid={identity.vaSid} /> : null}
      {processing || state.selectedCause ? (
        <FinalCausePicker api={api} label={isInitial ? "Confirm Step 1 underlying cause" : "Choose and confirm the final underlying cause"} value={state.selectedCause} searching={pickerTarget !== null} onOpen={(query) => setPickerTarget({ kind: "final", query })}
          quick={processing ? dorisQuickChoices(processing, dorisTitle) : []} onQuick={(codes) => void chooseCode(codes)} onDetails={setDetailCode} onClear={clearFinalCause} />
      ) : null}
      {state.reconfirm ? <Alert variant="destructive">Fresh processing replaced the previous result; confirm your final cause again.</Alert> : null}
      {isInitial ? null : <Textarea accessibilityLabel="COD remark" placeholder="Remark" value={state.remark} onChangeText={setRemark} />}
      {state.error ? <Alert variant="destructive">{state.error}</Alert> : null}
      <Button label="Reset DORIS from interview" variant="secondary" disabled={state.busy} onPress={resetCertificate} />
      <Button label="Process current certificate" disabled={!canEdit || state.busy} loading={state.busy} onPress={() => void process()} />
      <Button label={isInitial ? "Save Step 1" : "Save final COD"} disabled={!state.processing || !state.selectedCause || state.busy} loading={state.busy} onPress={() => void save()} />
      <Separator testID="doris-actions-separator" />
      {identity.mode === "coding" ? <NotCodeableAction reason={notCodeableReason} other={notCodeableOther} busy={state.busy} onReason={setNotCodeableReason} onOther={setNotCodeableOther} onSubmit={() => void reportNotCodeable()} /> : null}
      {picker(isInitial ? codeFromResult(processingResult(processing, "doris")) : ownFinal?.conclusive_cod ?? "")}
      {detailSheet}
      <FieldHint testID="icd11-citation">{tr("icd11Citation")}</FieldHint>
    </Card>
    </IntervalErrorContext.Provider>
  );
}

/** Section heading of the editor: top rule across the card, one h2 title, muted step line under it. */
function EditorHeading({ title, subtitle }: { title: string; subtitle?: string }) {
  const { t, phone } = useUi();
  const pad = phone ? gap.sm : gap.lg;
  return (
    <View style={{ gap: gap.xs }}>
      <Separator testID="doris-heading-separator" style={{ marginHorizontal: -pad, marginBottom: gap.md }} />
      <Text accessibilityRole="header" aria-level={2} style={{ fontSize: phone ? 24 : 26, lineHeight: phone ? 30 : 32, fontWeight: "700", textAlign: "center", color: t.foreground }}>{title}</Text>
      {subtitle ? <Text style={{ fontSize: 14, lineHeight: 20, textAlign: "center", color: t.mutedForeground }}>{subtitle}</Text> : null}
    </View>
  );
}

/** Shows the five server-supported not-codeable reasons to coders only. */
function NotCodeableAction({ reason, other, busy, onReason, onOther, onSubmit }: {
  reason: string;
  other: string;
  busy: boolean;
  onReason: (value: string) => void;
  onOther: (value: string) => void;
  onSubmit: () => void;
}) {
  const reasons = [
    ["narration_language", "Narration language"],
    ["narration_doesnt_match", "Narration does not match"],
    ["no_info", "No information"],
    ["form_is_empty", "Form is empty"],
    ["others", "Other"],
  ] as const;
  return (
    <View style={{ gap: gap.sm }}>
      <Muted>Report not codeable</Muted>
      <ChipChoice name="doris_not_codeable" label="Not-codeable reason" disabled={busy} options={reasons.map(([value, label]) => ({ value, label }))} value={reason} onChange={onReason} />
      {reason === "others" ? <Input accessibilityLabel="Other not-codeable reason" placeholder="Reason" value={other} onChangeText={onOther} /> : null}
      <Button label="Submit not-codeable report" variant="secondary" disabled={busy || !reason || (reason === "others" && !other.trim())} loading={busy} onPress={onSubmit} />
    </View>
  );
}

/** A quick-add choice above the search. `codes` are tried in order; `search` opens the picker with that query. */
type QuickChoice = { key: string; label: string; codes: string[]; title?: boolean } | { key: string; label: string; search: string };

/** The Step 1 DORIS suggestion's codes in the order a quick-add tries them: the full code, then its stem. */
function suggestedDorisCodes(run: unknown): string[] {
  const doris = object(object(run).doris);
  const dr = object(doris.result);
  if (doris.status !== "completed" || dr.reject === true) return [];
  return [...new Set([dr.code, dr.stemCode].filter((code): code is string => typeof code === "string" && code !== ""))];
}

/**
 * The DORIS stem (what the computed UCOD hangs off) and the title already known for it: the stored UCOD part's title,
 * else the coder's typed line. The stem is the lookup code: the full computed UCOD ("5A14/BA41.Z") is not a WHO code.
 */
function stemAndKnownTitle(run: unknown, certificate: JsonObject): { stem: string; known: string } {
  const codes = suggestedDorisCodes(run);
  const dr = object(object(object(run).doris).result);
  const stem = typeof dr.stemCode === "string" && dr.stemCode ? dr.stemCode : codes[0] ?? "";
  const stemPart = parseUcodParts(object(run).ucod_parts).find((part) => part.role === "stem");
  return { stem, known: stemPart?.title || certificateTitle(certificate, codes) };
}

/** Step 1 quick-add: DORIS's processed UCOD (code and title), as the web offers it above the search. */
function dorisQuickChoices(processing: DorisProcessReply | null, title: string): QuickChoice[] {
  const codes = suggestedDorisCodes(processing);
  return codes.length ? [{ key: "doris", label: `Use DORIS result: ${codes[0]}${title ? ` — ${title}` : ""}`, codes, title: true }] : [];
}

/**
 * Step 2 quick-adds: the Step 1 underlying cause, then SmartVA's primary ICD-11 target (one click, or a search for
 * several). Labels carry the WHO titles the server served with the workspace (antecedent_cod_label, cause icd11_label).
 */
function step2QuickChoices(initial: WorkspaceAssessment | null, smartva: JsonValue | null): QuickChoice[] {
  const choices: QuickChoice[] = [];
  const step1 = initial?.antecedent_cod;
  // The web stores Step 1 as "CODE title"; WHO is asked about the code alone.
  const step1Code = step1 ? step1.trim().split(/\s+/)[0] : "";
  if (step1Code) choices.push({ key: "step1", label: `Use Step 1 underlying cause: ${initial?.antecedent_cod_label || step1}`, codes: [step1Code] });
  const causes = Array.isArray(object(smartva).causes) ? (object(smartva).causes as JsonValue[]) : [];
  const primary = object(causes[0]);
  const alternatives = icd11Alternatives(primary.icd11);
  const label = typeof primary.icd11_label === "string" && primary.icd11_label ? primary.icd11_label : alternatives.join(" / ");
  const cause = [primary.cause, primary.likelihood].filter((part): part is string => typeof part === "string" && part !== "" && part !== "NaN");
  const suffix = cause.length ? ` (${cause.join(", ")})` : "";
  if (alternatives.length === 1) choices.push({ key: "smartva", label: `Use SmartVA result: ${label}${suffix}`, codes: alternatives });
  if (alternatives.length > 1) choices.push({ key: "smartva", label: `Search SmartVA result: ${label}${suffix}`, search: alternatives[0] });
  return choices;
}

/** The ICD-11 title of a code: the one already known, else WHO's codeinfo title ("" while it loads or on failure). */
function useCodeTitle(api: WorkspaceApi, vaSid: string, code: string, known: string): string {
  const [fetched, setFetched] = useState("");
  useEffect(() => {
    setFetched("");
    if (!code || known) return undefined;
    let live = true;
    api.getDorisCodeInfo(vaSid, code).then((reply) => { if (live) setFetched(reply.item.title); }).catch(() => undefined);
    return () => { live = false; };
  }, [api, code, known, vaSid]);
  return known || fetched;
}

/** A small ⓘ button that opens the ICD-11 details of a code. */
function InfoButton({ code, onPress }: { code: string; onPress: (code: string) => void }) {
  return <Button size="icon" variant="outline" accessibilityLabel={`Details for ${code}`} onPress={() => onPress(code)}><ButtonGlyph>ⓘ</ButtonGlyph></Button>;
}

/** Step 1 assigned causes as the web Step 2 shows them (immediate, Step 1 underlying, other conditions). */
function Step1AssignedCard({ initial }: { initial: WorkspaceAssessment | null }) {
  const other = Array.isArray(initial?.other_conditions) ? initial.other_conditions.join(", ") : initial?.other_conditions ?? "";
  return (
    <Card>
      <CardTitle>Your Step 1 assigned causes</CardTitle>
      <Body>Immediate cause: {initial?.immediate_cod || "-"}</Body>
      <Body>Step 1 underlying cause: {initial?.antecedent_cod || "-"}</Body>
      <Body>Other conditions: {other || "-"}</Body>
    </Card>
  );
}

/** The saved Step 1 DORIS suggestion for information on masked Step 2, with its VA mapping and checks. */
function Step1DorisCard({ saved, certificate, api, vaSid, onDetails }: { saved: JsonObject | null; certificate: JsonObject | null; api: WorkspaceApi; vaSid: string; onDetails: (code: string) => void }) {
  const codes = suggestedDorisCodes(saved);
  const { stem, known } = stemAndKnownTitle(saved, certificate ?? {});
  const title = useCodeTitle(api, vaSid, stem, known);
  return (
    <Card>
      <CardTitle>DORIS result from Step 1 (for information)</CardTitle>
      {!saved ? <Muted>No DORIS result was saved with Step 1.</Muted> : (
        <>
          {codes.length ? (
            <View style={{ gap: gap.xs }}>
              <View style={{ flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: gap.sm }}>
                <Body style={{ flexShrink: 1 }}>DORIS suggests: {codes[0]}{title ? ` — ${title}` : ""}</Body>
                <InfoButton code={codes[0]} onPress={onDetails} />
              </View>
              <AssociatedVaCodes api={api} code={codes[0]} />
            </View>
          ) : <Alert variant="destructive">DORIS could not select an underlying cause from this certificate.</Alert>}
          <DorisChecks doris={object(saved.doris)} codedit={object(saved.codedit)} api={api} vaSid={vaSid} />
        </>
      )}
    </Card>
  );
}

/**
 * ICD-11 titles for the codes the known DORIS warnings name, looked up once per code through codeinfo (the local WHO
 * API). A code whose lookup fails keeps no title and the warning shows the code alone.
 */
function useWarningTitles(api: WorkspaceApi, vaSid: string, warning: string): Record<string, string> {
  const codes = dorisWarningCodes(warning).slice(0, 5);
  const key = codes.join(" ");
  const [titles, setTitles] = useState<Record<string, string>>({});
  useEffect(() => {
    let live = true;
    setTitles({});
    key.split(" ").filter(Boolean).forEach((code) => {
      api.getDorisCodeInfo(vaSid, code)
        .then((reply) => { if (live && reply.item.title) setTitles((current) => ({ ...current, [code]: reply.item.title })); })
        .catch(() => undefined);
    });
    return () => { live = false; };
  }, [api, key, vaSid]);
  return titles;
}

/** "Check before you decide" items, or "No problems found" when DORIS ran and nothing was flagged. */
function DorisChecks({ doris, codedit, api, vaSid }: { doris: unknown; codedit: unknown; api: WorkspaceApi; vaSid: string }) {
  const warning = object(object(doris).result).warning;
  const titles = useWarningTitles(api, vaSid, typeof warning === "string" ? warning : "");
  const checks = summaryChecks(object(doris), object(codedit), (code) => titles[code]);
  if (checks.length) {
    return (
      <View style={{ gap: gap.xs }}>
        <Body style={{ fontWeight: "600" }}>Check before you decide</Body>
        {checks.map((check, index) => (
          <View key={`check-${index}`} style={{ gap: 2 }}>
            <Muted>• {check.text}</Muted>
            {check.original ? <Muted style={{ fontSize: 12 }}>DORIS: {check.original}</Muted> : null}
          </View>
        ))}
      </View>
    );
  }
  return object(doris).status === "completed" ? <Muted>No problems found in the certificate.</Muted> : null;
}

/** Selected final cause with its ⓘ and ✕, VA note, quick-add choices, then the shared ICD-11 picker. */
function FinalCausePicker({ api, label, value, onOpen, searching, quick, onQuick, onDetails, onClear }: {
  api: WorkspaceApi;
  label: string;
  value: PickerChoice | null;
  onOpen: (query: string) => void;
  searching: boolean;
  quick: QuickChoice[];
  onQuick: (codes: string[]) => void;
  onDetails: (code: string) => void;
  onClear: () => void;
}) {
  const layout = useLayout();
  const { phone } = useUi();
  return (
    <Card>
      <CardTitle>{label}</CardTitle>
      {value ? (
        <View testID="selected-cause-layout" style={phone ? { gap: gap.sm } : { flexDirection: "row", alignItems: "flex-start", gap: gap.md }}>
          <View style={phone ? undefined : { flex: 1, minWidth: 0 }}>
            <View style={[layout.row, { flexWrap: "nowrap" }]}>
              <Body style={{ flexShrink: 1 }}>{value.code} — {value.title}</Body>
              <InfoButton code={value.code} onPress={onDetails} />
              <Button size="icon" variant="outline" accessibilityLabel={`Clear chosen cause ${value.code}`} onPress={onClear} ><ButtonGlyph destructive>✕</ButtonGlyph></Button>
            </View>
            <AssociatedVaCodes api={api} code={value.code} />
          </View>
          <AssociatedVaCodes api={api} code={value.code} showDefinition attribution style={phone ? undefined : { flex: 1, minWidth: 0 }} />
        </View>
      ) : null}
      {quick.map((choice) => (
        <View key={choice.key} style={{ gap: gap.xs }}>
          {"search" in choice ? (
            <View style={layout.row}><Button variant="outline" size="sm" label={choice.label} onPress={() => onOpen(choice.search)} style={{ flexShrink: 1 }} /></View>
          ) : (
            <QuickChoiceButton choice={choice} onQuick={onQuick} api={api} onDetails={onDetails} />
          )}
        </View>
      ))}
      <Muted>Or search ICD-11 for your own code</Muted>
      <SearchBox label={`${label} search`} iconLabel={`${label} open search`} onOpen={onOpen} suspended={searching} />
    </Card>
  );
}

function QuickChoiceButton({ choice, onQuick, api, onDetails }: { choice: Extract<QuickChoice, { codes: string[] }>; onQuick: (codes: string[]) => void; api: WorkspaceApi; onDetails: (code: string) => void }) {
  const layout = useLayout();
  const code = choice.codes[0];
  return (
    <View style={{ gap: gap.xs }}>
      <View style={layout.row}>
        <Button variant="outline" size="sm" label={choice.label} onPress={() => onQuick(choice.codes)} style={{ flexShrink: 1 }} />
        <InfoButton code={code} onPress={onDetails} />
      </View>
      {code ? <AssociatedVaCodes api={api} code={code} /> : null}
    </View>
  );
}

function CertificateLine({ index, line, part2 = false, age, warning, searching, onSearch, isLast, onAddBelow, onChange, onRemove, onMove }: {
  index: number;
  line: CertificateLine;
  part2?: boolean;
  age: Age | null;
  warning?: string;
  /** A picker is open: the search box must not auto-open another. */
  searching: boolean;
  onSearch: (query: string) => void;
  isLast?: boolean;
  onAddBelow?: () => void;
  onChange: (line: CertificateLine) => void;
  onRemove: () => void;
  onMove?: (direction: -1 | 1) => void;
}) {
  const layout = useLayout();
  const { t } = useUi();
  const shade = chartFor(t, index, part2);
  const conditions = lineConditions(line);
  const interval = text(conditions[0]?.Interval);
  const prefix = part2 ? "Part II" : `Part I line ${index + 1}`;
  const setInterval = (value: string) => onChange({ ...line, Conditions: conditions.map((condition) => {
    const next = { ...condition };
    if (value) next.Interval = value; else delete next.Interval;
    return next;
  }) });
  const iconButton = (glyph: string, label: string, onPress: () => void, disabled: boolean, danger = false) => (
    <Button size="icon" variant={danger ? "outline" : "outline"} accessibilityLabel={label} disabled={disabled} onPress={onPress} style={danger ? { borderColor: t.destructiveText } : undefined}>
      <ButtonGlyph destructive={danger}>{glyph}</ButtonGlyph>
    </Button>
  );

  return (
    <Card style={{ borderLeftWidth: 4, borderLeftColor: shade.bar }}>
      <View style={[layout.nowrap, { backgroundColor: shade.tint, borderRadius: uiRadius.sm + 2, paddingHorizontal: gap.sm, paddingVertical: gap.xs }]}>
        <View style={[layout.row, { flexShrink: 1, flexWrap: "nowrap" }]}>
          {part2 ? null : <View style={{ minWidth: 22, height: 22, borderRadius: radius.full, alignItems: "center", justifyContent: "center", paddingHorizontal: 4, backgroundColor: shade.bar }}><Text accessibilityLabel={`Line ${lineLetter(index)}`} style={{ fontSize: 12, fontWeight: "700", color: t.background }}>{lineLetter(index)}</Text></View>}
          <CardTitle numberOfLines={1} style={{ color: shade.foreground }}>{lineTitle(index, part2)}</CardTitle>
        </View>
        {part2 ? (conditions.length ? iconButton("✕", "Remove Part II", onRemove, false, true) : null) : (
          <View style={layout.iconRow}>
            {onMove ? iconButton("↑", `Move Part I line ${index + 1} up`, () => onMove(-1), index === 0) : null}
            {onMove ? iconButton("↓", `Move Part I line ${index + 1} down`, () => onMove(1), Boolean(isLast)) : null}
            {iconButton("✕", `Remove Part I line ${index + 1}`, onRemove, index === 0, true)}
          </View>
        )}
      </View>
      {conditions.length ? (
        <View style={layout.row}>
          {conditions.map((condition, conditionIndex) => (
            <Chip key={`${conditionIndex}:${text(condition.Code) || "uncoded"}`} accessibilityLabel={`Remove condition ${conditionIndex + 1}`} onPress={() => onChange({ ...line, Conditions: conditions.filter((_item, current) => current !== conditionIndex) })} style={{ backgroundColor: shade.soft, borderColor: shade.bar }} textStyle={{ color: shade.foreground }}>{`${text(condition.Code) ? `${text(condition.Code)} — ` : ""}${text(condition.Text)} ×`}</Chip>
          ))}
        </View>
      ) : null}
      <View style={layout.row}>
        {conditions.length < 8 ? (
          <SearchBox label={`Search ${prefix} condition`} iconLabel={`Open search ${prefix}`} onOpen={onSearch} suspended={searching} />
        ) : null}
        {conditions.length ? (
          <View style={[layout.row, { flexShrink: 1, maxWidth: "100%" }]}>
            <IntervalField raw={interval} onChange={setInterval} inputLabel={`${prefix} interval`} unitLabel={`${prefix} interval unit`} placeholder="Interval" unitPlaceholder="Units" label="Onset to death" age={age} />
          </View>
        ) : null}
      </View>
      <Warn id={part2 ? "Part2" : `Part1.${index}`} text={warning} />
      {onAddBelow ? (
        <Button variant="outline" size="sm" label="+ Add line" accessibilityLabel={`Add line below line ${index + 1}`} onPress={onAddBelow} style={{ alignSelf: "flex-start" }} />
      ) : null}
    </Card>
  );
}

const YES_NO_UNKNOWN: ReadonlyArray<readonly [number, string]> = [[1, "Yes"], [0, "No"], [9, "Unknown"]];
// Codes are DORIS's own (the web editor and doris_certificate.py use the same lists).
const MANNER_OPTIONS: ReadonlyArray<readonly [number, string]> = [[0, "Disease"], [1, "Accident"], [2, "Intentional self-harm"], [3, "Assault"], [4, "Legal intervention"], [5, "War"], [6, "Could not be determined"], [7, "Pending investigation"], [9, "Unknown"]];
const PLACE_OPTIONS: ReadonlyArray<readonly [number, string]> = [[0, "At home"], [1, "Residential institution"], [2, "School, other institution, public administration area"], [3, "Sports and athletics area"], [4, "Street and highway"], [5, "Trade and service area"], [6, "Industrial and construction area"], [7, "Farm"], [8, "Other place"], [9, "Unknown"]];
const PREGNANCY_TIME_OPTIONS: ReadonlyArray<readonly [number, string]> = [[0, "At death"], [1, "Within 42 days"], [2, "43 days to 1 year"], [3, "1 year or more"], [9, "Unknown"]];

type OnChange = (section: string, key: string, value: JsonValue | undefined) => void;

function Tile({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card>
      <CardTitle>{title}</CardTitle>
      {children}
    </Card>
  );
}

/** Compact amber strip shown under the title of a whole card that does not apply; no fields are rendered. */
function NotApplicable({ text }: { text: string }) {
  return <Alert variant="warning" testID="not-applicable">{text}</Alert>;
}

function AdministrativeFields({ certificate, provenance, warns, onChange, onAgeTyped }: { certificate: JsonObject; provenance: JsonObject; warns: Warnings; onChange: OnChange; onAgeTyped: (typed: boolean) => void }) {
  const layout = useLayout();
  const data = object(certificate.AdministrativeData);
  // A cleared field loses its "from interview" badge until it is answered again.
  const badge = (key: string) => hasValue(data[key]) ? provenanceBadge(provenance, `AdministrativeData.${key}`) : undefined;
  const clear = (key: string) => hasValue(data[key]) ? () => onChange("AdministrativeData", key, undefined) : undefined;
  return (
    <Tile title="Administrative Data">
      {/* Top-aligned: the Sex tiles are tall and would otherwise push the other inputs down the row. */}
      <View style={[layout.grid, { alignItems: "flex-start" }]}>
        <Cell><ChoiceField label="Sex" name="doris_sex" value={data.Sex} options={[[1, "Male"], [2, "Female"], [9, "Unknown"]]} badge={badge("Sex")} onChange={(value) => onChange("AdministrativeData", "Sex", value)} /></Cell>
        <Cell>
          <FieldLabel text="Estimated age" badge={badge("EstimatedAge")} onClear={clear("EstimatedAge")} />
          <IntervalField raw={text(data.EstimatedAge)} onChange={(value) => onChange("AdministrativeData", "EstimatedAge", value)} onTyped={onAgeTyped} inputLabel="Estimated age" unitLabel="Estimated age unit" placeholder="Age" unitPlaceholder="Age unit" />
          <Warn id="AdministrativeData.EstimatedAge" text={warns["AdministrativeData.EstimatedAge"]} />
        </Cell>
        <Cell>
          <FieldLabel text="Date of birth" badge={badge("DateBirth")} onClear={clear("DateBirth")} />
          <DateField precision label="Date of birth" value={text(data.DateBirth)} onChange={(value) => onChange("AdministrativeData", "DateBirth", value)} />
          <Warn id="AdministrativeData.DateBirth" text={warns["AdministrativeData.DateBirth"]} />
        </Cell>
        <Cell>
          <FieldLabel text="Date of death" badge={badge("DateDeath")} onClear={clear("DateDeath")} />
          <DateField label="Date of death" value={text(data.DateDeath)} onChange={(value) => onChange("AdministrativeData", "DateDeath", value)} />
          <Warn id="AdministrativeData.DateDeath" text={warns["AdministrativeData.DateDeath"]} />
        </Cell>
      </View>
    </Tile>
  );
}

type FieldProps = { section: string; field: string; label: string; certificate: JsonObject; provenance: JsonObject; warns: Warnings; onChange: OnChange };

/** Digits only: these DORIS fields are whole numbers; a blank input omits the key. */
function NumberField({ section, field, label, certificate, provenance, warns, onChange }: FieldProps) {
  const stored = object(certificate[section])[field];
  const clear = hasValue(stored) ? () => onChange(section, field, undefined) : undefined;
  return (
    <Cell>
      <FieldLabel text={label} badge={hasValue(stored) ? provenanceBadge(provenance, `${section}.${field}`) : undefined} onClear={clear} />
      <Input accessibilityLabel={label} placeholder="Number" keyboardType="numeric" inputMode="numeric" value={text(stored)} onChangeText={(value) => {
        const digits = value.replace(/\D/g, "");
        onChange(section, field, digits === "" ? undefined : Number(digits));
      }} />
      <Warn id={`${section}.${field}`} text={warns[`${section}.${field}`]} />
    </Cell>
  );
}

function TextField({ section, field, label, certificate, provenance, onChange, multiline }: Omit<FieldProps, "warns"> & { multiline?: boolean }) {
  const stored = object(certificate[section])[field];
  return (
    <View style={{ gap: 4 }}>
      <FieldLabel text={label} badge={hasValue(stored) ? provenanceBadge(provenance, `${section}.${field}`) : undefined} onClear={hasValue(stored) ? () => onChange(section, field, undefined) : undefined} />
      {multiline ? <Textarea accessibilityLabel={label} numberOfLines={3} maxLength={500} value={text(stored)} onChangeText={(value) => onChange(section, field, value)} /> : <Input accessibilityLabel={label} numberOfLines={1} maxLength={500} value={text(stored)} onChangeText={(value) => onChange(section, field, value)} />}
    </View>
  );
}

/** A date answer with the precision dropdown (date of injury, date of surgery). */
function DateValue({ section, field, label, certificate, provenance, warns, onChange }: FieldProps) {
  const stored = object(certificate[section])[field];
  return (
    <View style={{ gap: 4 }}>
      <FieldLabel text={label} badge={hasValue(stored) ? provenanceBadge(provenance, `${section}.${field}`) : undefined} onClear={hasValue(stored) ? () => onChange(section, field, undefined) : undefined} />
      <DateField precision label={label} value={text(stored)} onChange={(value) => onChange(section, field, value)} />
      <Warn id={`${section}.${field}`} text={warns[`${section}.${field}`]} />
    </View>
  );
}

/** The WHO cards that follow Part 2, each its own titled tile, then the "not mandatory" footnote. Hidden parts are not rendered (rules.ts). */
function CertificateDetails({ certificate, provenance, shown, warns, onChange }: { certificate: JsonObject; provenance: JsonObject; shown: Visibility; warns: Warnings; onChange: OnChange }) {
  const layout = useLayout();
  const pregnancy = object(certificate.MaternalDeath).WasPregnant;
  const choice = (section: string, key: string, label: string, options: ReadonlyArray<readonly [number, string]>, name: string, disabled = false) => (
    <ChoiceField name={name} label={label} value={object(certificate[section])[key]} options={options} badge={object(certificate[section])[key] === undefined ? undefined : provenanceBadge(provenance, `${section}.${key}`)} disabled={disabled} onChange={(value) => onChange(section, key, value)} />
  );
  const shared = { certificate, provenance, warns, onChange };
  return (
    <View style={{ gap: 8 }}>
      <Tile title="Manner of death">
        {choice("MannerOfDeath", "MannerOfDeath", "Manner of death", MANNER_OPTIONS, "doris_manner_of_death")}
        {shown.externalCause ? (
          <>
            <Label>If external cause or poisoning:*</Label>
            <DateValue section="MannerOfDeath" field="DateOfExternalCauseOrPoisoning" label="Date of injury" {...shared} />
            <TextField section="MannerOfDeath" field="DescriptionExternalCause" label="Please describe how external cause occurred (If poisoning please specify poisoning agent)" multiline {...shared} />
            <Label>Place of occurrence of the external cause:*</Label>
            {choice("MannerOfDeath", "PlaceOfOccuranceExternalCause", "Place", PLACE_OPTIONS, "doris_place")}
          </>
        ) : null}
      </Tile>
      {!shown.fetalOrInfant ? (
        <Tile title="Fetal or infant death *"><NotApplicable text="This section is not applicable when it is not a fetal or infant death" /></Tile>
      ) : (
        <Tile title="Fetal or infant death *">
          {choice("FetalOrInfantDeath", "MultiplePregnancy", "Multiple pregnancy", YES_NO_UNKNOWN, "doris_multiple_pregnancy")}
          {choice("FetalOrInfantDeath", "Stillborn", "Stillborn?", YES_NO_UNKNOWN, "doris_stillborn")}
          <View style={layout.grid}>
            {shown.hoursSurvived ? <NumberField section="FetalOrInfantDeath" field="DeathWithin24h" label="If death within 24h specify number of hours survived" {...shared} /> : null}
            <NumberField section="FetalOrInfantDeath" field="BirthWeight" label="Birth weight (in grams)" {...shared} />
            <NumberField section="FetalOrInfantDeath" field="PregnancyWeeks" label="Number of completed weeks of pregnancy" {...shared} />
            <NumberField section="FetalOrInfantDeath" field="AgeMother" label="Age of mother (years)" {...shared} />
          </View>
          <TextField section="FetalOrInfantDeath" field="PerinatalDescription" label="If death was perinatal, please state conditions of mother that affected the fetus and newborn" multiline {...shared} />
        </Tile>
      )}
      {!shown.pregnancy ? (
        <Tile title="Information on pregnancy"><NotApplicable text={`This section is not applicable when the selected sex is ${object(certificate.AdministrativeData).Sex === 1 ? "male" : "not female"}`} /></Tile>
      ) : (
        <Tile title="Information on pregnancy">
          {choice("MaternalDeath", "WasPregnant", "For women, was the deceased pregnant?", YES_NO_UNKNOWN, "doris_was_pregnant")}
          <Warn id="MaternalDeath.WasPregnant" text={warns["MaternalDeath.WasPregnant"]} />
          {choice("MaternalDeath", "TimeFromPregnancy", "If yes please specify the time from pregnancy", PREGNANCY_TIME_OPTIONS, "doris_time_from_pregnancy", pregnancy !== 1)}
          {choice("MaternalDeath", "PregnancyContribute", "Did the pregnancy contribute to the death?", YES_NO_UNKNOWN, "doris_pregnancy_contribute", pregnancy !== 1)}
          {pregnancy !== 1 && pregnancy !== undefined ? <Muted>Pregnancy follow-up answers are excluded from processing unless pregnancy is Yes.</Muted> : null}
        </Tile>
      )}
      <Tile title="Surgery">
        {choice("Surgery", "WasPerformed", "Was surgery performed within the last 4 weeks?", YES_NO_UNKNOWN, "doris_surgery_performed")}
        {shown.surgeryDetail ? (
          <>
            <DateValue section="Surgery" field="Date" label="If yes please specify date of surgery*" {...shared} />
            <TextField section="Surgery" field="Reason" label="If yes please specify reason for surgery (disease or condition)*" {...shared} />
          </>
        ) : null}
      </Tile>
      <Tile title="Autopsy">
        {choice("Autopsy", "WasRequested", "Was an autopsy requested?*", YES_NO_UNKNOWN, "doris_autopsy_requested")}
        {shown.autopsyFindings ? choice("Autopsy", "Findings", "If yes were the findings used in the certification?*", YES_NO_UNKNOWN, "doris_autopsy_findings") : null}
      </Tile>
      <Muted>*fields are not mandatory</Muted>
    </View>
  );
}

function ChoiceField({ label, name, value, options, onChange, badge, disabled }: { label: string; name?: string; value: JsonValue | undefined; options: ReadonlyArray<readonly [number, string]>; onChange: (value: JsonValue | undefined) => void; badge?: string; disabled?: boolean }) {
  return (
    <ChipChoice
      name={name ?? `doris_${label.toLowerCase().replace(/[^a-z0-9]+/g, "_")}`}
      label={label}
      badge={badge}
      disabled={disabled}
      options={[{ value: NOT_SET_VALUE, label: NOT_STATED }, ...options.map(([code, title]) => ({ value: String(code), label: title }))]}
      value={value === undefined ? NOT_SET_VALUE : String(value)}
      onChange={(next) => onChange(next === NOT_SET_VALUE ? undefined : Number(next))}
      onClear={value === undefined ? undefined : () => onChange(undefined)}
    />
  );
}

function ProcessingSummary({ processing, saved, api, vaSid }: { processing: DorisProcessReply | null; saved?: JsonObject; api: WorkspaceApi; vaSid: string }) {
  const savedDoris = object(saved?.doris);
  const savedCodedit = object(saved?.codedit);
  const dorisStatus = processing?.doris.status ?? (typeof savedDoris.status === "string" ? savedDoris.status : undefined);
  const codeditStatus = processing?.codedit.status ?? (typeof savedCodedit.status === "string" ? savedCodedit.status : undefined);
  const dr = object(processing?.doris.result ?? savedDoris.result);
  const cr = object(processing?.codedit.result ?? savedCodedit.result);
  // A reopened run (no live reply) carries its stored UCOD titles and notes beside the engine envelopes.
  const ucodParts = parseUcodParts(processing?.ucod_parts ?? saved?.ucod_parts);
  const whoNotes = (processing?.who_notes ?? array(saved?.who_notes).filter((note): note is string => typeof note === "string"))
    .filter((note) => !isTechnicalWhoNote(note));
  const [showDetails, setShowDetails] = useState(false);
  // An empty report is no box at all; a run of blank lines reads as one blank line.
  const report = (value: unknown) => {
    const body = collapseBlankLines(value);
    return body ? <ReportBox>{body}</ReportBox> : null;
  };
  const reports = [dr.report, cr.report, cr.tabularReport].map(report);
  const hasDetails = typeof dr.stemCode === "string" || typeof dr.uri === "string" || ucodParts.length > 1 || reports.some(Boolean);
  return (
    <Card>
      <CardTitle>DORIS and CoDEdit</CardTitle>
      <Body>DORIS: {dorisStatus ?? "not processed"}</Body>
      {typeof dr.error === "string" ? <Alert variant="destructive">{dr.error}</Alert> : null}
      {dr.reject === true ? <Alert variant="destructive">DORIS rejected the certificate result.</Alert> : null}
      {whoNotes.map((note) => <Muted key={note}>{note}</Muted>)}
      {ucodParts.length ? (
        <View>
          {ucodClusterLines(ucodParts).map((line) => <Body key={line}>{line}</Body>)}
          {typeof dr.code === "string" ? <Badge variant="outline" mono>{dr.code}</Badge> : null}
        </View>
      ) : typeof dr.code === "string" ? <Body>Computed UCOD: {dr.code}</Body> : null}
      <DorisChecks doris={processing?.doris ?? savedDoris} codedit={processing?.codedit ?? savedCodedit} api={api} vaSid={vaSid} />
      {hasDetails ? (
        <View>
          <Button label={showDetails ? "Hide details" : "Details"} variant="outline" accessibilityLabel={showDetails ? "Hide DORIS code details" : "Show DORIS code details"} accessibilityState={{ expanded: showDetails }} onPress={() => setShowDetails((v) => !v)} />
          {showDetails ? (
            <View>
              {ucodParts.length > 1 ? <Muted>{UCOD_CLUSTER_EXPLANATION}</Muted> : null}
              {typeof dr.stemCode === "string" ? <Muted>Computed stem: {dr.stemCode}</Muted> : null}
              {typeof dr.uri === "string" ? <Muted>Computed URI: {dr.uri}</Muted> : null}
              {reports}
            </View>
          ) : null}
        </View>
      ) : null}
      <Separator />
      <Body>CoDEdit: {codeditStatus ?? "not processed"}</Body>
      {saved && typeof saved.final_choice === "string" ? <Body>Saved Step 1 choice: {saved.final_choice}</Body> : null}
    </Card>
  );
}

/** Year-only omission notes are implementation detail; actionable WHO/internal errors remain visible. */
function isTechnicalWhoNote(note: string): boolean {
  return note.startsWith("Year-only dates left out of the WHO check:")
    || (note.startsWith("The date of ") && note.includes(" is year-only. It was left out of the WHO check;"));
}

/** Renders only the owner's Step 1 conditions for masked Step 2 review. */
function CertificateReference({ certificate }: { certificate: JsonObject | null }) {
  if (!certificate) return null;
  const part1 = array(certificate.Part1).filter(isRecord) as CertificateLine[];
  const part2 = lineConditions(certificate.Part2);
  return (
    <Card>
      <CardTitle>Your Step 1 certificate</CardTitle>
      {part1.map((line, index) => (
        <View key={`p1:${index}`}>
          <Body>Part I, line {index + 1}</Body>
          {lineConditions(line).map((condition, conditionIndex) => (
            <Muted key={conditionIndex}>{text(condition.Text)}{text(condition.Code) ? ` — ${text(condition.Code)}` : ""}{text(condition.Interval) ? ` (${text(condition.Interval)})` : ""}</Muted>
          ))}
        </View>
      ))}
      {part2.length ? (
        <View>
          <Body>Part II</Body>
          {part2.map((condition, index) => <Muted key={index}>{text(condition.Text)}{text(condition.Code) ? ` — ${text(condition.Code)}` : ""}</Muted>)}
        </View>
      ) : null}
    </Card>
  );
}
