import type { ReactNode } from "react";
import { StyleSheet, Text, View } from "react-native";

import { controls, radius, spacing, useTheme } from "../theme";
import { useUiStyles } from "../ui";
import { answerText, answerTone } from "./answerTone";
import { categoryMode, groupDiseaseHistory, historySubcategoryIndex, subcategoryHeading, summaryPlacement, workflowGroups, type CategorySubcategory } from "./categoryLayout";
import { AttachmentGallery } from "./media/AttachmentGallery.native";
import type { CategoryPayload, JsonValue, WorkspaceCategoryNav } from "./contracts";

const ATTACHMENT_PATH = /^\/api\/v1\/attachments\/(?:legacy\/[^/?#]+\/[^/?#]+|[^/?#]+)(?:\.[a-zA-Z0-9]+)?$/;
/** Offline coding's draft attachment (src/workspace/localCategories.ts LOCAL_ATTACHMENT_PREFIX). */
const LOCAL_ATTACHMENT = /^digitva-local-attachment:[A-Za-z0-9_]+$/;

/** "Symptoms on VA Interview" as chips, the same summary the web shows (CategoryPanel.web.tsx SummaryBlock). */
function SymptomSummary({ items }: { items: JsonValue[] }) {
  const styles = useUiStyles();
  const { ui, typography } = useTheme();
  if (!items.length) return null;
  return (
    <View style={styles.card}>
      <Text accessibilityRole="header" style={styles.headline}>Symptoms on VA Interview</Text>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
        {/* Facts, not choices: a muted fill and ink text, no ring (round-6 C2). */}
        {items.map((item, index) => (
          <View key={`summary-${index}`} style={{ paddingVertical: spacing.xxs, paddingHorizontal: spacing.sm, borderRadius: radius.full, backgroundColor: ui.muted }}>
            <Text style={{ ...typography.subhead, color: ui.foreground, fontFamily: controls.fontFamily }}>{typeof item === "string" ? item : String(item)}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}

/** One question and its answer as two wrapping columns, the phone form of the web's Query/Response table. */
function QuestionRow({ item, first, renderMedia }: {
  item: CategoryPayload["subcategories"][number]["items"][number];
  first: boolean;
  renderMedia?: (attachmentPath: string) => ReactNode;
}) {
  const styles = useUiStyles();
  const { ui, typography } = useTheme();
  const tone = answerTone(item.value, !!item.flip, !!item.info);
  // Filled like the web badges: red is Petrol error, green Petrol success (each with its own on-colour); info is the primary badge, as the web's brand-bar badge.
  const badge = tone === "red" ? { bg: ui.destructive, fg: ui.destructiveForeground }
    : tone === "green" ? { bg: ui.success, fg: ui.primaryForeground }
    : tone === "info" ? { bg: ui.primary, fg: ui.primaryForeground } : null;
  const text = answerText(item.value);
  return (
    <View style={{ flexDirection: "row", gap: spacing.sm, paddingVertical: spacing.xs, borderTopWidth: first ? 0 : StyleSheet.hairlineWidth, borderColor: ui.separator }}>
      <Text style={[styles.text, { flex: 1, flexShrink: 1, fontWeight: "600" }]}>{item.label}</Text>
      <View style={{ flex: 1, flexShrink: 1, alignItems: "flex-start" }}>
        {badge && text ? (
          <View accessibilityLabel={tone === "info" ? `Informational response: ${text}` : undefined} style={{ backgroundColor: badge.bg, borderRadius: radius.sm, paddingVertical: spacing.xxs, paddingHorizontal: spacing.sm }}>
            <Text style={{ ...typography.subhead, fontWeight: "700", color: badge.fg, fontFamily: controls.fontFamily }}>{text}</Text>
          </View>
        ) : <CategoryValue value={item.value} renderMedia={renderMedia} />}
      </View>
    </View>
  );
}

/** A subcategory card: the question/answer grid, or the media gallery. The heading is hidden for "default". */
function SubcategoryCard({ subcategory, renderMedia, workspaceIdentity }: {
  subcategory: CategorySubcategory;
  renderMedia?: (attachmentPath: string) => ReactNode;
  workspaceIdentity?: string;
}) {
  const styles = useUiStyles();
  const heading = subcategoryHeading(subcategory.label);
  return (
    <View style={styles.card}>
      {heading ? <Text style={styles.headline}>{heading}</Text> : null}
      {subcategory.render_mode === "media_gallery" ? (
        <AttachmentGallery items={subcategory.items} label={subcategory.label} workspaceIdentity={workspaceIdentity} renderMedia={renderMedia} />
      ) : subcategory.items.map((item, index) => (
        <QuestionRow key={`${item.label}-${index}`} item={item} first={index === 0} renderMedia={renderMedia} />
      ))}
    </View>
  );
}

/** Disease / Co-morbidity as the web's DiseaseHistory: Diagnosed, Absent, then the other answers as a grid. */
function DiseaseHistoryCard({ items, renderMedia }: { items: CategorySubcategory["items"]; renderMedia?: (attachmentPath: string) => ReactNode }) {
  const styles = useUiStyles();
  const { positive, negative, remaining } = groupDiseaseHistory(items);
  return (
    <View style={styles.card} accessibilityLabel="Disease history summary">
      <Text style={styles.headline}>Disease / Co-morbidity</Text>
      <Text style={[styles.text, { fontWeight: "600" }]}>Diagnosed by Health Professional</Text>
      <Text style={styles.text}>{positive.length ? positive.join("\n") : "No positive diagnoses found."}</Text>
      <Text style={[styles.text, { fontWeight: "600", marginTop: spacing.sm }]}>Absent</Text>
      <Text style={styles.text}>{negative.length ? negative.join(", ") : "No negative diagnoses found."}</Text>
      {remaining.length ? (
        <View style={{ marginTop: spacing.sm }}>
          <Text style={[styles.text, { fontWeight: "600" }]}>Medical History (Responses)</Text>
          {remaining.map((item, index) => <QuestionRow key={`${item.label}-${index}`} item={item} first={index === 0} renderMedia={renderMedia} />)}
        </View>
      ) : null}
    </View>
  );
}

/** Render ordered server category data as escaped native text and optional media slots; layout rules in categoryLayout.ts. */
export function CategoryPanel({
  category,
  renderMedia,
  categoryNav,
  workspaceIdentity,
  afterContent,
}: {
  category: CategoryPayload;
  renderMedia?: (attachmentPath: string) => ReactNode;
  iconName?: string | null;
  categoryNav?: WorkspaceCategoryNav[];
  workspaceIdentity?: string;
  notesSummary?: ReactNode;
  afterContent?: ReactNode;
}) {
  const styles = useUiStyles();
  const mode = categoryMode(category, categoryNav);
  const placement = summaryPlacement(mode, category.summary_items);
  const card = (subcategory: CategorySubcategory) => <SubcategoryCard key={subcategory.code} subcategory={subcategory} renderMedia={renderMedia} workspaceIdentity={workspaceIdentity} />;
  const summary = <SymptomSummary items={category.summary_items} />;
  let body: ReactNode;
  if (mode === "workflow_panel") {
    const { attachmentSubs, historyItems, otherSubs } = workflowGroups(category, categoryNav);
    body = <>{attachmentSubs.map(card)}{historyItems.length ? <DiseaseHistoryCard items={historyItems} renderMedia={renderMedia} /> : null}{otherSubs.map(card)}</>;
  } else {
    const historyIndex = historySubcategoryIndex({ ...category, render_mode: mode }, categoryNav);
    body = category.subcategories.map((subcategory, index) => index === historyIndex
      ? <DiseaseHistoryCard key={subcategory.code} items={subcategory.items} renderMedia={renderMedia} />
      : card(subcategory));
  }
  return (
    <View accessibilityLabel={category.label}>
      {/* The symptoms card carries its own title; a second heading above it says the same (round-6 C6). */}
      {placement === "before" ? null : <Text style={styles.headline}>{category.label}</Text>}
      {placement === "before" ? summary : null}
      {body}
      {afterContent}
      {placement === "after" ? summary : null}
    </View>
  );
}

/** Render server values as labelled escaped text; attachment URLs go only through the supplied slot. */
export function CategoryValue({
  value,
  renderMedia,
}: {
  value: JsonValue;
  renderMedia?: (attachmentPath: string) => ReactNode;
}) {
  const styles = useUiStyles();
  if (value === null || value === "") return null;
  if (typeof value === "string") {
    if (renderMedia && (ATTACHMENT_PATH.test(value) || LOCAL_ATTACHMENT.test(value))) return <>{renderMedia(value)}</>;
    return <Text style={styles.text}>{value}</Text>;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return <Text style={styles.text}>{String(value)}</Text>;
  }
  if (Array.isArray(value)) {
    return (
      <View>
        {value.map((item, index) => <CategoryValue key={index} value={item} renderMedia={renderMedia} />)}
      </View>
    );
  }
  if (typeof value.label === "string" && "value" in value) {
    return (
      <View>
        <Text style={styles.muted}>{value.label}</Text>
        <CategoryValue value={value.value} renderMedia={renderMedia} />
      </View>
    );
  }
  return (
    <View>
      {Object.entries(value).map(([key, item]) => (
        <View key={key}>
          <Text style={styles.muted}>{valueLabels[key] ?? key.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase())}</Text>
          <CategoryValue value={item} renderMedia={renderMedia} />
        </View>
      ))}
    </View>
  );
}

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
