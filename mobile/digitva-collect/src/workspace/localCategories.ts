/**
 * The server's coding-workspace category rendering, from the bundled display pack and a draft's answers
 * (docs/policy/doris-cod-workflow.md, "Offline coding workspace"; .tasks/2026-10-31-offline-coding-workspace.md).
 * Pure: no React, no I/O. Each function names the server function it mirrors; the golden file
 * __tests__/fixtures/va-display-golden.json holds the server's own output for fixed answers, and the Jest parity
 * test requires these to equal it. Python value semantics (str(), truthiness, ==) are reproduced where the server
 * relies on them. Answers are the ones the server keeps on submission (src/coding/irrelevantAnswers.ts).
 */
import { CryptoDigestAlgorithm, digestStringAsync } from "expo-crypto";

import { ApiError } from "../api";
import type { CategoryPayload, JsonValue, WorkspaceCategoryNav } from "./contracts";

/** What an attachment field that holds a reference renders as; renderMedia resolves it from the draft. */
export const LOCAL_ATTACHMENT_PREFIX = "digitva-local-attachment:";

export type Answers = Record<string, unknown>;

export interface PackCategory {
  code: string;
  label: string;
  nav_label: string;
  icon_name: string | null;
  render_mode: string;
  display_order: number;
  always_include: boolean;
  is_default_start: boolean;
}

type Pairs = Array<[string, string]>;

/** The pack as shipped (schema 1); every ordered collection is an array. */
export interface DisplayPack {
  schema: number;
  form_type_code: string;
  categories: PackCategory[];
  datalevel: Array<[string, Array<[string, Pairs]>]>;
  /** Every active category's field ids in the DB mapping, which decides visibility (not the coder datalevel). */
  visibility: Array<[string, string[]]>;
  subcategories: Array<[string, Array<[string, string, string]>]>;
  choices: Array<[string, Pairs]>;
  flip_labels: string[];
  info_labels: string[];
  summary: { fields: Array<{ field_id: string; label: string; flip_color: boolean }>; special_fields: string[] };
  catcount: { summary: Array<[string, Pairs]>; flip: string[]; special_fields: string[] };
  render: { dates: string[]; datetimes: string[]; zero_skip: string[]; skip_values: string[]; attachments: string[]; multiselect: string[] };
  workflow_panel: { attachments_category: string; health_history_category: string };
  db_revision: string | null;
  content_sha256: string;
}

/** The pack indexed for rendering. */
export interface DisplayPackIndex {
  contentSha256: string;
  categories: PackCategory[];
  datalevel: Map<string, Array<[string, Pairs]>>;
  visibility: DisplayPack["visibility"];
  subcategories: Map<string, Map<string, { label: string; render_mode: string }>>;
  choices: Map<string, Map<string, string>>;
  flipLabels: Set<string>;
  infoLabels: Set<string>;
  summary: DisplayPack["summary"];
  summarySpecial: Set<string>;
  catcount: DisplayPack["catcount"]["summary"];
  catcountFlip: Set<string>;
  catcountSpecial: Set<string>;
  dates: Set<string>;
  datetimes: Set<string>;
  zeroSkip: Set<string>;
  skipValues: Set<string>;
  attachments: Set<string>;
  multiselect: Set<string>;
  workflowPanel: DisplayPack["workflow_panel"];
}

const HEX_SHA256 = /^[0-9a-f]{64}$/;
const isObject = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const isString = (value: unknown): value is string => typeof value === "string";
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every(isString);
const pairs = (value: unknown): value is Pairs => Array.isArray(value) && value.every((item) => Array.isArray(item) && item.length === 2 && isString(item[0]) && isString(item[1]));
const grouped = (value: unknown, inner: (item: unknown) => boolean) =>
  Array.isArray(value) && value.every((item) => Array.isArray(item) && item.length === 2 && isString(item[0]) && inner(item[1]));

