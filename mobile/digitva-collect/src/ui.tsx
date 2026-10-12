/** Shared screen chrome and controls. */
import type { ReactNode } from "react";
import { useMemo, useState } from "react";
import { Platform, Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions, type StyleProp, type ViewStyle } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { ApiError } from "./api";
import { SessionRevokedError, SignInRequiredError } from "./authErrors";
import { t, type StringKey } from "./i18n";
import { BUTTON_MIN_WIDTH, buttonTone, controls, fontSize, radius, spacing, typography, ui, useTheme, type ButtonSize, type ButtonVariant, type UiTokens } from "./theme";

/** Same phone breakpoint as the DORIS kit. */
const PHONE_BREAKPOINT = 768;

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

/** Legacy `kind` names of the queue and native routes, mapped onto the kit's variants. */
const KIND_VARIANT = { primary: "default", secondary: "outline", danger: "destructive" } as const;

/**
 * The app's one button: the DORIS kit's variants (default, secondary, outline, ghost, destructive) and sizes
 * (sm, default, icon), 40px high (44 on phones), 6px radius, 72px minimum width, 2px focus ring on the web.
 * `kind` stays as an alias of `variant` for existing callers.
 */
export function Button({
  label,
  onPress,
  kind,
  variant = kind ? KIND_VARIANT[kind] : "default",
  size = "default",
  disabled,
  loading = false,
  accessibilityLabel,
  expanded,
  style
}: {
  label: string;
  onPress: () => void;
  kind?: "primary" | "secondary" | "danger";
  variant?: ButtonVariant;
  size?: ButtonSize;
  disabled?: boolean;
  loading?: boolean;
  accessibilityLabel?: string;
  /** Set on a button that shows or hides a section, so screen readers hear its state. */
  expanded?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  const theme = useTheme();
  const [focused, setFocused] = useState(false);
  const height = useControlHeight();
  const disabledOrBusy = Boolean(disabled || loading);
  const tone = buttonTone(theme.ui, variant);
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityState={{ disabled: disabledOrBusy, busy: loading, expanded }}
      disabled={disabledOrBusy}
      hitSlop={spacing.xxs}
      onPress={onPress}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      style={({ pressed }) => [
        styles.button,
        { minHeight: height, backgroundColor: tone.bg, borderColor: tone.border, opacity: disabledOrBusy ? 0.5 : pressed ? 0.85 : 1 },
        size === "sm" && { paddingHorizontal: spacing.sm },
        size === "icon" && { minWidth: height, paddingHorizontal: 0 },
        focused && Platform.OS === "web" && ({ outlineStyle: "solid", outlineWidth: 2, outlineColor: theme.ui.ring, outlineOffset: 2 } as ViewStyle),
        style
      ]}
    >
      <Text style={[styles.buttonText, { color: tone.fg }]}>{loading ? t("loading") : label}</Text>
    </Pressable>
  );
}

/** 40px controls, 44px on phones (the minimum touch target). */
export function useControlHeight(): number {
  return useWindowDimensions().width < PHONE_BREAKPOINT ? controls.minTouchTarget : controls.minHeight;
}

export function Row({ children }: { children: ReactNode }) {
  return <View style={styles.row}>{children}</View>;
}

