import { createElement, useEffect } from "react";
import { Modal, ScrollView, Text, View } from "react-native";

import type { UpstreamChangeDetails, UpstreamField } from "../../data/api";
import { t } from "../../i18n";
import { controls, fontSize, radius, spacing, typography, useTheme } from "../../theme";
import { Button } from "../../ui";

function FieldTable({ title, note, fields }: { title: string; note?: string; fields: UpstreamField[] }) {
  const { ui } = useTheme();
  const cell = { padding: `${spacing.xxs}px ${spacing.xs}px`, borderBottom: `1px solid ${ui.border}`, textAlign: "left", verticalAlign: "top", fontSize: fontSize.body, color: ui.foreground, overflowWrap: "anywhere" } as const;
  return (
    <View style={{ gap: spacing.xxs }}>
      <Text accessibilityRole="header" style={{ ...typography.headline, color: ui.foreground }}>{title}</Text>
      {note ? <Text style={{ fontSize: fontSize.caption, color: ui.mutedForeground }}>{note}</Text> : null}
      {createElement(
        "div",
        { role: "region", tabIndex: 0, "aria-label": title, style: { overflowX: "auto" } },
        createElement(
          "table",
          { style: { width: "100%", borderCollapse: "collapse", fontFamily: controls.fontFamily } },
          createElement("thead", null, createElement(
            "tr",
            null,
            createElement("th", { scope: "col", style: { ...cell, fontWeight: 600, minWidth: 160 } }, t("dataChangesField")),
            createElement("th", { scope: "col", style: { ...cell, fontWeight: 600, minWidth: 140 } }, t("dataChangesOld")),
            createElement("th", { scope: "col", style: { ...cell, fontWeight: 600, minWidth: 140 } }, t("dataChangesNew")),
          )),
          createElement("tbody", null, ...fields.map((field, index) => createElement(
            "tr",
            { key: `${field.field_id}:${index}` },
            createElement("td", { style: cell }, field.field_label || field.field_id, createElement("div", { style: { fontSize: fontSize.caption, color: ui.mutedForeground } }, [field.field_id, field.category_code, field.subcategory_code].filter(Boolean).join(" · "))),
            createElement("td", { style: cell }, field.previous_value_display),
            createElement("td", { style: cell }, field.current_value_display),
          ))),
        ),
      )}
    </View>
  );
}

/**
 * What an ODK edit changed on a coded case (GET upstream-change-details): the answers, the operational metadata, and
 * the formatting-only differences, with the data manager's two decisions. Each decision is confirmed by the caller
 * (ConfirmDialog) before anything is sent. Escape closes. The values are shown as text only.
 */
export function UpstreamChangesDialog({ formId, details, loading, error, onAccept, onKeep, onClose }: {
  formId: string;
  details: UpstreamChangeDetails | null;
  loading: boolean;
  error: string;
  onAccept: () => void;
  onKeep: () => void;
  onClose: () => void;
}) {
  const { colors, ui } = useTheme();
  useEffect(() => {
    if (typeof document === "undefined") return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <Modal visible transparent animationType="fade" onRequestClose={onClose}>
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.md, backgroundColor: "rgba(0,0,0,0.5)" }}>
        <View
          accessibilityViewIsModal
          accessibilityRole={"dialog" as never}
          accessibilityLabel={t("dataChangesTitle")}
          style={{ width: "100%", maxWidth: 860, maxHeight: "92%", borderWidth: 1, borderRadius: radius.lg, padding: spacing.md, gap: spacing.sm, backgroundColor: colors.surface, borderColor: colors.border }}
        >
          <Text accessibilityRole="header" style={{ ...typography.headline, color: colors.text }}>{t("dataChangesTitle")}</Text>
          {formId ? <Text style={{ fontSize: fontSize.caption, color: ui.mutedForeground }}>{t("dataChangesForm", { id: formId })}</Text> : null}
          <ScrollView style={{ flexShrink: 1 }} contentContainerStyle={{ gap: spacing.md }}>
            {loading ? <Text style={{ ...typography.subhead, color: ui.mutedForeground }}>{t("loading")}</Text> : null}
            {error ? <Text accessibilityRole="alert" style={{ ...typography.subhead, color: ui.destructiveText }}>{error}</Text> : null}
            {details ? (
              <>
                {details.changed_fields.length ? (
                  <FieldTable title={t("dataChangesData")} fields={details.changed_fields} />
                ) : (
                  <Text style={{ ...typography.subhead, color: ui.mutedForeground }}>{t("dataChangesNoData")}</Text>
                )}
                {details.non_substantive_changed_fields.length ? <FieldTable title={t("dataChangesMetadata")} note={t("dataChangesMetadataNote")} fields={details.non_substantive_changed_fields} /> : null}
                {details.formatting_only_changed_fields.length ? <FieldTable title={t("dataChangesFormatting")} note={t("dataChangesFormattingNote")} fields={details.formatting_only_changed_fields} /> : null}
              </>
            ) : null}
          </ScrollView>
          {details ? (
            <View style={{ gap: spacing.xs }}>
              <Text style={{ fontSize: fontSize.caption, color: ui.mutedForeground }}>{t("dataChangesAcceptNote")}</Text>
              <Text style={{ fontSize: fontSize.caption, color: ui.mutedForeground }}>{t("dataChangesKeepNote")}</Text>
            </View>
          ) : null}
          <View style={{ flexDirection: "row", flexWrap: "wrap", justifyContent: "flex-end", gap: spacing.xs }}>
            <Button kind="secondary" label={t("dataClose")} onPress={onClose} />
            {details ? <Button variant="outline" label={t("dataChangesKeep")} onPress={onKeep} /> : null}
            {details ? <Button kind="primary" label={t("dataChangesAccept")} onPress={onAccept} /> : null}
          </View>
        </View>
      </View>
    </Modal>
  );
}
