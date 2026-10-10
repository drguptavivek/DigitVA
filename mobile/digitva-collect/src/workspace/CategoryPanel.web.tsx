import React from "react";
import { Text, View } from "react-native";

import type { CategoryPayload, JsonValue } from "./contracts";

const BLUE = "#004687";
const BORDER = "#e0e5ea";
const HEADER = "#f8f9fa";
const TEXT = "#333333";
const ROBOTO = "Roboto, Arial, sans-serif";
const YES = "#bc2938";
const NO = "#3f9366";
const ATTACHMENT_PATH = /^\/api\/v1\/attachments\/(?:legacy\/[^/?#]+\/[^/?#]+|[^/?#]+)(?:\.[a-zA-Z0-9]+)?$/;

function FaIcon({ name, color }: { name: string; color?: string }) {
  return React.createElement("i", { className: `fas ${name}`, style: color ? { color } : undefined, "aria-hidden": true });
}

function primitive(value: JsonValue): string {
  if (value === null || value === "") return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(primitive).filter(Boolean).join(", ");
  return Object.entries(value).map(([key, item]) => `${key.replace(/_/g, " ")}: ${primitive(item)}`).join(" · ");
}

function WebValue({ value, renderMedia }: { value: JsonValue; renderMedia?: (attachmentPath: string) => React.ReactNode }) {
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

function ResponseValue({ value, flip, renderMedia }: { value: JsonValue; flip: boolean; renderMedia?: (attachmentPath: string) => React.ReactNode }) {
  const text = primitive(value);
  const normalized = text.toLowerCase();
  const isYes = normalized === "yes";
  const isNo = normalized === "no";
  if (isYes || isNo) return <Text style={[webStyles.answer, { backgroundColor: (flip ? isNo : isYes) ? YES : NO }]}>{text}</Text>;
  return <WebValue value={value} renderMedia={renderMedia} />;
}

type CategoryItem = CategoryPayload["subcategories"][number]["items"][number];

function QueryResponseTable({ items, renderMedia }: { items: CategoryItem[]; renderMedia?: (attachmentPath: string) => React.ReactNode }) {
  return React.createElement("table", { style: webStyles.table },
    React.createElement("thead", null, React.createElement("tr", null,
      React.createElement("th", { style: webStyles.queryHeader }, "Query"),
      React.createElement("th", { style: webStyles.responseHeader }, "Response"),
    )),
    React.createElement("tbody", null, items.map((item, index) => React.createElement("tr", { key: `${item.label}-${index}`, style: webStyles.tableRow },
      React.createElement("td", { style: webStyles.query }, item.label),
      React.createElement("td", { style: webStyles.responseCell }, <>
        <ResponseValue value={item.value} flip={item.flip} renderMedia={renderMedia} />
        {item.info ? <Text accessibilityLabel="More information" style={webStyles.info}>i</Text> : null}
      </>),
    ))),
  );
}

function DiseaseHistory({ items, renderMedia }: { items: CategoryItem[]; renderMedia?: (attachmentPath: string) => React.ReactNode }) {
  const positive: string[] = [];
  const negative: string[] = [];
  const remaining: CategoryItem[] = [];
  items.forEach((item) => {
    const answer = typeof item.value === "string" ? item.value.trim().toLowerCase() : "";
    if (answer === "yes") positive.push(item.label);
    else if (answer === "no") negative.push(item.label);
    else remaining.push(item);
  });
  return <View style={webStyles.diseaseHistory}>
    <View style={webStyles.diseaseColumns}>
      <View style={webStyles.diseaseColumn}>
        <Text style={webStyles.diseaseHeading}><FaIcon name="fa-clipboard-check" color={BLUE} /> Diagnosed by Health Professional</Text>
        <View style={[webStyles.diseasePanel, webStyles.positivePanel]}>
          <Text style={webStyles.diseasePanelText}>{positive.length ? positive.join("\n") : "—"}</Text>
        </View>
      </View>
      <View style={webStyles.diseaseColumn}>
        <Text style={webStyles.diseaseHeading}><FaIcon name="fa-clipboard" color={BLUE} /> Absent</Text>
        <View style={[webStyles.diseasePanel, webStyles.negativePanel]}>
          <Text style={webStyles.diseasePanelText}>{negative.length ? negative.join(", ") : "—"}</Text>
        </View>
      </View>
    </View>
    {remaining.length ? <View style={webStyles.diseaseRemaining}>
      <Text style={webStyles.remainingHeading}>Other responses</Text>
      <QueryResponseTable items={remaining} renderMedia={renderMedia} />
    </View> : null}
  </View>;
}

/** Render the served category payload with the compact HTMX table treatment in browsers. */
export function CategoryPanel({ category, iconName, renderMedia }: { category: CategoryPayload; iconName?: string | null; renderMedia?: (attachmentPath: string) => React.ReactNode }) {
  return <View accessibilityLabel={category.label} style={webStyles.root}>
    <View style={webStyles.categoryHeading}><FaIcon name={iconName ?? "fa-folder-open"} color="#fff" /><Text style={webStyles.categoryHeadingText}>{category.label.toUpperCase()}</Text></View>
    {category.render_mode === "workflow_panel" && category.summary_items.length ? <View style={webStyles.summary}>{category.summary_items.map((value, index) => <Text key={`summary-${index}`} style={webStyles.response}>{primitive(value)}</Text>)}</View> : null}
    {category.subcategories.map((subcategory) => <View key={subcategory.code} style={webStyles.section}>
      {category.code === "vahealthhistorydetails" && subcategory.code === "medical_history" ? null : <Text style={webStyles.sectionHeading}><FaIcon name="fa-list" /> {subcategory.label}</Text>}
      {category.code === "vahealthhistorydetails" && subcategory.code === "medical_history"
        ? <DiseaseHistory items={subcategory.items} renderMedia={renderMedia} />
        : <QueryResponseTable items={subcategory.items} renderMedia={renderMedia} />}
    </View>)}
  </View>;
}

const webStyles = {
  root: { gap: 10, minWidth: 0 } as any,
  categoryHeading: { backgroundColor: BLUE, minHeight: 38, marginHorizontal: -14, marginTop: -14, paddingHorizontal: 14, flexDirection: "row", alignItems: "center", gap: 9 } as any,
  categoryHeadingText: { color: "#fff", fontFamily: ROBOTO, fontWeight: "700", fontSize: 15 } as any,
  summary: { paddingVertical: 8, gap: 4 },
  section: { gap: 12, marginTop: 14 },
  sectionHeading: { color: BLUE, fontFamily: ROBOTO, fontWeight: "700", fontSize: 24, lineHeight: 32, marginBottom: 12 },
  table: { width: "100%", border: `1px solid ${BORDER}`, borderCollapse: "collapse", tableLayout: "fixed" } as React.CSSProperties,
  tableHeader: { backgroundColor: HEADER, minHeight: 44, flexDirection: "row", alignItems: "center", borderBottomWidth: 1, borderBottomColor: BORDER },
  queryHeader: { width: "60%", height: 44, padding: "8px 9px", backgroundColor: HEADER, border: `1px solid ${BORDER}`, color: TEXT, fontFamily: ROBOTO, fontWeight: "700", fontSize: 17, lineHeight: "27.2px", textAlign: "left", verticalAlign: "middle", boxSizing: "border-box" } as React.CSSProperties,
  responseHeader: { width: "40%", height: 44, padding: "8px 9px", backgroundColor: HEADER, border: `1px solid ${BORDER}`, color: TEXT, fontFamily: ROBOTO, fontWeight: "700", fontSize: 17, lineHeight: "27.2px", textAlign: "left", verticalAlign: "middle", boxSizing: "border-box" } as React.CSSProperties,
  tableRow: { height: 46 },
  query: { width: "60%", padding: "8px 9px", border: `1px solid ${BORDER}`, color: TEXT, fontFamily: ROBOTO, fontSize: 17, lineHeight: "27.2px", verticalAlign: "middle", overflowWrap: "anywhere" } as React.CSSProperties,
  responseCell: { width: "40%", padding: "6px 9px", border: `1px solid ${BORDER}`, verticalAlign: "middle", overflowWrap: "anywhere" } as React.CSSProperties,
  response: { color: TEXT, fontFamily: ROBOTO, fontSize: 17, lineHeight: 27.2, flexShrink: 1 },
  answer: { color: "#fff", borderRadius: 3, paddingVertical: 8, paddingHorizontal: 16, fontFamily: ROBOTO, fontWeight: "700", fontSize: 13 },
  info: { color: "#fff", backgroundColor: BLUE, borderRadius: 9, minWidth: 18, height: 18, textAlign: "center", fontFamily: ROBOTO, fontWeight: "700", fontSize: 12, lineHeight: 18 } as any,
  valueList: { gap: 3 },
  valueLabel: { color: "#687482", fontFamily: ROBOTO, fontSize: 12 },
  diseaseHistory: { gap: 18 },
  diseaseColumns: { flexDirection: "row", flexWrap: "wrap", gap: 24 },
  diseaseColumn: { flexGrow: 1, flexShrink: 1, flexBasis: 0, minWidth: 240, gap: 8 } as any,
  diseaseHeading: { color: BLUE, fontFamily: ROBOTO, fontWeight: "700", fontSize: 24, lineHeight: 32 },
  diseasePanel: { minHeight: 72, borderRadius: 3, padding: 16, justifyContent: "center" } as any,
  positivePanel: { backgroundColor: "#b44b52" },
  negativePanel: { backgroundColor: "#477b5b" },
  diseasePanelText: { color: "#fff", fontFamily: ROBOTO, fontSize: 17, lineHeight: 27.2 },
  diseaseRemaining: { gap: 8 },
  remainingHeading: { color: BLUE, fontFamily: ROBOTO, fontWeight: "700", fontSize: 17, lineHeight: 27.2 },
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
