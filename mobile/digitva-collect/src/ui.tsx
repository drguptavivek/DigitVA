/** Shared screen chrome and controls. */
import type { ReactNode } from "react";
import { useMemo, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View, type StyleProp, type ViewStyle } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { ApiError } from "./api";
import { SessionRevokedError, SignInRequiredError } from "./authErrors";
import { t, type StringKey } from "./i18n";
import { controls, palette, radius, spacing, typography, useTheme } from "./theme";

export function Screen({
  title,
  children,
  scroll = true,
  sidebar,
  headerAction,
  footer
}: {
  title: string;
  children: ReactNode;
  scroll?: boolean;
  sidebar?: ReactNode;
  headerAction?: ReactNode;
  footer?: ReactNode;
}) {
  const theme = useTheme();
  const titleNode = (
    <View style={styles.titleWrap}>
      <View style={styles.titleBar}>
        <Text style={[styles.title, { color: theme.colors.text }]} accessibilityRole="header">
          {title}
        </Text>
        {headerAction}
      </View>
    </View>
  );
  const body = sidebar ? (
    <View style={[styles.frame, { backgroundColor: theme.colors.background }]}>
      {sidebar}
      <View style={styles.mainColumn}>
        {titleNode}
        {scroll ? (
          <ScrollView style={styles.mainScroll} contentContainerStyle={[styles.body, { backgroundColor: theme.colors.background }]}>
            {children}
          </ScrollView>
        ) : (
          <View style={[styles.body, styles.mainScroll, { backgroundColor: theme.colors.background }]}>
            {children}
          </View>
        )}
      </View>
    </View>
  ) : scroll ? (
    <ScrollView contentContainerStyle={[styles.body, { backgroundColor: theme.colors.background }]}>
      {children}
    </ScrollView>
  ) : (
    <View style={[styles.body, styles.fill, { backgroundColor: theme.colors.background }]}>{children}</View>
  );
  return (
    <SafeAreaView style={[styles.safe, { backgroundColor: theme.colors.background }]}>
      {__DEV__ ? (
        <Text
          style={[styles.debug, { backgroundColor: theme.colors.warning, color: theme.colors.onAccent }]}
          accessibilityRole="alert"
        >
          {t("debugWarning")}
        </Text>
      ) : null}
      {!sidebar ? titleNode : null}
      {body}
      {footer ? <View style={[styles.footer, { borderColor: theme.colors.border }]}>{footer}</View> : null}
    </SafeAreaView>
  );
}

export function Button({
  label,
  onPress,
  kind = "primary",
  disabled,
  loading = false,
  accessibilityLabel,
  style
}: {
  label: string;
  onPress: () => void;
  kind?: "primary" | "secondary" | "danger";
  disabled?: boolean;
  loading?: boolean;
  accessibilityLabel?: string;
  style?: StyleProp<ViewStyle>;
}) {
  const theme = useTheme();
  const [focused, setFocused] = useState(false);
  const disabledOrBusy = Boolean(disabled || loading);
  const colors = theme.colors;
  const buttonColor = kind === "danger" ? colors.danger : kind === "secondary" ? colors.surface : colors.accent;
  const textColor = kind === "secondary" ? colors.text : kind === "danger" ? colors.onAccent : colors.onAccent;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityState={{ disabled: disabledOrBusy, busy: loading }}
      disabled={disabledOrBusy}
      onPress={onPress}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      style={({ pressed }) => [
        styles.button,
        {
          backgroundColor: buttonColor,
          borderColor: kind === "secondary" ? colors.border : buttonColor,
          opacity: disabledOrBusy ? 0.5 : pressed ? 0.78 : 1
        },
        focused && { borderColor: colors.focus, borderWidth: 2 },
        style
      ]}
    >
      <Text style={[styles.buttonText, { color: textColor }]}>{loading ? t("loading") : label}</Text>
    </Pressable>
  );
}

export function Row({ children }: { children: ReactNode }) {
  return <View style={styles.row}>{children}</View>;
}

