/**
 * The problems list: one popup naming every question that needs fixing, each
 * row with its section, question, the reason and a Go button that opens the
 * question (digitva-man7). A bottom sheet on a phone, centred on a wide page.
 */
import React from "react";

import type { WhoVaUiMessages } from "../i18n.js";
import { defaultFormTheme as T } from "./theme.js";
import { withWebTheme } from "./web-theme.js";

export interface ProblemRow {
  key: string;
  /** The question to jump to; absent for a general note. */
  name?: string;
  section: string;
  question: string;
  reason: string;
}

interface Primitives {
  View: React.ElementType;
  Text: React.ElementType;
  Pressable: React.ElementType;
  ScrollView: React.ElementType;
  Modal?: React.ElementType | undefined;
}

export function createProblemsDialog({ View, Text, Pressable, ScrollView, Modal }: Primitives) {
  return function ProblemsDialog({
    messages,
    onClose,
    onGo,
    open,
    portalThemeStyle,
    rows,
    safeInsets
  }: {
    safeInsets?: { top: number; bottom: number } | undefined;
    messages: WhoVaUiMessages;
    onClose: () => void;
    onGo: (name: string) => void;
    open: boolean;
    portalThemeStyle?: unknown;
    rows: readonly ProblemRow[];
  }) {
    if (!open) return null;
    const overlay = (
      <View style={[styles.overlay, portalThemeStyle]} testID="problems-overlay">
        <Pressable
          accessibilityLabel={messages.close}
          accessibilityRole="button"
          onPress={onClose}
          style={styles.scrim}
          testID="problems-scrim"
        />
        <View
          accessibilityViewIsModal
          aria-label={messages.problemsTitle}
          aria-modal="true"
          role="dialog"
          style={[styles.panel, { paddingBottom: 12 + (safeInsets?.bottom ?? 0) }]}
          testID="problems-dialog"
        >
          <View style={styles.header}>
            <Text accessibilityRole="header" style={styles.title}>
              {`${messages.problemsTitle} (${rows.length})`}
            </Text>
            <Pressable
              accessibilityLabel={messages.close}
              accessibilityRole="button"
              onPress={onClose}
              style={styles.close}
              testID="problems-close"
            >
              <Text aria-hidden="true" style={styles.closeGlyph}>
                ✕
              </Text>
            </Pressable>
          </View>
          <ScrollView keyboardShouldPersistTaps="handled" style={styles.list}>
            {rows.length ? (
              rows.map((row) => (
                <View key={row.key} style={styles.row} testID={`problem-${row.name ?? "general"}`}>
                  <View style={styles.rowText}>
                    <Text style={styles.where}>
                      {row.section ? `${row.section} › ${row.question}` : row.question}
                    </Text>
                    <Text style={styles.reason}>{row.reason}</Text>
                  </View>
                  {row.name ? (
                    <Pressable
                      accessibilityLabel={`${messages.problemGo}: ${row.question}`}
                      accessibilityRole="button"
                      onPress={() => onGo(row.name!)}
                      style={styles.go}
                      testID={`problem-go-${row.name}`}
                    >
                      <Text style={styles.goText}>{messages.problemGo}</Text>
                    </Pressable>
                  ) : null}
                </View>
              ))
            ) : (
              <Text style={styles.empty}>{messages.problemsNone}</Text>
            )}
          </ScrollView>
        </View>
      </View>
    );
    if (!Modal) return overlay;
    return (
      <Modal animationType="none" onRequestClose={onClose} transparent visible>
        {overlay}
      </Modal>
    );
  };
}

const styles = {
  overlay: withWebTheme(
    { bottom: 0, justifyContent: "flex-end" as const, left: 0, position: "absolute" as const, right: 0, top: 0, zIndex: 1000 },
    { position: "overlayPosition" }
  ),
  scrim: withWebTheme(
    { backgroundColor: T.scrim, bottom: 0, left: 0, position: "absolute" as const, right: 0, top: 0 },
    {},
    { backgroundColor: "scrim" }
  ),
  panel: withWebTheme(
    {
      alignSelf: "center" as const,
      backgroundColor: T.surface,
      borderTopLeftRadius: 16,
      borderTopRightRadius: 16,
      maxHeight: "80%" as const,
      maxWidth: 640,
      paddingHorizontal: 16,
      paddingTop: 8,
      width: "100%" as const
    },
    { backgroundColor: "surface" }
  ),
  header: {
    alignItems: "center" as const,
    columnGap: 8,
    flexDirection: "row" as const,
    justifyContent: "space-between" as const
  },
  title: withWebTheme(
    { color: T.primary, flex: 1, fontSize: 18, fontWeight: "700" as const, lineHeight: 26, minWidth: 0 },
    { color: "brandDeep" }
  ),
  close: {
    alignItems: "center" as const,
    height: 44,
    justifyContent: "center" as const,
    width: 44
  },
  closeGlyph: withWebTheme({ color: T.primary, fontSize: 18, lineHeight: 22 }, { color: "brandDeep" }),
  list: { flexGrow: 0, flexShrink: 1 },
  row: withWebTheme(
    {
      alignItems: "center" as const,
      borderTopColor: T.border,
      borderTopWidth: 1,
      columnGap: 12,
      flexDirection: "row" as const,
      paddingVertical: 10
    },
    { borderTopColor: "border" }
  ),
  rowText: { flex: 1, minWidth: 0 },
  where: withWebTheme(
    { color: T.text, fontSize: 14, fontWeight: "600" as const, lineHeight: 20 },
    { color: "ink" }
  ),
  reason: withWebTheme({ color: T.danger, fontSize: 14, lineHeight: 20 }, { color: "dangerStrong" }),
  go: withWebTheme(
    {
      alignItems: "center" as const,
      backgroundColor: T.primary,
      borderRadius: 8,
      justifyContent: "center" as const,
      minHeight: 44,
      minWidth: 64,
      paddingHorizontal: 14
    },
    { backgroundColor: "brand", borderRadius: "controlRadius" }
  ),
  goText: withWebTheme(
    { color: T.onPrimary, fontSize: 15, fontWeight: "700" as const, lineHeight: 22 },
    {},
    { color: "onPrimary" }
  ),
  empty: withWebTheme(
    { color: T.textMuted, fontSize: 14, lineHeight: 20, paddingVertical: 16 },
    { color: "muted" }
  )
};