/** The exact text the exporter hashed: the hashed keys in schema order, compact (scripts/export_offline_va_display_pack.py). */
function canonicalContent(pack: DisplayPack): string {
  return JSON.stringify({
    schema: pack.schema,
    form_type_code: pack.form_type_code,
    categories: pack.categories,
    datalevel: pack.datalevel,
    visibility: pack.visibility,
    subcategories: pack.subcategories,
    choices: pack.choices,
    flip_labels: pack.flip_labels,
    info_labels: pack.info_labels,
    summary: pack.summary,
    catcount: pack.catcount,
    render: pack.render,
    workflow_panel: pack.workflow_panel,
  });
}

/**
 * Check and index a display pack. Rejects with `va_display_pack_invalid` when the schema, the shape or the content
 * hash is not the one this app understands: the phone then renders nothing rather than a wrong mapping.
 */
export async function createDisplayPackIndex(
  source: unknown,
  digest: (value: string) => Promise<string> = (value) => digestStringAsync(CryptoDigestAlgorithm.SHA256, value),
): Promise<DisplayPackIndex> {
  const fail = (): never => { throw new Error("va_display_pack_invalid"); };
  if (!isObject(source)) fail();
  const pack = source as unknown as DisplayPack;
  const render = isObject(pack.render) ? pack.render : fail();
  const summary = isObject(pack.summary) ? pack.summary : fail();
  const catcount = isObject(pack.catcount) ? pack.catcount : fail();
  const panel = isObject(pack.workflow_panel) ? pack.workflow_panel : fail();
  if (pack.schema !== 1 || pack.form_type_code !== "WHO_2022_VA"
      || !(pack.db_revision === null || isString(pack.db_revision))
      || !isString(pack.content_sha256) || !HEX_SHA256.test(pack.content_sha256)
      || !Array.isArray(pack.categories) || !pack.categories.every((item) => isObject(item) && isString(item.code) && isString(item.label)
        && isString(item.nav_label) && (item.icon_name === null || isString(item.icon_name)) && isString(item.render_mode)
        && typeof item.always_include === "boolean" && typeof item.is_default_start === "boolean")
      || !grouped(pack.datalevel, (subs) => grouped(subs, pairs))
      || !grouped(pack.visibility, strings)
      || !grouped(pack.subcategories, (subs) => Array.isArray(subs) && subs.every((item) => Array.isArray(item) && item.length === 3 && item.every(isString)))
      || !grouped(pack.choices, pairs)
      || !strings(pack.flip_labels) || !strings(pack.info_labels)
      || !Array.isArray(summary.fields) || !summary.fields.every((item) => isObject(item) && isString(item.field_id) && isString(item.label) && typeof item.flip_color === "boolean")
      || !strings(summary.special_fields)
      || !grouped(catcount.summary, pairs) || !strings(catcount.flip) || !strings(catcount.special_fields)
      || !(["dates", "datetimes", "zero_skip", "skip_values", "attachments", "multiselect"] as const).every((key) => strings(render[key]))
      || !isString(panel.attachments_category) || !isString(panel.health_history_category)) {
    fail();
  }
  if (await digest(canonicalContent(pack)) !== pack.content_sha256) fail();
  return {
    contentSha256: pack.content_sha256,
    categories: pack.categories,
    datalevel: new Map(pack.datalevel),
    visibility: pack.visibility,
    subcategories: new Map(pack.subcategories.map(([code, subs]) => [code, new Map(subs.map(([sub, label, mode]) => [sub, { label, render_mode: mode }]))])),
    choices: new Map(pack.choices.map(([field, items]) => [field, new Map(items)])),
    flipLabels: new Set(pack.flip_labels),
    infoLabels: new Set(pack.info_labels),
    summary: pack.summary,
    summarySpecial: new Set(pack.summary.special_fields),
    catcount: pack.catcount.summary,
    catcountFlip: new Set(pack.catcount.flip),
    catcountSpecial: new Set(pack.catcount.special_fields),
    dates: new Set(pack.render.dates),
    datetimes: new Set(pack.render.datetimes),
    zeroSkip: new Set(pack.render.zero_skip),
    skipValues: new Set(pack.render.skip_values),
    attachments: new Set(pack.render.attachments),
    multiselect: new Set(pack.render.multiselect),
    workflowPanel: pack.workflow_panel,
  };
}

