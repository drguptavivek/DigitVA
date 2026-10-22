/**
 * Registration numbers (death_registration identifiers; digitva-kzyp, docs/policy/death-registration-identifiers.md).
 * Types, the client-side pre-checks (advice only: the server validates every write again), the
 * per-project type cache and the two calls the UI makes. Browser calls go through the shared
 * requester, which sends X-CSRFToken on every mutation.
 */
import { ApiError, INTAKE_API, requestClientJson, type ClientCsrf } from "./api";
import { formatPhone, normalisePhone as normalisePhoneStrict, PY_SPACE } from "./phoneFormat";

/** The server's whitespace (Python `str.split()`), not JS `\s`: see PY_SPACE. */
const PY_SPACE_EDGES = new RegExp(`^[${PY_SPACE}]+|[${PY_SPACE}]+$`, "g");
const PY_SPACE_RUNS = new RegExp(`[${PY_SPACE}]+`, "g");

export type IdentifierCharType = "digits" | "letters" | "letters_digits" | "letters_digits_hyphen_slash";

/** One active type of a project, as GET /intake/identifier-types serves it. */
export interface IdentifierType {
  code: string;
  label: string;
  min_length: number;
  max_length: number;
  char_type: IdentifierCharType | null;
  pattern: string | null;
  example: string | null;
  required_at_report: boolean;
  sort_order: number;
}

/** A case's number: `value` for viewers who may see it, `present` only for badge viewers (no `value` key). */
export interface CaseIdentifier {
  code: string;
  label: string;
  value?: string | null;
  present?: boolean;
}

export interface IdentifierWarning {
  code: string;
  field: string;
  message: string;
}

export type IdentifierRule = "length" | "char_type" | "pattern";

const CHAR_TYPE_RE: Record<IdentifierCharType, RegExp> = {
  digits: /^[0-9]+$/,
  letters: /^[A-Z]+$/,
  letters_digits: /^[A-Z0-9]+$/,
  letters_digits_hyphen_slash: /^[A-Z0-9/-]+$/,
};

/**
 * What the field shows while typing: NFKC, upper-case, no leading space. It can change the length
 * (a leading space goes, "ß" becomes "SS"), so use typedCaret to place the caret.
 */
export function typedIdentifier(raw: string): string {
  return raw.normalize("NFKC").replace(/^\s+/, "").toUpperCase();
}

/**
 * The shown value and, when typing changed the text, the caret to force. `prev` is the value and
 * selection before the keystroke (onChangeText fires before onSelectionChange, so the selection is
 * still the old one): the caret after the edit is the old selection end moved by the length delta,
 * run through the same transform. undefined caret means the transform changed nothing: leave it to the platform.
 */
export function typedCaret(prev: string, selection: { start: number; end: number }, text: string): { value: string; caret?: number } {
  const value = typedIdentifier(text);
  if (value === text) return { value };
  const raw = Math.min(Math.max(selection.end + text.length - prev.length, 0), text.length);
  return { value, caret: typedIdentifier(text.slice(0, raw)).length };
}

/** What is sent: NFKC, trimmed, inner spaces collapsed, upper-case (the server normalises in the same order). */
export function cleanIdentifier(raw: string | null | undefined): string {
  return (raw ?? "").normalize("NFKC").replace(PY_SPACE_EDGES, "").replace(PY_SPACE_RUNS, " ").toUpperCase();
}

/**
 * The first failing rule of a non-empty value (length, then character type, then pattern), or undefined.
 * A pattern that does not compile as a JS RegExp is skipped: the server is the judge of the pattern.
 */
export function checkIdentifier(type: IdentifierType, raw: string): IdentifierRule | undefined {
  const value = cleanIdentifier(raw);
  if (!value) return undefined;
  const length = [...value].length; // code points, as the server's len()
  if (length < type.min_length || length > type.max_length) return "length";
  if (type.char_type && !CHAR_TYPE_RE[type.char_type]?.test(value)) return "char_type";
  if (type.pattern) {
    // "u" so "." is one code point, as in the server's re2; patterns that
    // are not valid in u-mode fall back to plain mode, then to no check.
    let re: RegExp | undefined;
    for (const flags of ["u", ""]) {
      try {
        re = new RegExp(`^(?:${type.pattern})$`, flags);
        break;
      } catch {
        re = undefined;
      }
    }
    if (re && !re.test(value)) return "pattern";
  }
  return undefined;
}

