import { usePathname, useRouter } from "expo-router";
import { useEffect, useId, useRef, useState } from "react";
import { Image, Platform, Pressable, StyleSheet, Text, View, useWindowDimensions, type ViewProps } from "react-native";

import { useAppState } from "../AppState";
import { ClientApiError } from "../client/api";
import { t, UI_LOCALES } from "../i18n";
import { useTheme } from "../theme";
import { Button, Screen, useUiStyles } from "../ui";
import { loginRecoveryUrl } from "./loginRecovery";

const DESKTOP_BREAKPOINT = 900;
const RAIL_WIDTH = 56;
const SIDEBAR_WIDTH = 240;

export function browserErrorText(error: unknown): string {
  if (error instanceof ClientApiError) {
    if (error.code === "unauthorized" || error.status === 401) return t("serverUnauthorized");
    if (error.code === "terms_required" || error.code === "factor_setup_required") return t("loginRequiredAction");
    if (error.status === 403) return t("serverForbidden");
    if (error.status === 422 || error.status === 400) return t("serverValidation");
    if (error.status >= 500) return t("serverUnavailable");
    return t("serverError");
  }
  if (error instanceof TypeError) return t("errNetwork");
  return t("serverError");
}

export function UiLanguageSwitcher() {
  const instanceId = useId();
  const anchorId = `ui-language-menu-${instanceId}`;
  const triggerId = `ui-language-trigger-${instanceId}`;
  const { uiLocale, chooseUiLocale } = useAppState();
  const theme = useTheme();
  const [open, setOpen] = useState(false);
  const wasOpen = useRef(false);

  useEffect(() => {
    if (wasOpen.current && !open && typeof document !== "undefined") {
      document.getElementById(triggerId)?.focus();
    }
    wasOpen.current = open;
  }, [open, triggerId]);

  useEffect(() => {
    if (!open || typeof document === "undefined") return undefined;
    const closeOnEscapeOrOutside = (event: KeyboardEvent | PointerEvent) => {
      if (event instanceof KeyboardEvent) {
        if (event.key === "Escape") setOpen(false);
        return;
      }
      const root = document.getElementById(anchorId);
      if (root && event.target instanceof Node && !root.contains(event.target)) setOpen(false);
    };
    document.addEventListener("keydown", closeOnEscapeOrOutside);
    document.addEventListener("pointerdown", closeOnEscapeOrOutside);
    return () => {
      document.removeEventListener("keydown", closeOnEscapeOrOutside);
      document.removeEventListener("pointerdown", closeOnEscapeOrOutside);
    };
  }, [open, anchorId]);

  const options = UI_LOCALES;
  async function selectLocale(code: string) {
    await chooseUiLocale(code);
    setOpen(false);
  }

  return (
    <View nativeID={anchorId} style={languageStyles.anchor}>
      <Pressable
        nativeID={triggerId}
        accessibilityRole="button"
        accessibilityLabel={t("appLanguage")}
        accessibilityHint={options.find((option) => option.code === uiLocale)?.label ?? uiLocale}
        accessibilityState={{ expanded: open }}
        aria-expanded={open}
        onPress={() => setOpen((current) => !current)}
        style={({ pressed }) => [
          languageStyles.trigger,
          { backgroundColor: theme.colors.surface, borderColor: theme.colors.border, opacity: pressed ? 0.78 : 1 }
        ]}
      >
        <Text style={[languageStyles.triggerText, { color: theme.colors.text }]}>文A</Text>
      </Pressable>
      {open ? (
        <View
          accessibilityRole="radiogroup"
          accessibilityLabel={t("appLanguage")}
          style={[languageStyles.popover, { backgroundColor: theme.colors.surface, borderColor: theme.colors.border }]}
        >
          {options.map((option) => {
            const selected = option.code === uiLocale;
            return (
              <Pressable
                key={option.code}
                accessibilityRole="radio"
                accessibilityLabel={option.label}
                accessibilityState={{ checked: selected }}
                aria-checked={selected}
                onPress={() => void selectLocale(option.code)}
                style={({ pressed }) => [
                  languageStyles.option,
                  { backgroundColor: selected ? theme.colors.accentSoft : "transparent", opacity: pressed ? 0.78 : 1 }
                ]}
              >
                <Text style={[languageStyles.optionLabel, { color: theme.colors.text }]}>{option.label}</Text>
                <Text style={[languageStyles.check, { color: theme.colors.accent }]}>{selected ? "✓" : ""}</Text>
              </Pressable>
            );
          })}
        </View>
      ) : null}
    </View>
  );
}

