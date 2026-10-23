/** Shared screen chrome and controls. */
import type { ReactNode } from "react";
import { useMemo, useState } from "react";
import { ActivityIndicator, Platform, Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions, type StyleProp, type ViewStyle } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { ApiError } from "./api";
import { APP_VERSION } from "./appVersion";
import { SessionRevokedError, SignInRequiredError } from "./authErrors";
import { describeError, recordError } from "./errorLog";
import { t, type StringKey } from "./i18n";
import { useShell } from "./nativeShell/shellContext";
import { BUTTON_MIN_WIDTH, buttonTone, controls, fontSize, radius, spacing, typography, ui, useTheme, type ButtonSize, type ButtonVariant, type UiTokens } from "./theme";

/** Same phone breakpoint as the DORIS kit. */
const PHONE_BREAKPOINT = 768;

export function Screen({
  title,
  children,
  scroll = true,
  sidebar,
  headerAction,
  footer,
  lead,
  variant = "standard",
  wide = false
}: {
  title: string;
  children: ReactNode;
  scroll?: boolean;
  sidebar?: ReactNode;
  headerAction?: ReactNode;
  footer?: ReactNode;
  /** With a sidebar and scroll: rendered full width at the top of the scroller, and the title row moves into the
   * scroller under it, so both scroll away with the page (the browser interview's header bar). */
  lead?: ReactNode;
  /** "immersive": no title bar, no dev banner, no padding or max width; `children` own the full height (the
   * interview and revision forms put their one compact top bar first). */
  variant?: "standard" | "immersive";
  /** Lift the 720px reading width so a table can use the whole page (the Users list). */
  wide?: boolean;
}) {
  const theme = useTheme();
  const screenStyles = useUiStyles();
  // The phone header and tabs pad the status and navigation bars themselves; Screen must not pad them again.
  const shell = useShell();
  const edges = (["top", "bottom", "left", "right"] as const).filter((edge) => !(edge === "top" && shell.header) && !(edge === "bottom" && shell.tabs));
  if (variant === "immersive") {
    return (
      <SafeAreaView style={[screenStyles.safe, { backgroundColor: theme.colors.background }]}>
        <View style={screenStyles.fill}>{children}</View>
        {footer ? <View style={[screenStyles.footer, { borderColor: theme.colors.border }]}>{footer}</View> : null}
      </SafeAreaView>
    );
  }
  const widen = wide ? { maxWidth: "100%" as const } : null;
  const titleNode = (
    <View style={[screenStyles.titleWrap, widen]}>
      <View style={screenStyles.titleBar}>
        <Text style={[screenStyles.title, { color: theme.colors.text }]} accessibilityRole="header">
          {title}
        </Text>
        {headerAction}
      </View>
    </View>
  );
  const body = sidebar ? (
    <View style={[screenStyles.frame, { backgroundColor: theme.colors.background }]}>
      {sidebar}
      <View style={screenStyles.mainColumn}>
        {lead && scroll ? (
          <ScrollView keyboardShouldPersistTaps="handled" style={screenStyles.mainScroll}>
            {lead}
            {titleNode}
            <View style={[screenStyles.body, widen, { backgroundColor: theme.colors.background }]}>{children}</View>
          </ScrollView>
        ) : (
          <>
            {titleNode}
            {scroll ? (
              <ScrollView keyboardShouldPersistTaps="handled" style={screenStyles.mainScroll} contentContainerStyle={[screenStyles.body, widen, { backgroundColor: theme.colors.background }]}>
                {children}
              </ScrollView>
            ) : (
              <View style={[screenStyles.body, widen, screenStyles.mainScroll, { backgroundColor: theme.colors.background }]}>
                {children}
              </View>
            )}
          </>
        )}
      </View>
    </View>
  ) : scroll ? (
    <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={[screenStyles.body, widen, { backgroundColor: theme.colors.background }]}>
      {children}
    </ScrollView>
  ) : (
    <View style={[screenStyles.body, widen, screenStyles.fill, { backgroundColor: theme.colors.background }]}>{children}</View>
  );
  return (
    <SafeAreaView edges={edges} style={[screenStyles.safe, { backgroundColor: theme.colors.background }]}>
      {__DEV__ ? (
        <Text
          style={[screenStyles.debug, { backgroundColor: theme.colors.warning, color: theme.colors.onAccent }]}
          accessibilityRole="alert"
        >
          {t("debugWarning")}
        </Text>
      ) : null}
      {!sidebar ? titleNode : null}
      {body}
      {footer ? <View style={[screenStyles.footer, { borderColor: theme.colors.border }]}>{footer}</View> : null}
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
      <Text style={[styles.buttonText, { color: tone.fg }]}>{label}</Text>
      {/* Absolute, so the button keeps its width while busy. */}
      {loading ? <ActivityIndicator size="small" color={tone.fg} style={styles.buttonSpinner} /> : null}
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

/** Every value is a `ui` token or a theme scale step (src/theme.ts): 40px (44 phone) controls, 6px control radius, 8px card radius, compact 12px/8px mobile padding/gaps. */
function createStyles(t: UiTokens, controlHeight: number = controls.minHeight, compact: boolean = false) {
  return StyleSheet.create({
    safe: { flex: 1, backgroundColor: t.page },
    body: {
      padding: compact ? spacing.sm : controls.screenPadding,
      gap: compact ? spacing.xs : spacing.sm,
      width: "100%",
      maxWidth: controls.contentMaxWidth,
      alignSelf: "center"
    },
    fill: { flex: 1 },
    footer: { paddingHorizontal: compact ? spacing.sm : controls.screenPadding, paddingVertical: spacing.xs, borderTopWidth: controls.borderWidth },
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
      paddingHorizontal: compact ? spacing.sm : controls.screenPadding,
      position: "relative",
      zIndex: 30,
      overflow: "visible"
    },
    titleBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm, paddingTop: compact ? spacing.xs : spacing.sm },
    text: { ...typography.body, color: t.foreground, fontFamily: controls.fontFamily },
    headline: { ...typography.headline, color: t.foreground, fontFamily: controls.fontFamily },
    /** A form question's label: larger and bolder than helper text so the questions lead. */
    fieldLabel: { ...typography.body, lineHeight: 22, fontWeight: "600" as const, color: t.foreground, fontFamily: controls.fontFamily },
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
    buttonSpinner: { position: "absolute", right: spacing.xs },
    disabled: { opacity: 0.5 },
    buttonText: { fontSize: fontSize.body, lineHeight: 20, fontWeight: "500", color: t.primaryForeground, fontFamily: controls.fontFamily },
    secondaryText: { fontSize: fontSize.body, lineHeight: 20, fontWeight: "500", color: t.foreground, fontFamily: controls.fontFamily },
    row: { flexDirection: "row", gap: spacing.xs, alignItems: "center", flexWrap: "wrap" },
    card: {
      backgroundColor: t.card,
      borderRadius: radius.lg,
      padding: compact ? spacing.sm : controls.cardPadding,
      borderWidth: 1,
      borderColor: t.border,
      gap: compact ? spacing.xs : controls.gap
    }
  });
}

