/**
 * XLSForm appearance parsing.
 *
 * An appearance is a space-separated list of tokens, not a single value:
 * `columns-3 no-buttons`, `no-ticks vertical`, `minimal quick`. Comparing the
 * whole string with `===` therefore only ever matches a question that uses one
 * appearance alone, and silently ignores every combination. Everything that
 * reads an appearance goes through this module so that stays fixed in one
 * place.
 *
 * Only the appearances DigitVA implements are given helpers here. Unknown
 * tokens are preserved by `appearanceTokens` and ignored by the controls,
 * which is what ODK clients do with an appearance they do not support.
 */
import type { InstrumentQuestion } from "../types.js";

/** Split an appearance string into its tokens, lower-cased and de-duplicated. */
export function appearanceTokens(appearance: string | undefined): string[] {
  if (!appearance) return [];
  return [...new Set(appearance.trim().toLowerCase().split(/\s+/).filter(Boolean))];
}

/** True when the question declares `token` among its appearances. */
export function hasAppearance(question: InstrumentQuestion, token: string): boolean {
  return appearanceTokens(question.appearance).includes(token);
}

/**
 * Column layout for a select question.
 *
 * - `columns-n` (e.g. `columns-3`) fixes the count
 * - `columns` leaves the count to the renderer, which adapts to screen width
 * - `columns-pack` fits as many choices per line as will go
 *
 * Returns undefined when the question asks for no column layout.
 */
export function columnLayout(
  question: InstrumentQuestion
): { mode: "fixed"; count: number } | { mode: "responsive" | "pack" } | undefined {
  const tokens = appearanceTokens(question.appearance);
  if (tokens.includes("columns-pack")) return { mode: "pack" };
  for (const token of tokens) {
    const match = /^columns-(\d+)$/.exec(token);
    if (match) {
      const count = Number(match[1]);
      if (Number.isInteger(count) && count > 0) return { mode: "fixed", count };
    }
  }
  if (tokens.includes("columns")) return { mode: "responsive" };
  return undefined;
}

/**
 * Bounds for a `range` question, read from the XLSForm `parameters` column
 * (`start=0 end=10 step=1`). ODK's defaults apply when a key is absent.
 */
export function rangeParameters(question: InstrumentQuestion): {
  start: number;
  end: number;
  step: number;
} {
  const found: Record<string, number> = {};
  for (const pair of (question.parameters ?? "").split(/\s+/)) {
    const [key, raw] = pair.split("=");
    const parsed = Number(raw);
    if (key && raw !== undefined && Number.isFinite(parsed)) found[key] = parsed;
  }
  const start = found.start ?? 0;
  const end = found.end ?? 10;
  const step = found.step && found.step !== 0 ? found.step : 1;
  return { start, end, step };
}

/** The discrete values a `range` offers, for the picker and rating appearances. */
export function rangeValues(question: InstrumentQuestion): number[] {
  const { start, end, step } = rangeParameters(question);
  const ascending = end >= start;
  const stride = Math.abs(step) * (ascending ? 1 : -1);
  const values: number[] = [];
  // A malformed range must not spin forever; ODK pickers are short lists.
  const limit = 1000;
  for (let value = start; ascending ? value <= end : value >= end; value += stride) {
    values.push(Number(value.toFixed(6)));
    if (values.length >= limit) break;
  }
  return values;
}

/**
 * Group digits for display only (`thousands-sep`). The submitted value is
 * never touched: this formats what is shown while the field is not being
 * edited.
 */
export function formatGrouped(value: number | string, locale: string): string {
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  try {
    return new Intl.NumberFormat(locale, { maximumFractionDigits: 20 }).format(numeric);
  } catch {
    return String(value);
  }
}