// --- Python value semantics ---------------------------------------------------

/** Python `repr()` of a JSON value, for `str()` of a list. */
function pyRepr(value: unknown): string {
  if (typeof value !== "string") return pyStr(value);
  return value.includes("'") && !value.includes('"') ? `"${value}"` : `'${value.replace(/'/g, "\\'")}'`;
}

/**
 * Python `str()` of a JSON value. A JSON number with no fraction is an int to both sides here; the server's
 * float-with-.0 (`12.0`) arrives in JS as 12, which the server's numeric cleaning turns into 12 as well.
 */
function pyStr(value: unknown): string {
  if (value === null || value === undefined) return "None";
  if (value === true) return "True";
  if (value === false) return "False";
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  if (Array.isArray(value)) return `[${value.map(pyRepr).join(", ")}]`;
  return `{${Object.entries(value as Record<string, unknown>).map(([key, item]) => `${pyRepr(key)}: ${pyRepr(item)}`).join(", ")}}`;
}

/** Python truthiness of a JSON value. */
function pyTruthy(value: unknown): boolean {
  if (Array.isArray(value)) return value.length > 0;
  if (isObject(value)) return Object.keys(value).length > 0;
  return !!value;
}

/** Python `value == n` for the 0/1 flag checks (`False == 0`, `True == 1` in Python). */
const pyEqualsFlag = (value: unknown, flag: 0 | 1) =>
  value === flag || value === (flag === 1) || value === String(flag) || value === `${flag}.0`;

/** va_render_cleannumericvalue: "12.0" -> "12"; a float with no fraction is already an int in JS. */
function cleanNumeric<T>(value: T): T | string {
  return typeof value === "string" && value.endsWith(".0") ? value.slice(0, -2) : value;
}

/** _label_choice: the label of the value (or of its numeric-cleaned form) in the field's choices, else the value. */
function labelChoice(choices: Map<string, string>, value: unknown): unknown {
  const candidates = [pyStr(value), pyStr(cleanNumeric(value))];
  for (const candidate of candidates) if (choices.has(candidate)) return choices.get(candidate);
  return value;
}

/** va_render_mapchoicevalue: a space-joined multi-select labels each choice, joined with ", ". */
function mapChoiceValue(pack: DisplayPackIndex, field: string, value: unknown): unknown {
  const choices = pack.choices.get(field);
  if (!choices) return value;
  if (typeof value === "string" && value.includes(" ")) return value.split(" ").map((choice) => choices.get(choice) ?? choice).join(", ");
  return choices.get(pyStr(value)) ?? value;
}

/** _list_answer_as_text: a list answer as its space-joined string would show. */
function listAnswerAsText(pack: DisplayPackIndex, field: string, value: unknown[]): string {
  const choices = pack.choices.get(field);
  if (!pack.multiselect.has(field) && choices) return value.map((item) => pyStr(labelChoice(choices, item))).join(", ");
  return value.map(pyStr).join(" ");
}

const isLeap = (year: number) => (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
const DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
const validDate = (year: number, month: number, day: number) =>
  year >= 1 && month >= 1 && month <= 12 && day >= 1 && day <= (month === 2 && isLeap(year) ? 29 : DAYS[month - 1]);
const pad = (value: number | string, width = 2) => String(value).padStart(width, "0");

/** va_render_standardizedate: strptime "%Y-%m-%d" (of the part before any "T") to "dd-mm-YYYY", else unchanged. */
function standardizeDate(value: unknown): unknown {
  if (!pyTruthy(value)) return "";
  if (typeof value !== "string") return value;
  const match = /^(\d{4})-(1[0-2]|0[1-9]|[1-9])-(3[01]|[12]\d|0[1-9]|[1-9]| [1-9])$/.exec(value.split("T")[0]);
  if (!match) return value;
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3].trim())];
  return validDate(year, month, day) ? `${pad(day)}-${pad(month)}-${pad(year, 4)}` : value;
}

