import { dorisWarningPatterns, type DorisWarningPattern } from "./dorisMessages";

/**
 * Plain-language reading of one DORIS warning for the "Check before you decide" list. Mirrors
 * app/static/js/doris_warnings.js: a known warning (dorisWarningPatterns, generated from the same table) gets its
 * meaning and what to do with the code and its ICD-11 title filled in; anything else is shown as DORIS wrote it,
 * with TUC, TSP and UCOD spelled out. tests/fixtures/doris_warning_cases.json checks both agree.
 */

/** A describe result: `original` is DORIS's text when a known pattern explained the warning, else null. */
export interface DescribedWarning {
  text: string;
  original: string | null;
  code: string | null;
}

function lines(value: unknown): string[] {
  return typeof value === "string" ? value.split("\n").map((line) => line.trim()).filter(Boolean) : [];
}

export function expandAbbreviations(text: string): string {
  return text.replace(/\bTUC\b/g, "tentative underlying cause")
    .replace(/\bTSP\b/g, "tentative starting point")
    .replace(/\bUCOD\b/g, "underlying cause of death");
}

// DORIS warns with a bare rule id ("M4 may have been applied.") and explains the rule in its report.
function explained(warning: string, report: unknown): string {
  const rule = /^(SP\d+|M\d+)\b(?!:)/.exec(warning);
  if (!rule) return warning;
  const detail = lines(report).find((line) => line.startsWith(`${rule[1]}:`));
  if (!detail) return warning;
  return `${warning.replace(/\.$/, "")}: ${detail.slice(rule[1].length + 1).trim()}`;
}

interface KnownWarning {
  entry: DorisWarningPattern;
  values: Record<string, string>;
}

function matchWarning(text: string): KnownWarning | null {
  for (const entry of dorisWarningPatterns) {
    const match = new RegExp(entry.pattern).exec(text);
    if (!match) continue;
    const values: Record<string, string> = {};
    entry.fields.forEach((field, index) => { values[field] = match[index + 1] || ""; });
    return { entry, values };
  }
  return null;
}

/** Describes one warning; titleOf(code) gives the ICD-11 title already known for a code, if any. */
export function describeDorisWarning(warning: string, report: unknown, titleOf: (code: string) => string | undefined = () => undefined): DescribedWarning {
  const text = warning.trim();
  const known = matchWarning(text);
  if (!known) return { text: expandAbbreviations(explained(text, report)), original: null, code: null };
  const code = known.values.code || "";
  const title = code ? titleOf(code) || "" : "";
  const cause = code ? `${code}${title ? ` (${title})` : ""}` : "";
  const fill = (template: string) => template.replace(/\{cause\}/g, cause).replace(/\{manner\}/g, known.values.manner || "");
  return { text: [fill(known.entry.meaning), fill(known.entry.action)].join(" "), original: text, code: code || null };
}

/** The ICD codes the known warnings name in a DORIS warning text (one per line), for title lookups. */
export function dorisWarningCodes(warning: unknown): string[] {
  const codes: string[] = [];
  for (const line of lines(warning)) {
    const code = matchWarning(line)?.values.code;
    if (code && !codes.includes(code)) codes.push(code);
  }
  return codes;
}
