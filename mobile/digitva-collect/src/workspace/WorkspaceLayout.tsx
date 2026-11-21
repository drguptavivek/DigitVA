import { useRef, useState } from "react";
import { ScrollView, StyleSheet, Text, View, useWindowDimensions } from "react-native";

import { useTheme } from "../theme";
import { Button, Screen, useUiStyles } from "../ui";
import { NotesCloseContext } from "./notesClose";
import { SkeletonCards } from "../ui/StateView";
import { PhoneSectionRail, SectionRows } from "./PhoneSectionRail";
import { WorkspaceScrollContext } from "./scrollTarget";
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
  children,
  notes,
  nextBlockedReason,
}: WorkspaceLayoutProps) {
  const [notesOpen, setNotesOpen] = useState(false);
  const scroller = useRef<ScrollView>(null);
  const index = categories.findIndex((item) => item.code === selectedCode);
  const previous = index > 0 ? categories[index - 1] : undefined;
  const next = index >= 0 ? categories[index + 1] : undefined;
  const blocked = Boolean(next && nextBlockedReason);
  const styles = useUiStyles();
  const phone = useWindowDimensions().width < PHONE_BREAKPOINT;
  const { ui } = useTheme();
  // Tablet: a flat full-height column (the phone panel's rows: icon, name, positives, attachments, 48dp), its first row
  // level with the page body. A rounded card flush to the edge read as misaligned; a ScrollView grows unless pinned.
  const nav = (
    <ScrollView
      keyboardDismissMode="on-drag"
      accessibilityLabel="Case categories"
      style={{ width: 300, flexGrow: 0, flexShrink: 0, backgroundColor: ui.card, borderRightWidth: StyleSheet.hairlineWidth, borderRightColor: ui.border }}
      contentContainerStyle={{ paddingTop: 16, paddingBottom: 16 }}
    >
      <SectionRows categories={categories} selectedCode={selectedCode} onSelect={onSelectCategory} />
    </ScrollView>
  );
  // On a phone the categories are an icon rail floating over the page (PhoneSectionRail): a row sidebar would take most of the width.
  const screen = (
    <Screen title={workspace.case.deceased_name ? `${workspace.case.deceased_name} · ${workspace.case.instance_name}` : workspace.case.instance_name} sidebar={phone ? undefined : nav} scrollRef={scroller}>
      {/* The next section's title and placeholder cards while it loads: a one-line "Loading" collapsed the page and
          pulled Previous / Next up under the finger, then the content pushed them down again (digitva-2rm2). */}
      {categoryLoading ? (
        <View style={{ gap: 8, minHeight: 480 }}>
          <Text accessibilityRole="header" style={[styles.headline, { textAlign: "center" }]}>{categories[index]?.label ?? ""}</Text>
          <SkeletonCards count={4} />
        </View>
      ) : null}
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
  if (!phone) return <WorkspaceScrollContext.Provider value={scroller}>{screen}</WorkspaceScrollContext.Provider>;
  return (
    <View style={{ flex: 1 }}>
      <WorkspaceScrollContext.Provider value={scroller}>{screen}</WorkspaceScrollContext.Provider>
      <PhoneSectionRail categories={categories} selectedCode={selectedCode} onSelect={onSelectCategory} />
    </View>
  );
}