/**
 * va_render_formatdatetimeindian: datetime.fromisoformat to "dd-mm-YYYY HH:MM" in the value's own offset, else unchanged.
 * ponytail: the ISO shapes devices write (date, T or space, HH:MM[:SS[.f]], Z or ±HH[:MM]); Python's fromisoformat
 * also takes basic (compact) forms, which no device writes.
 */
function formatDatetime(value: unknown): unknown {
  if (!value || typeof value !== "string") return value;
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2})(?::(\d{2})(?::(\d{2})(?:[.,]\d+)?)?)?(?:[+-]\d{2}(?::?\d{2}(?::?\d{2}(?:\.\d+)?)?)?)?)?$/
    .exec(value.replace(/Z/g, "+00:00"));
  if (!match) return value;
  const [year, month, day, hour, minute, second] = match.slice(1).map((part) => Number(part ?? 0));
  if (!validDate(year, month, day) || hour > 23 || minute > 59 || second > 59) return value;
  return `${pad(day)}-${pad(month)}-${pad(year, 4)} ${pad(hour)}:${pad(minute)}`;
}

// --- rendering -------------------------------------------------------------------

type Rendered = Map<string, Map<string, unknown>>;

/**
 * Whether va_render_processcategorydata keeps a field: answered (not null), not "ref"/"dk", not a 0 age flag, and an
 * attachment only when it holds a reference (the server skips one with no stored file). No later step drops a value.
 */
function rendersField(pack: DisplayPackIndex, answers: Answers, field: string): boolean {
  if (!Object.hasOwn(answers, field)) return false;
  const value = answers[field];
  if (value === null || value === undefined) return false;
  // A list is skipped exactly when its space-joined string would be.
  const skipTest = Array.isArray(value) ? value.map(pyStr).join(" ") : value;
  if ((typeof skipTest === "string" && pack.skipValues.has(skipTest.toLowerCase())) || (pack.zeroSkip.has(field) && pyEqualsFlag(skipTest, 0))) return false;
  // A list answer is shown as text before the server's attachment step.
  return !pack.attachments.has(field) || Array.isArray(value) || pyTruthy(value);
}

/**
 * va_render_processcategorydata for one category (the array rule included): subcategory -> label -> value, in
 * datalevel order. Values keyed by label, as the server's dict: a repeated label keeps its first place and its last value.
 */
function renderCategory(pack: DisplayPackIndex, answers: Answers, code: string): Rendered {
  const result: Rendered = new Map();
  if (!pyTruthy(answers)) return result;
  for (const [subcategory, fields] of pack.datalevel.get(code) ?? []) {
    const items = new Map<string, unknown>();
    for (const [field, label] of fields) {
      if (!rendersField(pack, answers, field)) continue;
      let value: unknown = answers[field];
      if (Array.isArray(value)) {
        value = listAnswerAsText(pack, field, value);
        if (!pack.multiselect.has(field)) {
          items.set(label, value);
          continue;
        }
      }
      if (pack.dates.has(field)) value = standardizeDate(value);
      if (pack.datetimes.has(field)) value = formatDatetime(value);
      const choices = pack.choices.get(field);
      if (choices) value = labelChoice(choices, value);
      if (pack.zeroSkip.has(field) && pyEqualsFlag(value, 1)) value = "True";
      if (pack.multiselect.has(field)) value = mapChoiceValue(pack, field, value);
      // The server resolves the stored file's URL; the phone holds the reference.
      if (pack.attachments.has(field)) value = `${LOCAL_ATTACHMENT_PREFIX}${field}`;
      items.set(label, cleanNumeric(value));
    }
    if (items.size) result.set(subcategory, items);
  }
  return result;
}

