/** Per-tab recovery for explicitly permitted COD fields; never a substitute for fresh authorization. */
import { Platform } from "react-native";
import type { JsonObject, WorkspaceIdentity, WorkspacePayload } from "../contracts";
import { browserSessionStore } from "../viewState";

export const DORIS_DRAFT_KEY = "digitva:doris:draft:v1";
export type DraftContext = { fingerprint: string; vaSid: string; mode: string; payloadVersion: string; projectMode: string };
type Selection = { code: string; title: string; uri: string };
type CodDraft = { step: string; certificate: JsonObject; selectedCause: Selection | null; remark: string };
type Draft = { schemaVersion: 1; context: DraftContext; cod?: CodDraft; pendingNote?: string };
const MAX_BYTES = 200_000;
let activeFingerprint: string | undefined;
let recoveryGeneration = 0;
/** Invalidate memory drafts when another form starts or the session ends. */
export function browserDraftGeneration(): number { return recoveryGeneration; }

/** Disable recovery for old servers, read-only workspaces and native clients. */
export function draftContext(workspace: WorkspacePayload, identity: WorkspaceIdentity): DraftContext | undefined {
  const { doris_draft_context, payload_version_id } = workspace.case;
  if (Platform.OS !== "web" || identity.mode === "view" || !doris_draft_context || !payload_version_id) return undefined;
  return { fingerprint: doris_draft_context, vaSid: identity.vaSid, mode: identity.mode, payloadVersion: payload_version_id, projectMode: workspace.case.project_mode };
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function boundedText(value: unknown, limit: number): value is string {
  return typeof value === "string" && value.length <= limit;
}

/** Copy only the COD line fields, including uncoded text and multiple conditions per line. */
export function codCertificate(value: JsonObject): JsonObject {
  const line = (raw: unknown): JsonObject => {
    if (!record(raw) || !Array.isArray(raw.Conditions) || raw.Conditions.length > 30) throw new Error("Invalid draft line");
    return { Conditions: raw.Conditions.map((condition: unknown) => {
      if (!record(condition)) throw new Error("Invalid draft condition");
      const result: JsonObject = {};
      for (const key of ["Text", "Code", "LinearizationURI", "Interval"]) {
        if (condition[key] === undefined) continue;
        if (!boundedText(condition[key], key === "Text" ? 10_000 : 2000)) throw new Error("Invalid draft condition field");
        result[key] = condition[key];
      }
      return result;
    }) };
  };
  if (value.Part1 !== undefined && (!Array.isArray(value.Part1) || value.Part1.length > 5)) throw new Error("Invalid draft certificate");
  return { Part1: (Array.isArray(value.Part1) ? value.Part1 : []).map(line), ...(value.Part2 === undefined ? {} : { Part2: line(value.Part2) }) };
}

/** Clear only our fixed key; blocked storage is harmless. */
export function clearBrowserDraft(): void {
  activeFingerprint = undefined;
  recoveryGeneration += 1;
  try { browserSessionStore()?.removeItem(DORIS_DRAFT_KEY); } catch { /* Storage may be disabled. */ }
}

/** A completed case callback may clear only the context it still owns. */
export function clearCaseBrowserDraft(context: DraftContext | undefined): void {
  if (!context || activeFingerprint !== context.fingerprint) return;
  clearBrowserDraft();
}

/** Read after the server workspace is authorized; a different context discards the old form. */
function read(context: DraftContext | undefined): Draft | undefined {
  if (!context || (activeFingerprint !== undefined && activeFingerprint !== context.fingerprint)) return undefined;
  try {
    const raw = browserSessionStore()?.getItem(DORIS_DRAFT_KEY);
    if (!raw) return undefined;
    if (raw.length > MAX_BYTES) throw new Error("Draft too large");
    const value: unknown = JSON.parse(raw);
    if (!record(value) || value.schemaVersion !== 1 || !record(value.context)
      || Object.entries(context).some(([key, field]) => value.context && (value.context as Record<string, unknown>)[key] !== field)) throw new Error("Draft context changed");
    const result: Draft = { schemaVersion: 1, context };
    if (value.pendingNote !== undefined) {
      if (!boundedText(value.pendingNote, 20_000)) throw new Error("Invalid note draft");
      result.pendingNote = value.pendingNote;
    }
    if (value.cod !== undefined) {
      if (!record(value.cod) || !boundedText(value.cod.step, 20) || !boundedText(value.cod.remark, 20_000) || !record(value.cod.certificate)) throw new Error("Invalid COD draft");
      const selected = value.cod.selectedCause;
      if (selected !== null && (!record(selected) || !boundedText(selected.code, 2000) || !boundedText(selected.title, 10_000) || !boundedText(selected.uri, 2000))) throw new Error("Invalid selected cause");
      result.cod = { step: value.cod.step, remark: value.cod.remark, certificate: codCertificate(value.cod.certificate as JsonObject), selectedCause: selected === null ? null : { code: selected.code as string, title: selected.title as string, uri: selected.uri as string } };
    }
    return result;
  } catch {
    clearBrowserDraft();
    return undefined;
  }
}

function write(value: Draft): void {
  if (activeFingerprint !== value.context.fingerprint) return;
  try {
    const raw = JSON.stringify(value);
    if (raw.length <= MAX_BYTES) browserSessionStore()?.setItem(DORIS_DRAFT_KEY, raw);
  } catch { /* A full or disabled store must never prevent editing. */ }
}

/** Start only after a successful workspace read, clearing a preceding form's recovery data. */
export function activateBrowserDraft(context: DraftContext | undefined): void {
  if (Platform.OS !== "web") return;
  if (!context) { clearBrowserDraft(); return; }
  if (activeFingerprint !== context.fingerprint) {
    activeFingerprint = undefined;
    recoveryGeneration += 1;
  }
  read(context);
  activeFingerprint = context.fingerprint;
}
export function readCodDraft(context: DraftContext | undefined, step: string): CodDraft | undefined {
  const cod = read(context)?.cod;
  return cod?.step === step ? cod : undefined;
}
export function saveCodDraft(context: DraftContext | undefined, cod: CodDraft): void {
  if (!context || !boundedText(cod.remark, 20_000) || !boundedText(cod.step, 20)) return;
  const selected = cod.selectedCause;
  if (selected && (!boundedText(selected.code, 2000) || !boundedText(selected.title, 10_000) || !boundedText(selected.uri, 2000))) return;
  try {
    write({ ...(read(context) ?? { schemaVersion: 1, context }), cod: {
      step: cod.step, remark: cod.remark, certificate: codCertificate(cod.certificate),
      selectedCause: selected ? { code: selected.code, title: selected.title, uri: selected.uri } : null,
    } });
  } catch { /* Invalid or oversize drafts are not stored. */ }
}
/** Step 1 submission ends its COD draft, while an unsaved private note stays with the case. */
export function clearCodDraft(context: DraftContext | undefined): void {
  const value = read(context);
  if (!value) return;
  delete value.cod;
  write(value);
}
export function readPendingNote(context: DraftContext | undefined): string | undefined { return read(context)?.pendingNote; }
export function savePendingNote(context: DraftContext | undefined, content: string | undefined): void {
  if (!context || (content !== undefined && content.length > 20_000)) return;
  const value = read(context) ?? { schemaVersion: 1 as const, context };
  if (content === undefined) delete value.pendingNote;
  else value.pendingNote = content;
  write(value);
}
