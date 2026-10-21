/**
 * Registration numbers (death_registration identifiers; digitva-kzyp, docs/policy/death-registration-identifiers.md).
 * Types, the client-side pre-checks (advice only: the server validates every write again), the
 * per-project type cache and the two calls the UI makes. Browser calls go through the shared
 * requester, which sends X-CSRFToken on every mutation.
 */
import { ApiError, INTAKE_API, requestClientJson, type ClientCsrf } from "./api";

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
  return (raw ?? "").normalize("NFKC").trim().replace(/\s+/g, " ").toUpperCase();
}

/**
 * The first failing rule of a non-empty value (length, then character type, then pattern), or undefined.
 * A pattern that does not compile as a JS RegExp is skipped: the server is the judge of the pattern.
 */
export function checkIdentifier(type: IdentifierType, raw: string): IdentifierRule | undefined {
  const value = cleanIdentifier(raw);
  if (!value) return undefined;
  if (value.length < type.min_length || value.length > type.max_length) return "length";
  if (type.char_type && !CHAR_TYPE_RE[type.char_type]?.test(value)) return "char_type";
  if (type.pattern) {
    let re: RegExp | undefined;
    try {
      re = new RegExp(`^(?:${type.pattern})$`);
    } catch {
      re = undefined;
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