export function LoginLanding() {
  const { loginUrl, actionCode, error, reload } = useAppState();
  const styles = useUiStyles();
  const login = loginRecoveryUrl(loginUrl, actionCode);
  return (
    <Screen title={t("loginTitle")} headerAction={<UiLanguageSwitcher />}>
      <View style={[styles.card, { padding: 24, marginTop: 8 }]}>
        <Text style={styles.headline}>{t("appName")}</Text>
        <Text style={styles.text}>{t("loginSubtitle")}</Text>
        {actionCode ? <Text style={styles.error} accessibilityRole="alert">{t("loginRequiredAction")}</Text> : null}
        {error && !actionCode ? <Text style={styles.error} accessibilityRole="alert">{t("serverUnavailable")}</Text> : null}
        {actionCode ? <Button label={t("continueSignIn")} onPress={() => window.location.assign(login)} /> : null}
        {error && !actionCode ? <Button kind="secondary" label={t("retry")} onPress={() => void reload()} /> : null}
        {!error && !actionCode ? <Button label={t("continueSignIn")} onPress={() => window.location.assign(login)} /> : null}
        <Text style={styles.muted}>{t("loginHelp")}</Text>
      </View>
    </Screen>
  );
}

type NavigationItem = {
  key: string;
  label: string;
  icon: string;
  route?: string;
  action: () => void;
};

function activeRoute(pathname: string, route: string): boolean {
  return pathname === route || pathname.startsWith(route + "/");
}

function NavigationLink({
  item,
  active,
  compact,
  onPress
}: {
  item: NavigationItem;
  active: boolean;
  compact: boolean;
  onPress: () => void;
}) {
  const theme = useTheme();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={item.label}
      accessibilityHint={active ? t("active") : undefined}
      accessibilityState={{ selected: active }}
      onPress={onPress}
      style={({ pressed }) => [
        navigationStyles.link,
        compact && navigationStyles.compactLink,
        {
          backgroundColor: active ? theme.colors.accentSoft : "transparent",
          borderColor: active ? theme.colors.focus : "transparent",
          opacity: pressed ? 0.78 : 1
        }
      ]}
    >
      <Text style={[navigationStyles.icon, { color: active ? theme.colors.accent : theme.colors.text }]}>{item.icon}</Text>
      {!compact ? <Text style={[navigationStyles.linkText, { color: theme.colors.text }]}>{item.label}</Text> : null}
    </Pressable>
  );
}

