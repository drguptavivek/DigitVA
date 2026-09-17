import { usePathname, useRouter } from "expo-router";
import { useEffect, type ReactNode } from "react";
import { Pressable, ScrollView, StatusBar, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useDemoState } from "./DemoState";

export function DemoChrome({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { currentUser, isDatabaseReady, lastUpdate } = useDemoState();

  useEffect(() => {
    if (isDatabaseReady && !currentUser && pathname !== "/") {
      router.replace("/");
    }
  }, [currentUser, isDatabaseReady, pathname, router]);

  return (
    <SafeAreaView style={styles.shell}>
      <StatusBar barStyle="dark-content" />
      <View style={styles.header}>
        <Text style={styles.title}>WHO VA 2022 Demo</Text>
        <Text style={styles.subtitle}>{lastUpdate}</Text>
      </View>
      {children}
    </SafeAreaView>
  );
}

export function ScreenScroll({ children }: { children: ReactNode }) {
  return <ScrollView contentContainerStyle={styles.screen}>{children}</ScrollView>;
}

export function ScreenHeader({
  actionLabel,
  onAction,
  title
}: {
  actionLabel?: string;
  onAction?: () => void;
  title: string;
}) {
  const router = useRouter();

  return (
    <View style={styles.screenHeader}>
      <Pressable accessibilityRole="button" onPress={() => router.push("/")} style={styles.backButton}>
        <Text style={styles.backButtonText}>Home</Text>
      </Pressable>
      <Text style={styles.screenTitleCompact}>{title}</Text>
      {actionLabel && onAction ? (
        <Pressable accessibilityRole="button" onPress={onAction} style={styles.smallPrimaryButton}>
          <Text style={styles.smallPrimaryButtonText}>{actionLabel}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <View style={styles.emptyState}>
      <Text style={styles.emptyText}>{message}</Text>
    </View>
  );
}

export function ActionButton({
  disabled,
  label,
  onPress,
  variant = "primary"
}: {
  disabled?: boolean;
  label: string;
  onPress: () => void;
  variant?: "primary" | "secondary";
}) {
  return (
    <Pressable
      accessibilityRole="button"
      disabled={disabled}
      onPress={onPress}
      style={[
        styles.actionButton,
        variant === "secondary" && styles.secondaryActionButton,
        disabled && styles.disabledButton
      ]}
    >
      <Text
        style={[
          styles.actionButtonText,
          variant === "secondary" && styles.secondaryActionButtonText,
          disabled && styles.disabledButtonText
        ]}
      >
        {label}
      </Text>
    </Pressable>
  );
}

export const styles = StyleSheet.create({
  actionButton: {
    alignItems: "center",
    backgroundColor: "#008a6a",
    borderRadius: 8,
    minHeight: 52,
    justifyContent: "center",
    paddingHorizontal: 18,
    paddingVertical: 14,
    width: "100%"
  },
  actionButtonText: {
    color: "#ffffff",
    fontSize: 17,
    fontWeight: "700"
  },
  actionStack: {
    marginTop: 24,
    width: "100%"
  },
  backButton: {
    alignItems: "center",
    backgroundColor: "#e9f1ee",
    borderRadius: 8,
    minHeight: 40,
    justifyContent: "center",
    paddingHorizontal: 14,
    paddingVertical: 8
  },
  backButtonText: {
    color: "#234c42",
    fontSize: 14,
    fontWeight: "700"
  },
  disabledButton: {
    opacity: 0.45
  },
  disabledButtonText: {
    color: "#5f746e"
  },
  dashboardGroup: {
    borderColor: "#dbe7e3",
    borderRadius: 8,
    borderWidth: 1,
    marginTop: 16,
    padding: 14,
    width: "100%"
  },
  dashboardRowActions: {
    alignItems: "flex-end",
    marginLeft: 12,
    rowGap: 8
  },
  dashboardTotals: {
    columnGap: 8,
    flexDirection: "row",
    marginTop: 18,
    width: "100%"
  },
  emptyState: {
    alignItems: "center",
    borderColor: "#dbe7e3",
    borderRadius: 8,
    borderWidth: 1,
    marginTop: 20,
    padding: 20
  },
  emptyText: {
    color: "#536b64",
    fontSize: 15,
    textAlign: "center"
  },
  formShell: {
    flex: 1
  },
  fieldLabel: {
    color: "#142a24",
    fontSize: 14,
    fontWeight: "700",
    marginTop: 12
  },
  formPanel: {
    marginTop: 16,
    width: "100%"
  },
  formToolbar: {
    alignItems: "center",
    backgroundColor: "#f8fafc",
    borderBottomColor: "#d7dee8",
    borderBottomWidth: 1,
    flexDirection: "row",
    paddingHorizontal: 16,
    paddingVertical: 10
  },
  formToolbarTitle: {
    color: "#0f172a",
    flex: 1,
    fontSize: 16,
    fontWeight: "700",
    marginLeft: 12,
    marginRight: 12,
    width: "100%"
  },
  header: {
    borderBottomColor: "#d7dee8",
    borderBottomWidth: 1,
    padding: 16
  },
  invalidText: {
    color: "#9f3412",
    fontSize: 13,
    fontWeight: "700",
    marginTop: 6
  },
  pendingText: {
    color: "#7c5800",
    fontSize: 13,
    fontWeight: "700",
    marginTop: 6
  },
  progressFill: {
    backgroundColor: "#008a6a",
    borderRadius: 999,
    height: "100%"
  },
  progressTrack: {
    backgroundColor: "#dbe7e3",
    borderRadius: 999,
    height: 8,
    marginTop: 14,
    overflow: "hidden",
    width: "100%"
  },
  listItem: {
    alignItems: "center",
    backgroundColor: "#ffffff",
    borderColor: "#dbe7e3",
    borderRadius: 8,
    borderWidth: 1,
    flexDirection: "row",
    marginTop: 12,
    padding: 14
  },
  listItemAction: {
    color: "#008a6a",
    fontSize: 14,
    fontWeight: "800",
    marginLeft: 12
  },
  listItemActionLabel: {
    color: "#008a6a",
    fontSize: 12,
    fontWeight: "800",
    marginTop: 6
  },
  listItemId: {
    color: "#6b7d78",
    fontSize: 12,
    marginTop: 4
  },
  listItemMeta: {
    color: "#536b64",
    fontSize: 13,
    marginTop: 4
  },
  listItemText: {
    flex: 1
  },
  listItemTitle: {
    color: "#142a24",
    fontSize: 16,
    fontWeight: "800"
  },
  metricBox: {
    backgroundColor: "#eef6f3",
    borderRadius: 8,
    flex: 1,
    paddingHorizontal: 10,
    paddingVertical: 12
  },
  metricLabel: {
    color: "#536b64",
    fontSize: 12,
    fontWeight: "700",
    marginTop: 2
  },
  metricRow: {
    columnGap: 8,
    flexDirection: "row",
    marginTop: 12,
    width: "100%"
  },
  metricValue: {
    color: "#142a24",
    fontSize: 22,
    fontWeight: "800"
  },
  screen: {
    padding: 20
  },
  screenCopy: {
    color: "#536b64",
    fontSize: 16,
    lineHeight: 23,
    marginTop: 8,
    width: "100%"
  },
  screenHeader: {
    alignItems: "center",
    flexDirection: "row",
    width: "100%"
  },
  screenTitle: {
    color: "#0f172a",
    fontSize: 28,
    fontWeight: "800",
    width: "100%"
  },
  screenTitleCompact: {
    color: "#0f172a",
    flex: 1,
    fontSize: 22,
    fontWeight: "800",
    marginLeft: 10
  },
  secondaryActionButton: {
    backgroundColor: "#e9f1ee"
  },
  secondaryActionButtonText: {
    color: "#183d33"
  },
  shell: {
    backgroundColor: "#f8fafc",
    flex: 1
  },
  smallPrimaryButton: {
    alignItems: "center",
    backgroundColor: "#008a6a",
    borderRadius: 8,
    minHeight: 40,
    justifyContent: "center",
    paddingHorizontal: 12,
    paddingVertical: 8
  },
  smallPrimaryButtonText: {
    color: "#ffffff",
    fontSize: 13,
    fontWeight: "800"
  },
  statusPill: {
    backgroundColor: "#e9f1ee",
    borderRadius: 8,
    color: "#183d33",
    fontSize: 12,
    fontWeight: "800",
    marginLeft: 12,
    overflow: "hidden",
    paddingHorizontal: 10,
    paddingVertical: 6
  },
  statusPillFinal: {
    backgroundColor: "#dff5ed",
    color: "#007858"
  },
  statusPillPending: {
    backgroundColor: "#fff3d6",
    color: "#7c5800"
  },
  subtitle: {
    color: "#475569",
    fontSize: 13,
    marginTop: 4,
    width: "100%"
  },
  title: {
    color: "#0f172a",
    fontSize: 20,
    fontWeight: "700",
    width: "100%"
  },
  textInput: {
    backgroundColor: "#ffffff",
    borderColor: "#9fb4ad",
    borderRadius: 8,
    borderWidth: 1,
    color: "#142a24",
    fontSize: 16,
    minHeight: 46,
    marginTop: 6,
    paddingHorizontal: 12,
    paddingVertical: 9,
    width: "100%"
  },
  validText: {
    color: "#008a6a",
    fontSize: 13,
    fontWeight: "700",
    marginTop: 6
  }
});
