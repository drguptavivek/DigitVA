import type { DorisAxis, DorisOption } from "../guidance";

/**
 * Pure rules of the React ICD-11 picker (Collect Plus). They mirror app/static/js/digitva_icd11_picker.js:
 * which search box text is a code, which results withhold "Use", how an axis takes several values and how the
 * chosen parts join into one WHO expression. docs/kb/doris-picker-who-behaviour-rules.md has the evidence.
 */

/** A search result, codeinfo item, related term or built expression the picker can stage. */
export interface PickerItem {
  code: string;
  title: string;
  uri: string;
  matching_text?: string;
  postcoordination?: boolean;
  /** WHO flag: 2 means postcoordination is mandatory, so the code alone is withheld. */
  postcoordination_availability?: unknown;
  related_maternal?: boolean;
  related_perinatal?: boolean;
  has_coding_note?: boolean;
  /** Optional: only a terms reply that carries it shows the tag (see parseDorisTerms). */
  age_restricted?: boolean;
  restriction_note?: string;
  /** The stem's required causing-condition axis was marked unknown; sent on to the final save. */
  causingUnknown?: boolean;
  /** Staged from the builder, which only offers what WHO accepts (all required axes chosen or "not known", or the stem when no axis is required). */
  built?: boolean;
  /** WHO chapter X (terms and codeinfo replies); absent means unknown. */
  extension?: boolean;
  /** WHO's isLeaf (of the first stem for an expression); absent means unknown, never false. */
  leaf?: boolean;
}

/** Chosen axis values by axis id. */
export type Selection = Record<string, DorisOption[]>;

/** WHO's axis whose "not known" answer stands in for a missing required value. */
export const CAUSING_AXIS = "hasCausingCondition";

export const isComplete = (code: string): boolean => /[&/]/.test(code);
export const isExtension = (code: string): boolean => /^X/i.test(code);
export const isMandatory = (item: PickerItem): boolean => item.postcoordination_availability === 2;
/**
 * Why WHO would refuse this item alone on a certificate, as the server's selection check words it, or null. Only the
 * reply's flags count: an item without them (older server, built expression, related term) passes here and the
 * selection check on OK decides.
 */
export function notFinal(item: PickerItem): { kind: "extension" | "category"; stem: string; message: string } | null {
  const { stem } = splitExpression(item.code);
  if (item.extension === true) return { kind: "extension", stem, message: `${stem} is an extension code. It cannot be used alone: add it to a stem through + Build.` };
  if (item.leaf === false) return { kind: "category", stem, message: `${stem} is a category, not a final code. Choose a more specific code under it.` };
  return null;
}
/** The selection check's refusal of a code that is not final, worded as `notFinal` words it; transport.ts shows only text that matches. */
export const NOT_FINAL_REFUSAL = /^[A-Z0-9][A-Z0-9.]{0,15} is (an extension code\. It cannot be used alone: add it to a stem through \+ Build|a category, not a final code\. Choose a more specific code under it)\.$/;
/** A search box value with a digit and no space is a code (codeinfo), anything else is text. */
export const looksCode = (value: string): boolean => /\d/.test(value) && !/\s/.test(value);

/** `BD54&XK9J/MC85` -> stem `BD54` and the other parts, which the builder opens already chosen. */
export function splitExpression(code: string): { stem: string; parts: string[] } {
  const [stem, ...parts] = code.split(/[&/]/);
  return { stem, parts };
}

/** What choosing `option` does to the axis values: toggle, replace in the same WHO block, or single choice. */
export function toggleOption(axis: DorisAxis, values: DorisOption[], option: DorisOption): DorisOption[] {
  const at = values.findIndex((item) => item.code === option.code);
  if (axis.allow_multiple_values === "AllowAlways") return at === -1 ? [...values, option] : values.filter((_item, index) => index !== at);
  if (axis.allow_multiple_values === "AllowedExceptFromSameBlock") {
    if (at !== -1) return values.filter((_item, index) => index !== at);
    const sameBlock = values.findIndex((item) => option.block_uri && item.block_uri === option.block_uri);
    return sameBlock === -1 ? [...values, option] : values.map((item, index) => (index === sameBlock ? option : item));
  }
  return [option];
}

const hasValue = (selected: Selection, axis: DorisAxis): boolean => (selected[axis.id]?.length ?? 0) > 0;

/** "Causing condition not known" counts only while that required axis has no value. */
export function causingUnknownApplies(axes: DorisAxis[], selected: Selection, unknown: boolean): boolean {
  return unknown && axes.some((axis) => axis.id === CAUSING_AXIS && axis.required && !hasValue(selected, axis));
}

export function requiredSatisfied(axes: DorisAxis[], selected: Selection, unknown: boolean): boolean {
  return axes.every((axis) => !axis.required || hasValue(selected, axis) || (axis.id === CAUSING_AXIS && unknown));
}

/**
 * Joins the stem and the chosen parts. WHO canonicalises `stem&ext/stem&ext` (an `&` after a `/` belongs to the
 * second stem), so X extensions go first in axis order, then the `/` stems; "Other postcoordination" is last of
 * the extensions.
 */
export function buildExpression(stem: PickerItem, axes: DorisAxis[], selected: Selection, other: DorisOption | null, unknown: boolean): PickerItem {
  const chosen = [...axes.flatMap((axis) => selected[axis.id] ?? []), ...(other ? [other] : [])];
  const ordered = [...chosen.filter((part) => isExtension(part.code)), ...chosen.filter((part) => !isExtension(part.code))];
  let code = stem.code;
  let uri = stem.uri;
  for (const item of ordered) {
    const separator = isExtension(item.code) ? "&" : "/";
    code += separator + item.code;
    uri += ` ${separator} ${item.uri}`;
  }
  return {
    code,
    uri,
    title: [stem.title, ...ordered.map((part) => part.title)].filter(Boolean).join("; "),
    ...(causingUnknownApplies(axes, selected, unknown) ? { causingUnknown: true } : {}),
  };
}
