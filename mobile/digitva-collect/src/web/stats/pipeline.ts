/** Pure rules of the Statistics screen: bar widths and number formatting. No React, so they are unit-tested directly. */
import type { AreaCounts, AreaRow } from "../../area/api";

/** The three stages of one unit's bar. Interviewed = submissions received, coded = final cause of death. */
export type PipelineCounts = Pick<AreaCounts, "deaths_reported" | "submitted" | "final_cod">;

/** False for a project with no death register: deaths reported is 0 everywhere, so "0 reported" says nothing. */
export function hasDeathRegister(counts: Pick<PipelineCounts, "deaths_reported">[]): boolean {
  return counts.some((one) => one.deaths_reported > 0);
}

/** The longest stage of any row: the bar length of 100 percent, so units compare by eye. Without a register, interviews set it. */
export function pipelineScale(rows: { counts: PipelineCounts }[], withReported = true): number {
  return rows.reduce((top, { counts }) => Math.max(top, withReported ? counts.deaths_reported : 0, counts.submitted, counts.final_cod), 0);
}

/** Width of each stage as a whole percent of *scale*; a non-zero count is never narrower than 1 so it stays visible. */
export function stageWidths(counts: PipelineCounts, scale: number): { reported: number; interviewed: number; coded: number } {
  const width = (value: number) => (scale <= 0 || value <= 0 ? 0 : Math.min(100, Math.max(1, Math.round((100 * value) / scale))));
  return { reported: width(counts.deaths_reported), interviewed: width(counts.submitted), coded: width(counts.final_cod) };
}

/** Rows a user can open: a unit with units below it, or a sites-mode site (its card, causes and staff). The unrouted row ends the path. */
export const canDrill = (row: Pick<AreaRow, "kind" | "has_children">): boolean => row.kind === "site" || (row.kind === "unit" && row.has_children);

/**
 * The unit to open straight away: a user scoped below the project whose one root has units under it (a district data
 * manager) would otherwise see only that root as the first level. Null for anything else. Only at the top level.
 */
export function soleOpenUnit(
  summary: { mode: string; project_wide: boolean; unit: unknown; rows: Pick<AreaRow, "kind" | "key" | "has_children">[] },
  selection: { unit: string | null; site: string | null },
): string | null {
  if (selection.unit || selection.site || summary.unit || summary.mode !== "organization" || summary.project_wide) return null;
  const [only] = summary.rows;
  return summary.rows.length === 1 && only.kind === "unit" && only.has_children ? only.key : null;
}

/** Median days with one decimal ("3.5"); null when the server had too little data. */
export function formatDays(days: number | null): string | null {
  return days === null ? null : (Math.round(days * 10) / 10).toString();
}

/** A share as sent by the server, trimmed of a trailing ".0" ("12.5", "40"). */
export function formatPercent(percent: number): string {
  return (Math.round(percent * 10) / 10).toString();
}