/** Legacy static styles remain light-mode compatible for existing native routes. */
export const styles = createStyles(ui.light);

/** Use this hook when a screen needs styles that follow the selected UI theme. */
export function useUiStyles() {
  const theme = useTheme();
  const { width } = useWindowDimensions();
  const compact = width < PHONE_BREAKPOINT;
  const height = compact ? controls.minTouchTarget : controls.minHeight;
  return useMemo(() => createStyles(theme.ui, height, compact), [theme.mode, height, compact]);
}

/**
 * One support line for screenshots: what failed, when, on which build. Only status, machine code, masked
 * route, error class and a scrubbed message prefix; never tokens, server text, URLs, names or answers.
 */
export function errorReference(error: unknown): string {
  return `Ref: ${describeError(error)} · ${new Date().toISOString().slice(11, 16)}Z · v${APP_VERSION}`;
}

/** The UI string for an error from the device API; never shows server text or answers. */
export function errorText(error: unknown): string {
  recordError(describeError(error));
  if (error instanceof SessionRevokedError) return t(error.keptUnsent ? "accessRemovedKept" : "sessionRevoked");
  if (error instanceof SignInRequiredError) return t("signInAgain");
  if (error instanceof ApiError) {
    if (error.code === "enrolment_invalid") return t("errEnrolInvalid");
    if (error.code === "csrf_failed") return t("csrfRefreshed");
    if (error.code === "cookie_session_required") return t("loginRequiredAction");
    if (error.code === "maintenance") return t("serverUnavailable");
    if (error.code === "forbidden" || error.code === "project_forbidden") return t("serverForbidden");
    if (error.code === "password_change_required" || error.code === "terms_required") return t("termsRequired");
    if (error.code === "no_interviewer_grant") return t("errNoGrant");
    if (error.code === "no_collection_access") return t("noCollectionAccess");
    if (error.code === "device_revoked") return t("errDeviceRevoked");
    if (error.code === "demo_limit") return t("demoLimit");
    if (error.code === "cap_reached") return t("demoFull");
    if (error.status === 429) return t("errRateLimited");
    if (error.status === 401) return t("errSignIn");
    return `${t("errGeneric")}\n${errorReference(error)}`;
  }
  if (error instanceof TypeError) return t("errNetwork");
  return `${t("errGeneric")}\n${errorReference(error)}`;
}

/** A case state's UI label (the states a device holds), else the state code itself. */
export function stateLabel(state: string): string {
  const key = `state_${state}` as StringKey;
  const label = t(key);
  return label === key ? state : label;
}
