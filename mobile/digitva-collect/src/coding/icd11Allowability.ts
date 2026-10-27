/**
 * ICD-11 final-cause allowability on the device: the same rules the server applies in
 * app/services/icd11_mms_service.py (validate_icd11_mms_coding_value_for_submission), app/services/icd_coding_policy.py
 * and app/services/icd_coding_value.py, read from the exported pack (scripts/export_icd11_allowability_pack.py).
 *
 * - A code absent from the pack is not selectable (chapter 22, blocks, residual parents); KD3B.Z is in it.
 * - A "/" cluster is judged by its primary stem: WHO's causing condition (codeinfo hasCausingCondition[0]), else the
 *   first stem.
 * - A sex conflict blocks. An age conflict warns and needs the coder's confirmation, which is recorded in provenance.
 * - "Causing condition not known" is valid on a single stem only.
 * Unknown age or sex adds no filter for that dimension, as on the server. Pure: no I/O, no engine, no clock except the
 * confirmation timestamp the caller passes in.
 */

export type AgeGroup = "neonate" | "infant" | "child" | "adult";
export type Sex = "male" | "female";

export interface AllowabilityPack {
  schema: number;
  release: string;
  db_revision: string | null;
  count: number;
  sha256: string;
  groups: { sex: string; age: string; note: string | null; codes: string[] }[];
}

interface Restriction {
  sex: string;
  age: string;
  note: string | null;
}

export interface AllowabilityIndex {
  release: string;
  /** `<release>+<first 12 of sha256>`: what each offline coding records as the rules it was judged by. */
  version: string;
  codes: ReadonlyMap<string, Restriction>;
}

export interface CodingContext {
  ageGroup: AgeGroup | null;
  sex: Sex | null;
}

/** The server's AgeRestrictionConfirmationRequired.details(). */
export interface AgeRestriction {
  code: string;
  age_group_selectable: string | null;
  restriction_note: string | null;
}

export type AllowabilityResult =
  | { status: "ok" }
  | { status: "blocked"; message: string }
  | { status: "age_confirm"; restriction: AgeRestriction };

export const CAUSING_CONDITION_MESSAGE = "Causing condition not known applies to a single ICD-11 stem code only.";
export const INVALID_EXPRESSION_MESSAGE = "The ICD-11 code expression is not valid.";

const STEM = "[0-9A-Z][A-Z][0-9][0-9A-Z](?:\\.[0-9A-Z]{1,2})?";
const EXTENSION = "[0-9A-Z]+(?:\\.[0-9A-Z]+)?";
// icd_coding_value.ICD11_CODE_EXPRESSION_RE, anchored; the server also caps the token at 256 characters.
const EXPRESSION_RE = new RegExp(`^(${STEM})(?:&${EXTENSION})*(?:/${STEM}(?:&${EXTENSION})*)*$`, "i");
const EXPRESSION_MAX = 256;
const STEM_RE = new RegExp(`^(${STEM})`, "i");

/** Index a pack. Throws on a pack this code does not understand, so a stale asset can never read as "nothing allowed". */
export function createAllowabilityIndex(pack: AllowabilityPack): AllowabilityIndex {
  if (pack.schema !== 1 || typeof pack.release !== "string" || typeof pack.sha256 !== "string" || !Array.isArray(pack.groups)) {
    throw new Error("allowability_pack_invalid");
  }
  const codes = new Map<string, Restriction>();
  for (const group of pack.groups) {
    for (const code of group.codes) codes.set(code, { sex: group.sex, age: group.age, note: group.note });
  }
  if (codes.size !== pack.count) throw new Error("allowability_pack_invalid");
  return { release: pack.release, version: `${pack.release}+${pack.sha256.slice(0, 12)}`, codes };
}

/** The leading code expression of a stored COD value ("<CODE> <title>"), upper-cased, or null when malformed. */
export function extractIcd11CodeExpression(value: string | null | undefined): string | null {
  const token = (value ?? "").trim().split(/\s+/)[0] ?? "";
  if (!token || token.length > EXPRESSION_MAX) return null;
  const candidate = token.toUpperCase();
  return EXPRESSION_RE.test(candidate) ? candidate : null;
}

/** The first stem of an expression (`FB80.B/2F9Z` -> `FB80.B`), or null. */
export function firstStem(expression: string): string | null {
  return STEM_RE.exec(expression.toUpperCase())?.[1] ?? null;
}

export function isCluster(expression: string): boolean {
  return expression.includes("/");
}

/**
 * The stem that drives allowability and the VA cause: WHO's causing condition when codeinfo reports one
 * (`FB80.B/2F9Z` is `2F9Z`), else `first`. Reads only the codeinfo it is given.
 */
export function icd11PrimaryStem(codeinfo: unknown, first: string): string {
  const causing = typeof codeinfo === "object" && codeinfo !== null ? (codeinfo as { hasCausingCondition?: unknown }).hasCausingCondition : undefined;
  if (Array.isArray(causing) && typeof causing[0] === "string") {
    const stem = firstStem(causing[0].trim());
    if (stem) return stem;
  }
  return first;
}

