import { useEffect, useRef } from "react";
import { Pressable, ScrollView, Text, useWindowDimensions } from "react-native";

import { useTheme } from "../theme";
import { Button, Screen, useUiStyles } from "../ui";
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
}: WorkspaceLayoutProps) {
  const styles = useUiStyles();
  const phone = useWindowDimensions().width < PHONE_BREAKPOINT;
  const { ui } = useTheme();
  const strip = useRef<ScrollView>(null);
  const tabX = useRef<Record<string, number>>({});
  // The selected tab scrolls into view, a little of its left neighbour showing (round-6 C1).
  useEffect(() => {
    const x = tabX.current[selectedCode];
    if (phone && x !== undefined) strip.current?.scrollTo?.({ x: Math.max(0, x - 16), animated: true });
  }, [phone, selectedCode, categories]);
  const nav = (
    <ScrollView
      ref={strip}
      horizontal={phone}
      showsHorizontalScrollIndicator={false}
      keyboardDismissMode="on-drag"
      accessibilityLabel="Case categories"
      style={phone ? undefined : styles.card}
      contentContainerStyle={phone ? { gap: 20, paddingRight: 16 } : undefined}
    >
      {categories.map((item) => {
        const selected = selectedCode === item.code;
        return phone ? (
          <Pressable
            key={item.code}
            accessibilityRole="button"
            accessibilityState={{ selected }}
            onPress={() => onSelectCategory(item.code)}
            onLayout={(event) => { tabX.current[item.code] = event.nativeEvent.layout.x; }}
            style={{ minHeight: 44, justifyContent: "center", borderBottomWidth: 2, borderBottomColor: selected ? ui.primary : "transparent" }}
          >
            <Text style={[selected ? styles.headline : styles.text, selected && { color: ui.primary }]}>{item.nav_label}</Text>
          </Pressable>
        ) : (
          <Pressable key={item.code} accessibilityRole="button" accessibilityState={{ selected }} onPress={() => onSelectCategory(item.code)}>
            <Text style={selected ? styles.headline : styles.text}>{item.nav_label}</Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
  // On a phone the categories are a strip above the content: a row sidebar would take most of the width.
  return (
    <Screen title={workspace.case.deceased_name ? `${workspace.case.deceased_name} · ${workspace.case.instance_name}` : workspace.case.instance_name} headerAction={phone ? undefined : <Button label="Exit" kind="secondary" onPress={onExit} />} sidebar={phone ? undefined : nav}>
      {phone ? nav : null}
      {categoryLoading ? <Text style={styles.muted}>Loading category…</Text> : null}
      {children}
    </Screen>
  );
}