/** The rule a value breaks per type code; `requireAll` adds the types the registration must carry. */
export function identifierIssues(
  types: IdentifierType[],
  values: Record<string, string | undefined>,
  requireAll = false,
): Record<string, IdentifierRule | "required"> {
  const issues: Record<string, IdentifierRule | "required"> = {};
  for (const type of types) {
    const value = cleanIdentifier(values[type.code]);
    if (!value) {
      if (requireAll && type.required_at_report) issues[type.code] = "required";
      continue;
    }
    const rule = checkIdentifier(type, value);
    if (rule) issues[type.code] = rule;
  }
  return issues;
}

/** The registration body's `identifiers`: only non-empty values, cleaned; undefined when there are none. */
export function identifiersToSend(values: Record<string, string | undefined> | undefined): Record<string, string> | undefined {
  const out: Record<string, string> = {};
  for (const [code, raw] of Object.entries(values ?? {})) {
    const value = cleanIdentifier(raw);
    if (value) out[code] = value;
  }
  return Object.keys(out).length ? out : undefined;
}

/** A correction's `identifiers`: only the codes whose cleaned value differs from the stored one; null clears. */
export function identifierChanges(
  base: Record<string, string | undefined> | undefined,
  current: Record<string, string | undefined> | undefined,
): Record<string, string | null> {
  const changes: Record<string, string | null> = {};
  for (const code of new Set([...Object.keys(base ?? {}), ...Object.keys(current ?? {})])) {
    const before = cleanIdentifier(base?.[code]);
    const after = cleanIdentifier(current?.[code]);
    if (before !== after) changes[code] = after || null;
  }
  return changes;
}

/** The values a case carries (value viewers only); a badge-only entry holds none. */
export function identifierValues(identifiers: CaseIdentifier[] | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  for (const entry of identifiers ?? []) if (typeof entry.value === "string" && entry.value) out[entry.code] = entry.value;
  return out;
}

/**
 * True when no entry carries a `value` key (the badge-only shape). Judged per list, not per entry:
 * one row the server could not decrypt arrives without `value` among entries that have it, and the
 * others must still be shown and prefilled.
 */
export function isBadgeOnly(identifiers: CaseIdentifier[] | undefined): boolean {
  const list = identifiers ?? [];
  return list.length > 0 && list.every((entry) => !("value" in entry));
}

/** Server refusals per type code: `fields: ["identifiers.<code>"]` with the reply's message (which never echoes the value). */
export function identifierFieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || !error.payload) return {};
  const fields = Array.isArray(error.payload.fields) ? error.payload.fields : [];
  const message = typeof error.payload.error === "string" ? error.payload.error : "";
  const out: Record<string, string> = {};
  for (const field of fields) {
    if (typeof field === "string" && field.startsWith("identifiers.")) out[field.slice("identifiers.".length)] = message;
  }
  return out;
}