/** null when `expression` may carry "causing condition not known" (one stem, `&` extensions allowed); else the refusal. */
export function causingConditionUnknownError(expression: string | null): string | null {
  return expression && !isCluster(expression) ? null : CAUSING_CONDITION_MESSAGE;
}

/** Judge a final underlying cause: `primaryStem` is the stem the cause buckets by (see icd11PrimaryStem). */
export function checkAllowability(index: AllowabilityIndex, primaryStem: string, context: CodingContext): AllowabilityResult {
  const restriction = index.codes.get(primaryStem);
  // The server's message for both "not a selectable code" and a sex conflict.
  const blocked: AllowabilityResult = { status: "blocked", message: `${primaryStem} is not selectable for this submission.` };
  if (!restriction) return blocked;
  if (context.sex && restriction.sex !== "both" && restriction.sex !== context.sex) return blocked;
  const group = context.ageGroup;
  if (group && restriction.age !== "all" && restriction.age !== group
    && !(restriction.age === "neonate_infant" && (group === "neonate" || group === "infant"))) {
    return { status: "age_confirm", restriction: { code: primaryStem, age_group_selectable: restriction.age, restriction_note: restriction.note } };
  }
  return { status: "ok" };
}

/**
 * The age confirmation record of provenance, as app/services/icd_coding_value.record_final_cod_flags writes it.
 * `dorisWarning` is the processed DORIS plausibility warning; it is kept only when it names the code.
 */
export function ageRestrictionConfirmation(restriction: AgeRestriction, confirmedBy: string, confirmedAt: string, dorisWarning: unknown) {
  return {
    confirmed_by: confirmedBy,
    confirmed_at: confirmedAt,
    code: restriction.code,
    age_group_selectable: restriction.age_group_selectable,
    restriction_note: restriction.restriction_note,
    doris_warning: typeof dorisWarning === "string" && dorisWarning.includes(restriction.code) ? dorisWarning : null,
  };
}

const DAYS_PER_MONTH = 30.4375;
const DAYS_PER_YEAR = 365.25;

function number(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string" || value.trim() === "") return null;
  const parsed = Number(value.trim());
  return Number.isFinite(parsed) ? parsed : null;
}

const flag = (value: unknown): boolean => ["1", "1.0", "true", "True"].includes(String(value).trim());

/**
 * Age at death in days, as who_age_normalization.normalize_who_2022_age picks it (same source precedence and
 * conversions) over the answers the interview stored. When the calculated ageIn* fields are not in the draft, the
 * form's own entry fields (age_group, age_child_<unit>, age_adult) stand in for them. Null when unknown.
 */
export function normalizedAgeDays(data: Record<string, unknown>): number | null {
  const hours = number(data.age_neonate_hours);
  const neonateDays = number(data.age_neonate_days);
  const days = number(data.ageInDays);
  const months = number(data.ageInMonths);
  const years = number(data.ageInYears);
  const years2 = number(data.ageInYears2);
  const finalYears = number(data.finalAgeInYears);
  const child = flag(data.isChild);
  const adult = flag(data.isAdult);
  const neonatal = flag(data.isNeonatal);

  if (hours !== null) return 0;
  if (neonateDays !== null) return neonateDays;
  if (neonatal && days !== null) return days;
  if (child) {
    if (days !== null) return days;
    if (months !== null) return months * DAYS_PER_MONTH;
    const childYears = years ?? years2 ?? finalYears;
    if (childYears !== null) return childYears * DAYS_PER_YEAR;
  }
  if (adult) {
    const adultYears = years ?? years2 ?? finalYears;
    if (adultYears !== null) return adultYears * DAYS_PER_YEAR;
  }
  if (years !== null) return years * DAYS_PER_YEAR;
  if (days !== null) return days;
  if (months !== null) return months * DAYS_PER_MONTH;
  const lateYears = years2 ?? finalYears;
  if (lateYears !== null) return lateYears * DAYS_PER_YEAR;

  // No calculated field: the form's own entry fields.
  const group = String(data.age_group ?? "").trim().toLowerCase();
  if (group === "child") {
    const unit = String(data.age_child_unit ?? "").trim().toLowerCase();
    const value = number(data[`age_child_${unit}`]);
    if (value === null) return null;
    return unit === "days" ? value : unit === "months" ? value * DAYS_PER_MONTH : unit === "years" ? value * DAYS_PER_YEAR : null;
  }
  if (group === "adult") {
    const value = number(data.age_adult);
    return value === null ? null : value * DAYS_PER_YEAR;
  }
  return null;
}

/** neonate/infant/child/adult by the WHO 2022 boundaries (icd_coding_policy.coding_age_group_for_submission). */
export function ageGroupForDays(days: number | null): AgeGroup | null {
  if (days === null) return null;
  if (days < 28) return "neonate";
  if (days < 365) return "infant";
  return days < 12 * DAYS_PER_YEAR ? "child" : "adult";
}

/** The age group and sex of the interview's deceased: male/female only, anything else adds no sex filter. */
export function codingContextFromInterview(data: Record<string, unknown>): CodingContext {
  const sex = typeof data.Id10019 === "string" ? data.Id10019.trim().toLowerCase() : "";
  return {
    ageGroup: ageGroupForDays(normalizedAgeDays(data)),
    sex: sex === "male" || sex === "female" ? sex : null,
  };
}