/** Every value is a `ui` token or a theme scale step (src/theme.ts): 40px (44 phone) controls, 6px control radius, 8px card radius, 16px card padding, 12px gaps. */
function createStyles(t: UiTokens, controlHeight: number = controls.minHeight) {
  return StyleSheet.create({
    safe: { flex: 1, backgroundColor: t.page },
    body: {
      padding: controls.screenPadding,
      gap: spacing.sm,
      width: "100%",
      maxWidth: controls.contentMaxWidth,
      alignSelf: "center"
    },
    fill: { flex: 1 },
    footer: { paddingHorizontal: controls.screenPadding, paddingVertical: spacing.xs, borderTopWidth: controls.borderWidth },
    frame: { flex: 1, flexDirection: "row", width: "100%", minWidth: 0, position: "relative" },
    mainColumn: { flex: 1, minWidth: 0 },
    mainScroll: { flex: 1, minWidth: 0 },
    debug: {
      backgroundColor: t.warningText,
      color: t.primaryForeground,
      padding: spacing.xs,
      minHeight: controlHeight,
      textAlign: "center",
      textAlignVertical: "center",
      fontWeight: "600"
    },
    title: {
      ...typography.title,
      color: t.foreground,
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
    titleBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm, paddingTop: spacing.sm },
    text: { ...typography.body, color: t.foreground, fontFamily: controls.fontFamily },
    headline: { ...typography.headline, color: t.foreground, fontFamily: controls.fontFamily },
    muted: { ...typography.subhead, color: t.mutedForeground, fontFamily: controls.fontFamily },
    error: { ...typography.subhead, color: t.destructiveText, fontFamily: controls.fontFamily },
    input: {
      borderWidth: 1,
      borderColor: t.input,
      borderRadius: radius.md,
      minHeight: controlHeight,
      paddingHorizontal: spacing.md,
      paddingVertical: spacing.xs,
      ...typography.body,
      backgroundColor: t.background,
      color: t.foreground,
      fontFamily: controls.fontFamily
    },
    phoneInputRow: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
    phonePrefix: { ...typography.body, color: t.foreground, fontFamily: controls.fontFamily, minWidth: 40 },
    phoneInput: { flex: 1 },
    authLinks: { gap: spacing.xs },
    button: {
      borderRadius: radius.md,
      borderWidth: 1,
      minHeight: controlHeight,
      minWidth: BUTTON_MIN_WIDTH,
      paddingVertical: spacing.xs,
      paddingHorizontal: spacing.lg,
      alignItems: "center",
      justifyContent: "center"
    },
    primary: { backgroundColor: t.primary },
    secondary: { backgroundColor: t.background, borderWidth: 1, borderColor: t.input },
    danger: { backgroundColor: t.destructive },
    disabled: { opacity: 0.5 },
    buttonText: { fontSize: fontSize.body, lineHeight: 20, fontWeight: "500", color: t.primaryForeground, fontFamily: controls.fontFamily },
    secondaryText: { fontSize: fontSize.body, lineHeight: 20, fontWeight: "500", color: t.foreground, fontFamily: controls.fontFamily },
    row: { flexDirection: "row", gap: spacing.xs, alignItems: "center", flexWrap: "wrap" },
    card: {
      backgroundColor: t.card,
      borderRadius: radius.lg,
      padding: controls.cardPadding,
      borderWidth: 1,
      borderColor: t.border,
      gap: controls.gap
    }
  });
}

/** Legacy static styles remain light-mode compatible for existing native routes. */
export const styles = createStyles(ui.light);

/** Use this hook when a screen needs styles that follow the selected UI theme. */
export function useUiStyles() {
  const theme = useTheme();
  const height = useControlHeight();
  return useMemo(() => createStyles(theme.ui, height), [theme.mode, height]);
}

/** The UI string for an error from the device API; never shows server text or answers. */
export function errorText(error: unknown): string {
  if (error instanceof SessionRevokedError) return t("sessionRevoked");
  if (error instanceof SignInRequiredError) return t("signInAgain");
  if (error instanceof ApiError) {
    if (error.code === "enrolment_invalid") return t("errEnrolInvalid");
    if (error.code === "cookie_session_required") return t("loginRequiredAction");
    if (error.code === "maintenance") return t("serverUnavailable");
    if (error.code === "forbidden" || error.code === "project_forbidden") return t("serverForbidden");
    if (error.code === "password_change_required" || error.code === "terms_required") return t("termsRequired");
    if (error.code === "no_interviewer_grant") return t("errNoGrant");
    if (error.code === "no_collection_access") return t("noCollectionAccess");
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