/** The duplicate warnings of a write reply, keyed by type code. */
export function identifierWarnings(reply: unknown): Record<string, string> {
  const warnings = (reply as { warnings?: unknown } | null | undefined)?.warnings;
  const out: Record<string, string> = {};
  if (!Array.isArray(warnings)) return out;
  for (const warning of warnings as IdentifierWarning[]) {
    if (warning?.code === "identifier_in_use" && typeof warning.field === "string" && warning.field.startsWith("identifiers.")) {
      out[warning.field.slice("identifiers.".length)] = String(warning.message ?? "");
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// Calls
// ---------------------------------------------------------------------------

/** GET /intake/identifier-types: the project's active types. */
export async function getIdentifierTypes(projectId: string, csrf?: ClientCsrf): Promise<IdentifierType[]> {
  const body = await requestClientJson<{ identifier_types?: IdentifierType[] }>(
    `${INTAKE_API}/identifier-types?project_id=${encodeURIComponent(projectId)}`,
    { csrf },
  );
  return Array.isArray(body?.identifier_types) ? body.identifier_types : [];
}

/**
 * PUT /intake/cases/<death_id>/identifiers: the any-time write. `identifiers` holds only the codes to
 * change (null clears); `ifUpdatedAt` is the case's `updated_at` as last seen. Rejects with ApiError:
 * 400 (payload.fields), 404, 409 `case_closed` / `death_stale`.
 */
export function putCaseIdentifiers(
  link: string,
  deathId: string,
  identifiers: Record<string, string | null>,
  ifUpdatedAt: string | undefined,
  csrf: ClientCsrf,
): Promise<{ case: Record<string, unknown>; warnings?: IdentifierWarning[] }> {
  const base = link.replace(/\/+$/, "");
  return requestClientJson(`${base}/${encodeURIComponent(deathId)}/identifiers`, {
    method: "PUT",
    json: { identifiers, ...(ifUpdatedAt ? { if_updated_at: ifUpdatedAt } : {}) },
    csrf,
  });
}

// In-memory cache of the types per project (the browser keeps no other copy). A failure is not cached.
const typeCache = new Map<string, Promise<IdentifierType[]>>();

/** The project's types, fetched once per page load. Rejects when they cannot be loaded (callers say so; a failure is not cached). */
export function loadIdentifierTypes(projectId: string, csrf?: ClientCsrf): Promise<IdentifierType[]> {
  if (!projectId) return Promise.resolve([]);
  let cached = typeCache.get(projectId);
  if (!cached) {
    cached = getIdentifierTypes(projectId, csrf);
    typeCache.set(projectId, cached);
    cached.catch(() => { if (typeCache.get(projectId) === cached) typeCache.delete(projectId); });
  }
  return cached;
}

export function clearIdentifierTypeCache(): void {
  typeCache.clear();
}

// ---------------------------------------------------------------------------
// Offline contract helpers reusing central identifier & phone primitives
// ---------------------------------------------------------------------------

export type IdentifierTypeSpec = IdentifierType & {
  id?: number;
  project_id?: number | string;
  description?: string;
  required_at_registration?: boolean;
  active?: boolean;
};

export type CaseIdentifierValueItem = CaseIdentifier;

export interface IdentifierInUseWarning extends IdentifierWarning {
  code: "identifier_in_use";
}

export function normaliseIdentifier(raw: string | null | undefined): string | null {
  const cleaned = cleanIdentifier(raw);
  return cleaned || null;
}

export function validateIdentifier(
  raw: string | null | undefined,
  rule: IdentifierTypeSpec,
): { valid: true; value: string | null } | { valid: false; error: string } {
  const norm = normaliseIdentifier(raw);
  const isRequired = Boolean(rule.required_at_report ?? rule.required_at_registration);
  if (norm === null) {
    if (isRequired) return { valid: false, error: `${rule.label} is required.` };
    return { valid: true, value: null };
  }
  const broken = checkIdentifier(rule, norm);
  if (broken === "length") {
    return { valid: false, error: `${rule.label} must be between ${rule.min_length} and ${rule.max_length} characters.` };
  }
  if (broken === "char_type") {
    return { valid: false, error: `${rule.label} contains characters not permitted for type '${rule.char_type}'.` };
  }
  if (broken === "pattern") {
    const example = typeof rule.example === "string" ? rule.example.trim() : "";
    return {
      valid: false,
      error: example ? `${rule.label} must look like ${example}.` : `${rule.label} does not match the required format.`,
    };
  }
  return { valid: true, value: norm };
}

export function normalisePhone(raw: string | null | undefined): string | null {
  return typeof raw === "string" ? normalisePhoneStrict(raw) : null;
}

export function formatPhone334(digits10: string | null | undefined): string {
  const norm = normalisePhone(digits10);
  return norm ? formatPhone(norm) : "";
}

/**
 * The 19 sealed PII field IDs from Contract Section 6.6 (`PII_FIELDS`).
 */
export const PII_FIELDS_FLOOR = [
  "Id10007",
  "Id10010",
  "Id10010a",
  "Id10010b",
  "Id10010c",
  "Id10017",
  "Id10018",
  "Id10055",
  "Id10057",
  "Id10061",
  "Id10062",
  "Id10070",
  "Id10071",
  "Id10072",
  "Id10073",
  "visit_address",
  "visit_remarks",
  "abha_number",
  "abha_address",
] as const;

export type SealedPiiFieldId = (typeof PII_FIELDS_FLOOR)[number];