function NavigationMenu({ beforeNavigate }: { beforeNavigate?: () => Promise<boolean> }) {
  const router = useRouter();
  const pathname = usePathname();
  const { width } = useWindowDimensions();
  const { bootstrap, logout } = useAppState();
  const theme = useTheme();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const wide = width >= DESKTOP_BREAKPOINT;
  const navigationLandmarkProps = Platform.OS === "web"
    ? ({ role: "navigation", "aria-label": t("menuLabel") } as unknown as ViewProps)
    : { accessibilityLabel: t("menuLabel") };
  const drawerDialogProps = Platform.OS === "web"
    ? ({ role: "dialog", "aria-modal": true, "aria-label": t("menuLabel") } as unknown as ViewProps)
    : { accessibilityLabel: t("menuLabel"), accessibilityViewIsModal: true };

  useEffect(() => {
    if (wide) setDrawerOpen(false);
  }, [wide]);

  useEffect(() => {
    if (!drawerOpen || wide || typeof window === "undefined") return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDrawerOpen(false);
      if (event.key !== "Tab" || typeof document === "undefined") return;
      const drawer = document.getElementById("digitva-navigation-drawer");
      const focusable = drawer?.querySelectorAll<HTMLElement>("button, a, [tabindex]:not([tabindex='-1'])");
      if (!focusable?.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [drawerOpen, wide]);

  useEffect(() => {
    if (typeof document === "undefined") return;
    if (drawerOpen && !wide) {
      document.getElementById("digitva-navigation-close")?.focus();
    } else if (!drawerOpen && !wide) {
      document.getElementById("digitva-navigation-trigger")?.focus();
    }
  }, [drawerOpen, wide]);

  if (!bootstrap) return null;

  const { capabilities } = bootstrap;
  const items: NavigationItem[] = [];
  if (capabilities.intake) {
    items.push({ key: "collection", label: t("reportedDeaths"), icon: "☷", route: "/collection", action: () => router.push("/collection") });
  }
  const settings: NavigationItem = {
    key: "settings",
    label: t("navSettings"),
    icon: "⚙",
    route: "/settings",
    action: () => router.push("/settings")
  };

  async function navigate(action: () => void) {
    if (beforeNavigate && !(await beforeNavigate())) return;
    setDrawerOpen(false);
    action();
  }

  async function signOut() {
    if (beforeNavigate && !(await beforeNavigate())) return;
    setDrawerOpen(false);
    await logout?.();
  }

  const linksFor = (compact: boolean) => (
    <>
      <View style={navigationStyles.linkList}>
        {items.map((item) => (
          <NavigationLink
            key={item.key}
            item={item}
            compact={compact}
            active={item.route ? activeRoute(pathname, item.route) : false}
            onPress={() => void navigate(item.action)}
          />
        ))}
      </View>
      <View style={[navigationStyles.divider, { backgroundColor: theme.colors.border }]} />
      <NavigationLink
        item={settings}
        compact={compact}
        active={activeRoute(pathname, settings.route!)}
        onPress={() => void navigate(settings.action)}
      />
    </>
  );

  const signOutItem: NavigationItem = { key: "signOut", label: t("signOut"), icon: "↪", action: () => void signOut() };
  const menuBody = (
    <>
      <View style={navigationStyles.brand} accessibilityRole="header" accessibilityLabel={t("appName")}>
        <Image
          source={{ uri: "/static/digitva_logo.png" }}
          accessibilityLabel={t("appName")}
          resizeMode="contain"
          style={navigationStyles.brandLogo}
        />
      </View>
      <Text style={[navigationStyles.user, { color: theme.colors.textMuted }]} numberOfLines={2}>{bootstrap.user.name}</Text>
      {linksFor(false)}
      <View style={navigationStyles.spacer} />
      <NavigationLink item={signOutItem} compact={false} active={false} onPress={signOutItem.action} />
    </>
  );

  const railBody = (
    <>
      <Pressable
        nativeID="digitva-navigation-trigger"
        accessibilityRole="button"
        accessibilityLabel={t("openMenu")}
        accessibilityHint={t("menuLabel")}
        accessibilityState={{ expanded: drawerOpen }}
        onPress={() => setDrawerOpen(true)}
        style={({ pressed }) => [navigationStyles.menuButton, { borderColor: theme.colors.border, opacity: pressed ? 0.78 : 1 }]}
      >
        <Text style={[navigationStyles.menuIcon, { color: theme.colors.text }]}>☰</Text>
      </Pressable>
      {linksFor(true)}
      <View style={navigationStyles.spacer} />
      <NavigationLink item={signOutItem} compact active={false} onPress={signOutItem.action} />
    </>
  );

  return (
    <>
      {wide ? (
        <View {...navigationLandmarkProps} style={[navigationStyles.sidebar, { backgroundColor: theme.colors.surface, borderRightColor: theme.colors.border }]}>
          {menuBody}
        </View>
      ) : (
        <View {...navigationLandmarkProps} style={[navigationStyles.rail, { backgroundColor: theme.colors.surface, borderRightColor: theme.colors.border }]}>
          {railBody}
        </View>
      )}
      {!wide && drawerOpen ? (
        <View style={navigationStyles.drawerLayer} accessibilityViewIsModal>
          <Pressable accessibilityRole="button" accessibilityLabel={t("closeMenu")} onPress={() => setDrawerOpen(false)} style={navigationStyles.scrim} />
          <View nativeID="digitva-navigation-drawer" {...drawerDialogProps} style={[navigationStyles.drawer, { backgroundColor: theme.colors.surface, borderRightColor: theme.colors.border }]}>
            <View style={navigationStyles.drawerHeader}>
              <Text style={[navigationStyles.drawerTitle, { color: theme.colors.text }]}>{t("menuLabel")}</Text>
              <Pressable nativeID="digitva-navigation-close" accessibilityRole="button" accessibilityLabel={t("closeMenu")} onPress={() => setDrawerOpen(false)} style={[navigationStyles.closeButton, { borderColor: theme.colors.border }]}>
                <Text style={[navigationStyles.closeIcon, { color: theme.colors.text }]}>×</Text>
              </Pressable>
            </View>
            {menuBody}
          </View>
        </View>
      ) : null}
    </>
  );
}

export function WebShell({
  title,
  children,
  beforeNavigate,
  headerAction,
  footer
}: {
  title: string;
  children: React.ReactNode;
  beforeNavigate?: () => Promise<boolean>;
  headerAction?: React.ReactNode;
  footer?: React.ReactNode;
}) {
  const { bootstrap, ready } = useAppState();
  const uiStyles = useUiStyles();
  if (!ready) return <Screen title={t("appName")}><Text style={uiStyles.muted}>{t("loading")}</Text></Screen>;
  if (!bootstrap) return <LoginLanding />;
  const resolvedHeaderAction = headerAction === undefined ? <UiLanguageSwitcher /> : headerAction;
  return (
    <Screen title={title} sidebar={<NavigationMenu beforeNavigate={beforeNavigate} />} headerAction={resolvedHeaderAction} footer={footer}>
      {children}
    </Screen>
  );
}

const navigationStyles = StyleSheet.create({
  sidebar: {
    width: SIDEBAR_WIDTH,
    flexShrink: 0,
    padding: 16,
    borderRightWidth: 1,
    gap: 8
  },
  rail: {
    width: RAIL_WIDTH,
    flexShrink: 0,
    paddingVertical: 8,
    paddingHorizontal: 4,
    alignItems: "center",
    borderRightWidth: 1,
    gap: 8
  },
  brand: { minHeight: 68, justifyContent: "center", paddingBottom: 8 },
  brandLogo: { width: 208, height: 68 },
  user: { fontSize: 14, lineHeight: 20, paddingBottom: 8 },
  linkList: { gap: 8 },
  link: { minHeight: 48, borderWidth: 1, borderRadius: 12, paddingHorizontal: 12, flexDirection: "row", alignItems: "center", gap: 10 },
  compactLink: { width: 48, paddingHorizontal: 0, justifyContent: "center" },
  icon: { width: 22, textAlign: "center", fontSize: 18, fontWeight: "700" },
  linkText: { fontSize: 16, fontWeight: "600", flexShrink: 1 },
  spacer: { flex: 1 },
  divider: { height: 1, marginVertical: 4 },
  menuButton: { width: 48, minHeight: 48, borderWidth: 1, borderRadius: 12, alignItems: "center", justifyContent: "center" },
  menuIcon: { fontSize: 22, lineHeight: 26 },
  drawerLayer: { position: "absolute", left: 0, right: 0, top: 0, bottom: 0, zIndex: 10, flexDirection: "row" },
  scrim: { position: "absolute", left: 0, right: 0, top: 0, bottom: 0, backgroundColor: "rgba(0,0,0,0.45)" },
  drawer: { width: 280, maxWidth: "85%", height: "100%", padding: 16, borderRightWidth: 1, gap: 8, zIndex: 11 },
  drawerHeader: { minHeight: 48, flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  drawerTitle: { fontSize: 18, fontWeight: "700", flexShrink: 1 },
  closeButton: { width: 48, minHeight: 48, borderWidth: 1, borderRadius: 12, alignItems: "center", justifyContent: "center" },
  closeIcon: { fontSize: 28, lineHeight: 32 }
});

const languageStyles = StyleSheet.create({
  anchor: { position: "relative", zIndex: 20 },
  trigger: { minWidth: 48, minHeight: 48, borderWidth: 1, borderRadius: 12, alignItems: "center", justifyContent: "center" },
  triggerText: { fontSize: 17, fontWeight: "700" },
  popover: { position: "absolute", right: 0, top: 56, minWidth: 192, padding: 8, borderWidth: 1, borderRadius: 12, gap: 4, zIndex: 21, shadowColor: "#000", shadowOpacity: 0.16, shadowRadius: 8, shadowOffset: { width: 0, height: 3 }, elevation: 4 },
  option: { minHeight: 48, borderRadius: 8, paddingHorizontal: 12, flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 16 },
  optionLabel: { fontSize: 16, lineHeight: 22, flexShrink: 1 },
  check: { width: 20, fontSize: 18, fontWeight: "700", textAlign: "center" }
});