function createStyles(colors: (typeof palette)["light"] | (typeof palette)["dark"]) {
  return StyleSheet.create({
    safe: { flex: 1, backgroundColor: colors.background },
    body: {
      padding: controls.screenPadding,
      gap: spacing.sm,
      width: "100%",
      maxWidth: controls.contentMaxWidth,
      alignSelf: "center"
    },
    fill: { flex: 1 },
    footer: { paddingHorizontal: controls.screenPadding, paddingVertical: spacing.xs, borderTopWidth: 1 },
    frame: { flex: 1, flexDirection: "row", width: "100%", minWidth: 0, position: "relative" },
    mainColumn: { flex: 1, minWidth: 0 },
    mainScroll: { flex: 1, minWidth: 0 },
    debug: {
      backgroundColor: colors.warning,
      color: colors.onAccent,
      padding: spacing.xs,
      minHeight: controls.minHeight,
      textAlign: "center",
      textAlignVertical: "center",
      fontWeight: "600"
    },
    title: {
      ...typography.title,
      paddingTop: spacing.sm,
      color: colors.text,
      fontFamily: controls.fontFamily
    },
    titleWrap: {
      width: "100%",
      maxWidth: controls.contentMaxWidth,
      alignSelf: "center",
      paddingHorizontal: controls.screenPadding,
      position: "relative",
      zIndex: 30,
      overflow: "visible"
    },
    titleBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm },
    text: { ...typography.body, color: colors.text, fontFamily: controls.fontFamily },
    headline: { ...typography.headline, color: colors.text, fontFamily: controls.fontFamily },
    muted: { ...typography.subhead, color: colors.textMuted, fontFamily: controls.fontFamily },
    error: { ...typography.subhead, color: colors.danger, fontFamily: controls.fontFamily },
    input: {
      borderWidth: 1,
      borderColor: colors.border,
      borderRadius: radius.md,
      minHeight: controls.minHeight,
      paddingHorizontal: spacing.md,
      paddingVertical: spacing.xs,
      ...typography.body,
      backgroundColor: colors.surface,
      color: colors.text,
      fontFamily: controls.fontFamily
    },
    phoneInputRow: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
    phonePrefix: { ...typography.body, color: colors.text, fontFamily: controls.fontFamily, minWidth: 40 },
    phoneInput: { flex: 1 },
    authLinks: { gap: spacing.xs },
    button: {
      borderRadius: radius.md,
      borderWidth: 1,
      minHeight: controls.minHeight,
      paddingVertical: spacing.xs,
      paddingHorizontal: spacing.md,
      alignItems: "center",
      justifyContent: "center"
    },
    primary: { backgroundColor: colors.accent },
    secondary: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
    danger: { backgroundColor: colors.danger },
    disabled: { opacity: 0.5 },
    buttonText: { ...typography.headline, color: colors.onAccent, fontFamily: controls.fontFamily },
    secondaryText: { ...typography.headline, color: colors.text, fontFamily: controls.fontFamily },
    row: { flexDirection: "row", gap: spacing.xs, alignItems: "center", flexWrap: "wrap" },
    card: {
      backgroundColor: colors.surface,
      borderRadius: radius.md,
      padding: spacing.sm,
      borderWidth: 1,
      borderColor: colors.border,
      gap: spacing.xxs
    }
  });
}

/** Legacy static styles remain light-mode compatible for existing native routes. */
export const styles = createStyles(palette.light);

/** Use this hook when a screen needs styles that follow the selected UI theme. */
export function useUiStyles() {
  const theme = useTheme();
  return useMemo(() => createStyles(theme.colors), [theme.mode]);
}

/** The UI string for an error from the device API; never shows server text or answers. */
export function errorText(error: unknown): string {
  if (error instanceof SessionRevokedError) return t("sessionRevoked");
  if (error instanceof SignInRequiredError) return t("signInAgain");
  if (error instanceof ApiError) {
    if (error.code === "enrolment_invalid") return t("errEnrolInvalid");
    if (error.code === "second_factor_required") return t("otpRequired");
    if (error.code === "factor_setup_required" || error.code === "cookie_session_required") return t("loginRequiredAction");
    if (error.code === "maintenance") return t("serverUnavailable");
    if (error.code === "forbidden" || error.code === "project_forbidden") return t("serverForbidden");
    if (error.code === "password_change_required" || error.code === "terms_required") return t("termsRequired");
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