/**
 * get_visible_category_codes: every active category (any role's), always included or rendering something over the
 * DB mapping's fields. `always_include` is known for the coder's categories; the others are shown by their answers.
 */
export function visibleCategoryCodes(pack: DisplayPackIndex, answers: Answers): string[] {
  if (!pyTruthy(answers)) return [];
  const always = new Set(pack.categories.filter((item) => item.always_include).map((item) => item.code));
  return pack.visibility
    .filter(([code, fields]) => always.has(code) || fields.some((field) => rendersField(pack, answers, field)))
    .map(([code]) => code);
}

/** get_category_nav for the coder. */
function nav(pack: DisplayPackIndex, visible: readonly string[]): PackCategory[] {
  return pack.categories.filter((item) => item.always_include || visible.includes(item.code));
}

/** va_preprocess_summcatenotification's category counts: answers that are positive for the symptom, never the special ids. */
function categoryCounts(pack: DisplayPackIndex, answers: Answers): Map<string, number> {
  const counts = new Map<string, number>();
  for (const [category, fields] of pack.catcount) {
    let count = 0;
    for (const [field, label] of fields) {
      if (!Object.hasOwn(answers, field)) continue;
      const raw = answers[field];
      const response = Array.isArray(raw) ? raw.map(pyStr).join(" ") : raw;
      const positive = pack.catcountFlip.has(label) ? response === "no" : response === "yes";
      if (positive && !pack.catcountSpecial.has(field)) count += 1;
    }
    counts.set(category, count);
  }
  return counts;
}

/** _count_attachments_per_category: non-empty fields of `media_gallery` subcategories. */
function attachmentCounts(pack: DisplayPackIndex, answers: Answers): Map<string, number> {
  const counts = new Map<string, number>();
  for (const [category, subcategories] of pack.datalevel) {
    const fields = new Map(subcategories);
    let count = 0;
    for (const [code, { render_mode }] of pack.subcategories.get(category) ?? []) {
      if (render_mode !== "media_gallery") continue;
      for (const [field] of fields.get(code) ?? []) if (pyTruthy(answers[field])) count += 1;
    }
    if (count >= 1) counts.set(category, count);
  }
  return counts;
}

/** build_submission_summary ("Symptoms on VA Interview"). */
function summaryItems(pack: DisplayPackIndex, answers: Answers): string[] {
  if (!pyTruthy(answers)) return [];
  const items: string[] = [];
  for (const { field_id: field, label, flip_color: flip } of pack.summary.fields) {
    if (!Object.hasOwn(answers, field)) continue;
    const answer = answers[field];
    const raw = Array.isArray(answer) ? answer.map(pyStr).join(" ") : answer;
    if (raw === null || raw === undefined || raw === "" || (isObject(raw) && !Object.keys(raw).length)) continue;
    const normalized = pyStr(raw).trim().toLowerCase();
    if (pack.summarySpecial.has(field)) {
      items.push(`${label}: ${pyStr(pack.choices.get(field)?.get(pyStr(raw)) ?? raw)}`);
      continue;
    }
    if (flip ? normalized === "no" : normalized === "yes") items.push(label);
  }
  return items;
}

/** _subcategories: ordered subcategories tagged with their source category. */
function subcategoriesOf(pack: DisplayPackIndex, rendered: Rendered, source: string): CategoryPayload["subcategories"] {
  const meta = pack.subcategories.get(source);
  return [...rendered].map(([code, items]) => ({
    code,
    label: meta?.get(code)?.label ?? code,
    source_category: source,
    render_mode: meta?.get(code)?.render_mode ?? "default",
    items: [...items].map(([label, value]) => ({
      label, value: value as JsonValue, flip: pack.flipLabels.has(label), info: pack.infoLabels.has(label),
    })),
  }));
}

