import { useState } from "react";
import { Pressable, ScrollView, Text, View, useWindowDimensions } from "react-native";

import { useTheme } from "../theme";
import { Button, Screen, useUiStyles } from "../ui";
import { NotesCloseContext } from "./notesClose";
import { PhoneSectionRail } from "./PhoneSectionRail";
import type { WorkspaceCategoryNav, WorkspaceIdentity, WorkspacePayload } from "./contracts";

/** Same phone breakpoint as WorkspaceLayout.web and Screen. */
const PHONE_BREAKPOINT = 768;

export type WorkspaceLayoutProps = {
  identity: WorkspaceIdentity;
  workspace: WorkspacePayload;
  categories: WorkspaceCategoryNav[];
  selectedCode: string;
  categoryLoading: boolean;
  onSelectCategory: (code: string) => void;
  onExit: () => void;
  children: React.ReactNode;
  notes?: React.ReactNode;
  smartvaPanel?: React.ReactNode;
  nextBlockedReason?: string;
};

/** Native workspace chrome. The browser has a platform-specific HTMX-like layout. */
export function WorkspaceLayout({
  workspace,
  categories,
  selectedCode,
  categoryLoading,
  onSelectCategory,
  onExit,
  children,
  notes,
  nextBlockedReason,
}: WorkspaceLayoutProps) {
  const [notesOpen, setNotesOpen] = useState(false);
  const index = categories.findIndex((item) => item.code === selectedCode);
  const previous = index > 0 ? categories[index - 1] : undefined;
  const next = index >= 0 ? categories[index + 1] : undefined;
  const blocked = Boolean(next && nextBlockedReason);
  const styles = useUiStyles();
  const phone = useWindowDimensions().width < PHONE_BREAKPOINT;
  const { ui } = useTheme();
  const nav = (
    <ScrollView keyboardDismissMode="on-drag" accessibilityLabel="Case categories" style={styles.card}>
      {categories.map((item) => {
        const selected = selectedCode === item.code;
        return (
          <Pressable key={item.code} accessibilityRole="button" accessibilityState={{ selected }} onPress={() => onSelectCategory(item.code)}>
            <Text style={selected ? styles.headline : styles.text}>{item.nav_label}</Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
  // On a phone the categories are an icon rail floating over the page (PhoneSectionRail): a row sidebar would take most of the width.
  const screen = (
    <Screen title={workspace.case.deceased_name ? `${workspace.case.deceased_name} · ${workspace.case.instance_name}` : workspace.case.instance_name} headerAction={phone ? undefined : <Button label="Exit" kind="secondary" onPress={onExit} />} sidebar={phone ? undefined : nav}>
      {categoryLoading ? <Text style={styles.muted}>Loading category…</Text> : null}
      {children}
      {categories.length > 1 ? (
        <View style={{ gap: 8 }}>
          <View style={{ flexDirection: "row", justifyContent: "space-between", gap: 12 }}>
            <Button label="Previous" kind="secondary" disabled={!previous} onPress={() => previous && onSelectCategory(previous.code)} />
            <Button label="Next" disabled={!next || blocked} onPress={() => next && !blocked && onSelectCategory(next.code)} />
          </View>
          {blocked ? <Text accessibilityRole="alert" style={[styles.text, { color: ui.destructiveText }]}>{nextBlockedReason}</Text> : null}
        </View>
      ) : null}
      {notes ? (
        <View style={{ gap: 8 }}>
          <Button label={notesOpen ? "Hide Notes" : "Notes"} kind="secondary" expanded={notesOpen} onPress={() => setNotesOpen((open) => !open)} />
          {/* Stays mounted while hidden so an unsaved draft survives category changes and closing. */}
          <View style={notesOpen ? undefined : { display: "none" }}>
            <NotesCloseContext.Provider value={() => setNotesOpen(false)}>{notes}</NotesCloseContext.Provider>
          </View>
        </View>
      ) : null}
    </Screen>
  );
  if (!phone) return screen;
  return (
    <View style={{ flex: 1 }}>
      {screen}
      <PhoneSectionRail categories={categories} selectedCode={selectedCode} onSelect={onSelectCategory} />
    </View>
  );
}
