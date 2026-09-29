/** Shared screen chrome and controls. */
import type { ReactNode } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { ApiError } from "./api";
import { SessionRevokedError, SignInRequiredError } from "./auth";
import { t, type StringKey } from "./i18n";

export function Screen({ title, children, scroll = true }: { title: string; children: ReactNode; scroll?: boolean }) {
  const body = scroll ? <ScrollView contentContainerStyle={styles.body}>{children}</ScrollView> : children;
  return (
    <SafeAreaView style={styles.safe}>
      {__DEV__ ? <Text style={styles.debug}>{t("debugWarning")}</Text> : null}
      <Text style={styles.title} accessibilityRole="header">
        {title}
      </Text>
      {body}
    </SafeAreaView>
  );
}

export function Button({
  label,
  onPress,
  kind = "primary",
  disabled
}: {
  label: string;
  onPress: () => void;
  kind?: "primary" | "secondary" | "danger";
  disabled?: boolean;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: Boolean(disabled) }}
      disabled={disabled}
      onPress={onPress}
      style={[styles.button, styles[kind], disabled && styles.disabled]}
    >
      <Text style={kind === "secondary" ? styles.secondaryText : styles.buttonText}>{label}</Text>
    </Pressable>
  );
}

export function Row({ children }: { children: ReactNode }) {
  return <View style={styles.row}>{children}</View>;
}

export const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#f6f7f9" },
  body: { padding: 16, gap: 12 },
  debug: { backgroundColor: "#b45309", color: "#fff", padding: 6, textAlign: "center", fontWeight: "600" },
  title: { fontSize: 22, fontWeight: "700", paddingHorizontal: 16, paddingTop: 12, color: "#111827" },
  text: { fontSize: 16, color: "#1f2937" },
  muted: { fontSize: 14, color: "#6b7280" },
  error: { fontSize: 15, color: "#b91c1c" },
  input: {
    borderWidth: 1,
    borderColor: "#cbd5e1",
    borderRadius: 8,
    padding: 12,
    fontSize: 16,
    backgroundColor: "#fff",
    color: "#111827"
  },
  button: { borderRadius: 8, paddingVertical: 12, paddingHorizontal: 16, alignItems: "center" },
  primary: { backgroundColor: "#1d4ed8" },
  secondary: { backgroundColor: "#fff", borderWidth: 1, borderColor: "#cbd5e1" },
  danger: { backgroundColor: "#b91c1c" },
  disabled: { opacity: 0.5 },
  buttonText: { color: "#fff", fontSize: 16, fontWeight: "600" },
  secondaryText: { color: "#1f2937", fontSize: 16, fontWeight: "600" },
  row: { flexDirection: "row", gap: 8, alignItems: "center", flexWrap: "wrap" },
  card: { backgroundColor: "#fff", borderRadius: 8, padding: 12, borderWidth: 1, borderColor: "#e5e7eb", gap: 4 }
});

/** The UI string for an error from the device API; never shows server text or answers. */
export function errorText(error: unknown): string {
  if (error instanceof SessionRevokedError) return t("sessionRevoked");
  if (error instanceof SignInRequiredError) return t("signInAgain");
  if (error instanceof ApiError) {
    if (error.code === "enrolment_invalid") return t("errEnrolInvalid");
    if (error.code === "second_factor_required") return t("otpRequired");
    if (error.code === "no_interviewer_grant") return t("errNoGrant");
    if (error.code === "device_revoked") return t("errDeviceRevoked");
    if (error.status === 429) return t("errRateLimited");
    if (error.status === 401) return t("errSignIn");
    return t("errGeneric");
  }
  if (error instanceof TypeError) return t("errNetwork");
  return t("errGeneric");
}

/** A case state's UI label (the states a device holds), else the state code itself. */
export function stateLabel(state: string): string {
  const key = `state_${state}` as StringKey;
  const label = t(key);
  return label === key ? state : label;
}
