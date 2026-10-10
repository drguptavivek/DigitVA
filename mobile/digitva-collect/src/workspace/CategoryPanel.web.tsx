import React, { type ReactNode } from "react";
import { Text, View } from "react-native";

import type { CategoryPayload, JsonValue, WorkspaceCategoryNav } from "./contracts";
import { AttachmentGallery } from "./media/AttachmentGallery.web";

const BLUE = "#004687";
const BORDER = "#e0e5ea";
const HEADER = "#f8f9fa";
const TEXT = "#333333";
const ROBOTO = "Roboto, Arial, sans-serif";
const YES = "#bc2938";
const NO = "#3f9366";
const ATTACHMENT_PATH = /^\/api\/v1\/attachments\/(?:legacy\/[^/?#]+\/[^/?#]+|[^/?#]+)(?:\.[a-zA-Z0-9]+)?$/;

type CategorySubcategory = CategoryPayload["subcategories"][number] & { source_category?: string };
type CategoryItem = CategorySubcategory["items"][number];

function FaIcon({ name, color }: { name: string; color?: string }) {
  return React.createElement("i", { className: `fas ${name}`, style: color ? { color } : undefined, "aria-hidden": true });
}

function primitive(value: JsonValue): string {
  if (value === null || value === "") return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(primitive).filter(Boolean).join(", ");
  return Object.entries(value).map(([key, item]) => `${key.replace(/_/g, " ")}: ${primitive(item)}`).join(" · ");
}

function WebValue({ value, renderMedia }: { value: JsonValue; renderMedia?: (attachmentPath: string) => ReactNode }) {
  if (value === null || value === "") return null;
  if (typeof value === "string") {
    if (renderMedia && ATTACHMENT_PATH.test(value)) return <>{renderMedia(value)}</>;
    return <Text style={webStyles.response}>{value}</Text>;
  }
  if (typeof value === "number" || typeof value === "boolean") return <Text style={webStyles.response}>{String(value)}</Text>;
  if (Array.isArray(value)) return <View style={webStyles.valueList}>{value.map((item, index) => <WebValue key={index} value={item} renderMedia={renderMedia} />)}</View>;
  if (typeof value.label === "string" && "value" in value) return <View><Text style={webStyles.valueLabel}>{value.label}</Text><WebValue value={value.value} renderMedia={renderMedia} /></View>;
  return <View style={webStyles.valueList}>{Object.entries(value).map(([key, item]) => <View key={key}><Text style={webStyles.valueLabel}>{valueLabels[key] ?? key.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase())}</Text><WebValue value={item} renderMedia={renderMedia} /></View>)}</View>;
}

function ResponseValue({ value, flip, info, renderMedia }: { value: JsonValue; flip: boolean; info: boolean; renderMedia?: (attachmentPath: string) => ReactNode }) {
  const text = primitive(value);
  const normalized = text.trim().toLowerCase();
  const isYes = normalized === "yes";
  const isNo = normalized === "no";
  // The legacy renderer changes the badge colour only; the answer text stays as served.
  if (info) return <Text accessibilityLabel={`Informational response: ${text}`} style={webStyles.info}>{text}</Text>;
  if (isYes || isNo) return <Text style={[webStyles.answer, { backgroundColor: (flip ? isNo : isYes) ? YES : NO }]}>{text}</Text>;
  return <WebValue value={value} renderMedia={renderMedia} />;
}

function QueryResponseTable({ items, renderMedia, queryWidth = "60%" }: { items: CategoryItem[]; renderMedia?: (attachmentPath: string) => ReactNode; queryWidth?: string }) {
  const responseWidth = queryWidth === "60%" ? "40%" : "80%";
  return React.createElement("div", { className: "digitva-query-response-table", role: "table", "aria-label": "Question responses", style: webStyles.table },
    React.createElement("div", { className: "digitva-query-response-header", role: "row", style: { ...webStyles.tableHeaderRow, gridTemplateColumns: `${queryWidth} ${responseWidth}` } },
      React.createElement("div", { role: "columnheader", style: webStyles.queryHeader }, "Query"),
      React.createElement("div", { role: "columnheader", style: webStyles.responseHeader }, "Response"),
    ),
    React.createElement("div", { className: "digitva-query-response-body", role: "rowgroup" }, items.map((item, index) => React.createElement("div", { key: `${item.label}-${index}`, className: "digitva-query-response-row", role: "row", style: { ...webStyles.tableRow, gridTemplateColumns: `${queryWidth} ${responseWidth}` } },
      React.createElement("div", { "data-query": "true", role: "cell", style: webStyles.query }, item.label),
      React.createElement("div", { "data-response": "true", role: "cell", style: webStyles.responseCell }, <>
        <ResponseValue value={item.value} flip={item.flip} info={item.info} renderMedia={renderMedia} />
      </>),
    ))),
  );
}

function DiseaseHistory({ items, renderMedia }: { items: CategoryItem[]; renderMedia?: (attachmentPath: string) => ReactNode }) {
  const positive: string[] = [];
  const negative: string[] = [];
  const remaining: CategoryItem[] = [];
  items.forEach((item) => {
    const answer = typeof item.value === "string" ? item.value.trim().toLowerCase() : "";
    if (answer === "yes") positive.push(item.label);
    else if (answer === "no") negative.push(item.label);
    else remaining.push(item);
  });
  return <View style={webStyles.diseaseHistory} accessibilityLabel="Disease history summary">
    <View style={webStyles.diseaseColumns}>
      <View style={webStyles.diseaseColumn}>
        <Text style={webStyles.diseaseHeading}><FaIcon name="fa-clipboard-check" color={BLUE} /> Diagnosed by Health Professional</Text>
        <View style={[webStyles.diseasePanel, webStyles.positivePanel]}>
          <Text style={webStyles.diseasePanelText}>{positive.length ? positive.join("\n") : "No positive diagnoses found."}</Text>
        </View>
      </View>
      <View style={webStyles.diseaseColumn}>
        <Text style={webStyles.diseaseHeading}><FaIcon name="fa-clipboard" color={BLUE} /> Absent</Text>
        <View style={[webStyles.diseasePanel, webStyles.negativePanel]}>
          <Text style={webStyles.diseasePanelText}>{negative.length ? negative.join(", ") : "No negative diagnoses found."}</Text>
        </View>
      </View>
    </View>
    {remaining.length ? <View style={webStyles.diseaseRemaining}>
      <Text style={webStyles.remainingHeading}>Medical History (Responses)</Text>
      <QueryResponseTable items={remaining} renderMedia={renderMedia} />
    </View> : null}
  </View>;
}

function sourceCategory(category: CategoryPayload, subcategory: CategorySubcategory): string {
  return subcategory.source_category ?? category.code;
}

function sourceConfig(category: CategoryPayload, subcategory: CategorySubcategory, categoryNav: WorkspaceCategoryNav[] | undefined) {
  const source = sourceCategory(category, subcategory);
  return categoryNav?.find((item) => item.code === source);
}

function isHistorySource(category: CategoryPayload, subcategory: CategorySubcategory, categoryNav: WorkspaceCategoryNav[] | undefined): boolean {
  const source = sourceConfig(category, subcategory, categoryNav);
  return subcategory.render_mode === "health_history_summary" || source?.render_mode === "health_history_summary";
}

function historySubcategories(category: CategoryPayload, categoryNav: WorkspaceCategoryNav[] | undefined): CategorySubcategory[] {
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

function historySubcategoryIndex(category: CategoryPayload, categoryNav: WorkspaceCategoryNav[] | undefined): number {
  const selected = historySubcategories(category, categoryNav)[0];
  return selected ? category.subcategories.indexOf(selected) : -1;
}

function CategorySection({ category, subcategory, renderMedia, workspaceIdentity }: {
  category: CategoryPayload;
  subcategory: CategorySubcategory;
  renderMedia?: (attachmentPath: string) => ReactNode;
  workspaceIdentity?: string;
}) {
  const mode = subcategory.render_mode || "default";
  if (mode === "media_gallery") {
    return <AttachmentGallery
      items={subcategory.items}
      label={subcategory.label}
      visible={subcategory.items.length > 0}
      workspaceIdentity={workspaceIdentity}
      renderMedia={renderMedia}
    />;
  }
  return <QueryResponseTable items={subcategory.items} renderMedia={renderMedia} queryWidth={category.render_mode === "attachments" && (subcategory.label.toLowerCase().includes("narrat") || subcategory.code === "iv_final") ? "20%" : "60%"} />;
}

function SectionHeading({ icon = "fa-list", children }: { icon?: string; children: ReactNode }) {
  return <Text style={webStyles.sectionHeading}><FaIcon name={icon} /> {children}</Text>;
}

function SummaryBlock({ items }: { items: JsonValue[] }) {
  if (!items.length) return null;
  return <View style={webStyles.summaryBlock}>
    <SectionHeading icon="fa-file-alt">Symptoms on VA Interview</SectionHeading>
    <View style={webStyles.summary}>{items.map((value, index) => <Text key={`summary-${index}`} style={webStyles.summaryBadge}>{primitive(value)}</Text>)}</View>
  </View>;
}

function CategorySections({ category, categoryNav, renderMedia, workspaceIdentity, afterContent }: {
  category: CategoryPayload;
  categoryNav?: WorkspaceCategoryNav[];
  renderMedia?: (attachmentPath: string) => ReactNode;
  workspaceIdentity?: string;
  afterContent?: ReactNode;
}) {
  const historyIndex = historySubcategoryIndex(category, categoryNav);
  return <>
    {category.subcategories.map((subcategory, index) => {
      const history = index === historyIndex;
      return <View key={subcategory.code} style={webStyles.section}>
        {history ? <DiseaseHistory items={subcategory.items} renderMedia={renderMedia} /> : <>
          <SectionHeading icon={subcategory.render_mode === "media_gallery" ? "fa-images" : category.render_mode === "attachments" ? "fa-paperclip" : "fa-list-ul"}>{subcategory.label}</SectionHeading>
          <CategorySection category={category} subcategory={subcategory} renderMedia={renderMedia} workspaceIdentity={workspaceIdentity} />
        </>}
      </View>;
    })}
    {afterContent}
  </>;
}

function WorkflowSections({ category, categoryNav, renderMedia, workspaceIdentity, notesSummary, afterContent }: {
  category: CategoryPayload;
  categoryNav?: WorkspaceCategoryNav[];
  renderMedia?: (attachmentPath: string) => ReactNode;
  workspaceIdentity?: string;
  notesSummary?: ReactNode;
  afterContent?: ReactNode;
}) {
  const attachmentSubs = category.subcategories.filter((subcategory) => sourceConfig(category, subcategory, categoryNav)?.render_mode === "attachments");
  const historySubs = historySubcategories(category, categoryNav);
  const otherSubs = category.subcategories.filter((subcategory) => !attachmentSubs.includes(subcategory) && !historySubs.includes(subcategory));
  const historyItems = historySubs.flatMap((subcategory) => subcategory.items);
  return <>
    <SummaryBlock items={category.summary_items} />
    {attachmentSubs.length ? <View style={webStyles.workflowGroup}>
      <SectionHeading icon="fa-file-medical-alt">Narration and Documents</SectionHeading>
      {attachmentSubs.map((subcategory) => <View key={subcategory.code} style={webStyles.section}>
        <SectionHeading icon={subcategory.render_mode === "media_gallery" ? "fa-images" : "fa-paperclip"}>{subcategory.label}</SectionHeading>
        <CategorySection category={{ ...category, render_mode: "attachments" }} subcategory={subcategory} renderMedia={renderMedia} workspaceIdentity={workspaceIdentity} />
      </View>)}
    </View> : null}
    {historyItems.length ? <View style={webStyles.workflowGroup}>
      <SectionHeading icon="fa-notes-medical">Disease / Co-Morbidity</SectionHeading>
      <DiseaseHistory items={historyItems} renderMedia={renderMedia} />
    </View> : null}
    {otherSubs.map((subcategory) => <View key={subcategory.code} style={webStyles.section}>
      <SectionHeading icon="fa-list-ul">{subcategory.label}</SectionHeading>
      <CategorySection category={category} subcategory={subcategory} renderMedia={renderMedia} workspaceIdentity={workspaceIdentity} />
    </View>)}
    {notesSummary ? <View style={webStyles.workflowGroup}><SectionHeading icon="fa-sticky-note">Notes</SectionHeading>{notesSummary}</View> : null}
    {afterContent}
  </>;
}

/** Render the served category payload with the config-driven HTMX treatment in browsers. */
export function CategoryPanel({ category, iconName, renderMedia, categoryNav, workspaceIdentity, notesSummary, afterContent }: {
  category: CategoryPayload;
  iconName?: string | null;
  renderMedia?: (attachmentPath: string) => ReactNode;
  categoryNav?: WorkspaceCategoryNav[];
  workspaceIdentity?: string;
  notesSummary?: ReactNode;
  afterContent?: ReactNode;
}) {
  const mode = category.render_mode || categoryNav?.find((item) => item.code === category.code)?.render_mode || "table_sections";
  return <View accessibilityLabel={category.label} style={webStyles.root} nativeID="digitva-category-panel">
    {React.createElement("style", null, responsiveCategoryCss)}
    <View style={webStyles.categoryHeading}><FaIcon name={iconName ?? categoryNav?.find((item) => item.code === category.code)?.icon_name ?? "fa-folder-open"} color="#fff" /><Text style={webStyles.categoryHeadingText}>{category.label.toUpperCase()}</Text></View>
    {mode === "workflow_panel"
      ? <WorkflowSections category={category} categoryNav={categoryNav} renderMedia={renderMedia} workspaceIdentity={workspaceIdentity} notesSummary={notesSummary} afterContent={afterContent} />
      : <>
        <CategorySections category={{ ...category, render_mode: mode }} categoryNav={categoryNav} renderMedia={renderMedia} workspaceIdentity={workspaceIdentity} afterContent={afterContent} />
        {mode === "attachments" ? <SummaryBlock items={category.summary_items} /> : null}
      </>}
  </View>;
}

const responsiveCategoryCss = `
#digitva-category-panel .digitva-query-response-table { max-width: 100%; }
@media (max-width: 640px) {
  #digitva-category-panel .digitva-query-response-table { border: 0; display: grid; gap: 10px; }
  #digitva-category-panel .digitva-query-response-header { display: none !important; }
  #digitva-category-panel .digitva-query-response-body { display: grid; gap: 10px; }
  #digitva-category-panel .digitva-query-response-row { display: grid !important; grid-template-columns: 1fr !important; height: auto !important; min-height: 0 !important; border: 1px solid ${BORDER}; border-radius: 4px; overflow: hidden; }
  #digitva-category-panel .digitva-query-response-row [role="cell"] { display: block; height: auto !important; width: auto !important; border: 0; }
  #digitva-category-panel .digitva-query-response-row [data-query="true"] { background: ${HEADER}; font-weight: 700; }
  #digitva-category-panel .digitva-query-response-row [data-response="true"] { padding-top: 8px; }
}
`;

const webStyles = {
  root: { gap: 10, minWidth: 0 } as any,
  categoryHeading: { backgroundColor: BLUE, minHeight: 38, marginHorizontal: -14, marginTop: -14, paddingHorizontal: 14, flexDirection: "row", alignItems: "center", gap: 9 } as any,
  categoryHeadingText: { color: "#fff", fontFamily: ROBOTO, fontWeight: "700", fontSize: 15 } as any,
  summaryBlock: { gap: 4 },
  summary: { display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 6, padding: 10, border: `1px solid ${BORDER}`, backgroundColor: "#fff" } as any,
  summaryBadge: { color: TEXT, backgroundColor: "#f8f9fa", border: `1px solid ${BORDER}`, borderRadius: 3, padding: "5px 9px", fontFamily: ROBOTO, fontSize: 15, lineHeight: "24px" } as any,
  workflowGroup: { gap: 10, marginTop: 18 },
  section: { gap: 12, marginTop: 14 },
  sectionHeading: { color: BLUE, fontFamily: ROBOTO, fontWeight: "700", fontSize: 24, lineHeight: "32px", marginBottom: 12 } as any,
  table: { width: "100%", border: `1px solid ${BORDER}`, fontFamily: ROBOTO } as React.CSSProperties,
  tableHeaderRow: { display: "grid", minHeight: 44 } as React.CSSProperties,
  queryHeader: { height: 44, padding: "8px 9px", backgroundColor: HEADER, border: `1px solid ${BORDER}`, color: TEXT, fontFamily: ROBOTO, fontWeight: "700", fontSize: 17, lineHeight: "27.2px", textAlign: "left", verticalAlign: "middle", boxSizing: "border-box" } as React.CSSProperties,
  responseHeader: { height: 44, padding: "8px 9px", backgroundColor: HEADER, border: `1px solid ${BORDER}`, color: TEXT, fontFamily: ROBOTO, fontWeight: "700", fontSize: 17, lineHeight: "27.2px", textAlign: "left", verticalAlign: "middle", boxSizing: "border-box" } as React.CSSProperties,
  tableRow: { display: "grid", minHeight: 46 } as React.CSSProperties,
  query: { padding: "8px 9px", border: `1px solid ${BORDER}`, color: TEXT, fontFamily: ROBOTO, fontSize: 17, lineHeight: "27.2px", verticalAlign: "middle", overflowWrap: "anywhere", boxSizing: "border-box" } as React.CSSProperties,
  responseCell: { padding: "6px 9px", border: `1px solid ${BORDER}`, verticalAlign: "middle", overflowWrap: "anywhere", boxSizing: "border-box" } as React.CSSProperties,
  response: { color: TEXT, fontFamily: ROBOTO, fontSize: 17, lineHeight: "27.2px", flexShrink: 1 } as any,
  answer: { color: "#fff", borderRadius: 3, padding: "8px 16px", fontFamily: ROBOTO, fontWeight: "700", fontSize: 13, lineHeight: "20px" } as any,
  info: { color: "#fff", backgroundColor: BLUE, borderRadius: 9, minWidth: 18, height: 18, textAlign: "center", fontFamily: ROBOTO, fontWeight: "700", fontSize: 12, lineHeight: "18px" } as any,
  valueList: { gap: 3 },
  valueLabel: { color: "#687482", fontFamily: ROBOTO, fontSize: 12 },
  diseaseHistory: { gap: 18 },
  diseaseColumns: { flexDirection: "row", flexWrap: "wrap", gap: 24 },
  diseaseColumn: { flexGrow: 1, flexShrink: 1, flexBasis: 0, minWidth: 240, gap: 8 } as any,
  diseaseHeading: { color: BLUE, fontFamily: ROBOTO, fontWeight: "700", fontSize: 24, lineHeight: "32px" } as any,
  diseasePanel: { minHeight: 72, borderRadius: 3, padding: 16, justifyContent: "center" } as any,
  positivePanel: { backgroundColor: "#b44b52" },
  negativePanel: { backgroundColor: "#477b5b" },
  diseasePanelText: { color: "#fff", fontFamily: ROBOTO, fontSize: 17, lineHeight: "27.2px" } as any,
  diseaseRemaining: { gap: 8 },
  remainingHeading: { color: BLUE, fontFamily: ROBOTO, fontWeight: "700", fontSize: 17, lineHeight: "27.2px" } as any,
} as const;

const valueLabels: Record<string, string> = {
  age: "Age",
  gender: "Gender",
  key_symptoms: "Key symptoms",
  causes: "Predicted causes",
  rank: "Rank",
  cause: "Cause",
  icd10: "ICD-10",
  icd11: "ICD-11",
  likelihood: "Likelihood",
  symptoms: "Symptoms",
};
