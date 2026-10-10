import { Pressable, ScrollView, Text, View } from "react-native";

import { Button, Screen, styles } from "../ui";
import type { WorkspaceCategoryNav, WorkspaceIdentity, WorkspacePayload } from "./contracts";

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
  return (
    <Screen title={workspace.case.instance_name} headerAction={<Button label="Exit" kind="secondary" onPress={onExit} />} sidebar={(
      <ScrollView accessibilityLabel="Case categories" style={styles.card}>
        {categories.map((item) => (
          <Pressable key={item.code} accessibilityRole="button" accessibilityState={{ selected: selectedCode === item.code }} onPress={() => onSelectCategory(item.code)}>
            <Text style={selectedCode === item.code ? styles.headline : styles.text}>{item.nav_label}</Text>
          </Pressable>
        ))}
      </ScrollView>
    )}>
      {categoryLoading ? <Text style={styles.muted}>Loading category…</Text> : null}
      {children}
    </Screen>
  );
}