/** One case's workspace view: what the server's workspace and category routes serve for these answers. */
export interface LocalCaseView {
  visibleCategoryCodes: string[];
  categories: WorkspaceCategoryNav[];
  defaultCategory: string;
  summaryItems: string[];
  /** The category payload (`GET /va/<sid>/categories/<code>`); a code outside the nav is 404 `not_found`, as there. */
  category(code: string): CategoryPayload;
  /** A field is shown by some nav category (the case header shows only what the tables show). */
  shows(field: string): boolean;
  /** va_render_mapchoicevalue for the header. */
  choiceLabel(field: string, value: unknown): unknown;
}

export function localCaseView(pack: DisplayPackIndex, answers: Answers): LocalCaseView {
  const visible = visibleCategoryCodes(pack, answers);
  const items = nav(pack, visible);
  const counts = categoryCounts(pack, answers);
  const attachments = attachmentCounts(pack, answers);
  const summary = summaryItems(pack, answers);
  const shown = new Set(items.flatMap((item) => (pack.datalevel.get(item.code) ?? []).flatMap(([, fields]) => fields.map(([field]) => field))));
  return {
    visibleCategoryCodes: visible,
    categories: items.map((item) => ({
      code: item.code,
      label: item.label,
      nav_label: item.nav_label,
      icon_name: item.icon_name,
      count: counts.get(item.code) ?? 0,
      attachment_count: attachments.get(item.code) ?? 0,
      render_mode: item.render_mode,
    })),
    defaultCategory: (items.find((item) => item.is_default_start) ?? items[0])?.code ?? "",
    summaryItems: summary,
    category(code) {
      const config = items.find((item) => item.code === code);
      if (!config) throw new ApiError(404, "not_found");
      const subcategories = subcategoriesOf(pack, renderCategory(pack, answers, code), code);
      if (config.render_mode === "workflow_panel") {
        for (const source of [pack.workflowPanel.attachments_category, pack.workflowPanel.health_history_category]) {
          subcategories.push(...subcategoriesOf(pack, renderCategory(pack, answers, source), source));
        }
      }
      return { code, label: config.label, render_mode: config.render_mode, summary_items: [...summary], subcategories, blocked_by: [] };
    },
    shows: (field) => shown.has(field),
    choiceLabel: (field, value) => mapChoiceValue(pack, field, value),
  };
}

/**
 * The case header fields the server derives at submission for a web or app interview: `va_deceased_age` (int of
 * `finalAgeInYears`, which the server fills from ageInYears / ageInYears2 / "000"), `va_deceased_gender`
 * (Id10019 or "unknown"), and the survey district and state labels when a nav category shows them (_survey_location).
 */
export function localCaseHeader(view: LocalCaseView, answers: Answers): { age: number; gender: string; survey_district: string | null; survey_state: string | null } {
  const ageText = (): string => {
    const final = answers.finalAgeInYears;
    if (final !== null && final !== undefined && final !== "") return pyStr(final);
    for (const key of ["ageInYears", "ageInYears2"]) {
      const value = answers[key];
      if (value === null || value === undefined || typeof value === "boolean") continue;
      if (["", "NaN", "nan"].includes(pyStr(value).trim())) continue;
      return pyStr(value);
    }
    return "000";
  };
  const decimal = ageText().trim();
  // Decimal() accepts plain and exponent notation only; anything else leaves the age at 0.
  const age = /^[+-]?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$/i.test(decimal) ? Math.trunc(Number(decimal)) || 0 : 0;
  const survey = (field: string) => {
    const value = view.shows(field) ? answers[field] : undefined;
    if (value === null || value === undefined) return null;
    return pyStr(view.choiceLabel(field, value)).trim() || null;
  };
  return {
    age,
    gender: pyTruthy(answers.Id10019) ? pyStr(answers.Id10019) : "unknown",
    survey_district: survey("survey_district"),
    survey_state: survey("survey_state"),
  };
}
