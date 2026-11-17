import type { CategoryPayload, WorkspaceCategoryNav } from "./contracts";
import { humanizeKey } from "./humanizeKey";

/**
 * Category layout rules shared by CategoryPanel.tsx (phone) and CategoryPanel.web.tsx so the two cannot drift.
 * Pure: no React, no styles.
 */
export type CategorySubcategory = CategoryPayload["subcategories"][number] & { source_category?: string };
type CategoryItem = CategorySubcategory["items"][number];

/** The category's render mode: its own, else the nav entry's, else the server default (web CategoryPanel). */
export function categoryMode(category: CategoryPayload, categoryNav: WorkspaceCategoryNav[] | undefined): string {
  return category.render_mode || categoryNav?.find((item) => item.code === category.code)?.render_mode || "table_sections";
}

/**
 * Where "Symptoms on VA Interview" shows. The server sends summary_items on every category (online and offline);
 * the web shows them only in workflow panels (first) and attachments/Narration (after the narrative and its panels).
 */
export function summaryPlacement(mode: string, summaryItems: unknown[]): "before" | "after" | null {
  if (!summaryItems.length) return null;
  if (mode === "workflow_panel") return "before";
  return mode === "attachments" ? "after" : null;
}

/** A subcategory heading: nothing for the "default" placeholder, a readable label for raw keys ("risk_factors"). */
export function subcategoryHeading(label: string): string | null {
  return label.trim().toLowerCase() === "default" ? null : humanizeKey(label);
}

/** Disease history split by the answer: Yes -> diagnosed, No -> absent, anything else stays a question row. */
export function groupDiseaseHistory<T extends { label: string; value: unknown }>(items: T[]): { positive: string[]; negative: string[]; remaining: T[] } {
  const positive: string[] = [];
  const negative: string[] = [];
  const remaining: T[] = [];
  items.forEach((item) => {
    const answer = typeof item.value === "string" ? item.value.trim().toLowerCase() : "";
    if (answer === "yes") positive.push(item.label);
    else if (answer === "no") negative.push(item.label);
    else remaining.push(item);
  });
  return { positive, negative, remaining };
}

function sourceCategory(category: CategoryPayload, subcategory: CategorySubcategory): string {
  return subcategory.source_category ?? category.code;
}

export function sourceConfig(category: CategoryPayload, subcategory: CategorySubcategory, categoryNav: WorkspaceCategoryNav[] | undefined) {
  const source = sourceCategory(category, subcategory);
  return categoryNav?.find((item) => item.code === source);
}

function isHistorySource(category: CategoryPayload, subcategory: CategorySubcategory, categoryNav: WorkspaceCategoryNav[] | undefined): boolean {
  const source = sourceConfig(category, subcategory, categoryNav);
  return subcategory.render_mode === "health_history_summary" || source?.render_mode === "health_history_summary";
}

export function historySubcategories(category: CategoryPayload, categoryNav: WorkspaceCategoryNav[] | undefined): CategorySubcategory[] {
  const candidates = category.subcategories.filter((subcategory) => (
    category.render_mode === "health_history_summary" || isHistorySource(category, subcategory, categoryNav)
  ));
  const explicit = candidates.filter((subcategory) => subcategory.render_mode === "health_history_summary");
  if (explicit.length) return explicit;
  if (category.render_mode === "health_history_summary") {
    // Category mode is the configuration for legacy payloads that do not carry
    // a subcategory mode. Preserve configured order; unknown answers remain in
    // the detail table instead of changing which section is summarised.
    const selected = candidates[0];
    return selected ? [selected] : [];
  }
  const grouped = new Map<string, CategorySubcategory[]>();
  candidates.forEach((subcategory) => {
    const source = sourceCategory(category, subcategory);
    grouped.set(source, [...(grouped.get(source) ?? []), subcategory]);
  });
  return [...grouped.values()].flatMap((items) => {
    const selected = items[0];
    return selected ? [selected] : [];
  });
}

export function historySubcategoryIndex(category: CategoryPayload, categoryNav: WorkspaceCategoryNav[] | undefined): number {
  const selected = historySubcategories(category, categoryNav)[0];
  return selected ? category.subcategories.indexOf(selected) : -1;
}

/** A workflow panel's subcategories in web order: narration and documents, then Disease / Co-Morbidity, then the rest. */
export function workflowGroups(category: CategoryPayload, categoryNav: WorkspaceCategoryNav[] | undefined) {
  const attachmentSubs = category.subcategories.filter((subcategory) => sourceConfig(category, subcategory, categoryNav)?.render_mode === "attachments");
  const historySubs = historySubcategories(category, categoryNav);
  const otherSubs = category.subcategories.filter((subcategory) => !attachmentSubs.includes(subcategory) && !historySubs.includes(subcategory));
  const historyItems: CategoryItem[] = historySubs.flatMap((subcategory) => subcategory.items);
  return { attachmentSubs, historyItems, otherSubs };
}
