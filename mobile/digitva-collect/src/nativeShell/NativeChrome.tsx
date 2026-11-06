/**
 * The phone's header (48dp bar: emblem on tab roots or a back chevron and the screen title, sync chip, account)
 * and bottom tabs (56dp). Look follows docs/design/collect-petrol-theme: both bars are the canvas colour with a
 * hairline separator, ink title, primary chevron and icons; the active tab is primary with a semibold label,
 * the others muted. Both step aside by the rules in navAdapter.ts, and a tab tap never remounts a screen that is
 * already in the stack (navAdapter `tabMove`).
 */
import { useGlobalSearchParams, useNavigationContainerRef, usePathname, useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, BackHandler, Image, Modal, Platform, Pressable, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { BlurView } from "expo-blur";

import { useAppState } from "../AppState";
import DemoBadge from "../DemoBadge";
import { canTryDorisDemo } from "../dorisDemoAccess";
import { t } from "../i18n";
import { controlText, radius, spacing, typography, useTheme } from "../theme";
import { homeRoute } from "../standalone/home";
import { MenuChoiceRow } from "../ui/controls";
import { LANGUAGE_LIST_FROM, LanguageSheet, machineTranslated } from "../ui/LanguagePicker";
import { useUiLanguages } from "../uiPacks";
import { focusForAccessibility } from "../ui";
import { Icon, icons } from "../Icon";
import { useToastClearance } from "../toast";
import { activeNativeTab, isNativeTabRoot, isPreLoginRoute, nativeTabs, showNativeBackTitle, tabMove, type NativeTab } from "./navAdapter";
import { useShell, type SyncStatus } from "./shellContext";

const HEADER_HEIGHT = 48;
const TAB_HEIGHT = 56;

/**
 * Both bars' fill. iOS: frosted, a system chrome blur under a translucent canvas tint (README "Frosted bars on iOS
 * only"); the bars sit beside the Stack (app/_layout.tsx), so the blur samples the canvas, not scrolled content.
 * Android and the web: the opaque canvas, since blur drops frames on mid-range phones.
 */
function BarFill() {
  const { ui: tokens, mode } = useTheme();
  if (Platform.OS !== "ios") return null;
  return (
    <>
      <BlurView tint={mode === "dark" ? "systemChromeMaterialDark" : "systemChromeMaterialLight"} intensity={80} style={StyleSheet.absoluteFill} />
      {/* 80% canvas over the blur; `page` is a six-digit hex token. */}
      <View pointerEvents="none" style={[StyleSheet.absoluteFill, { backgroundColor: `${tokens.page}cc` }]} />
    </>
  );
}

const barBackground = (page: string) => (Platform.OS === "ios" ? "transparent" : page);

/** First letters of the first two words of the display name. */
export function initials(name: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((word) => Array.from(word)[0]?.toUpperCase() ?? "").join("") || "?";
}

/**
 * What the header shows about syncing: a spinner while it runs, "Offline" while the phone is offline, otherwise
 * nothing. The unsent count lives on the Sync tab, the Home card and the Sync sheet only.
 */
export function syncIndicator(sync: SyncStatus): { label: string; busy: boolean } | undefined {
  if (sync.busy) return { label: t("syncChipSyncing"), busy: true };
  if (sync.offline) return { label: t("syncChipOffline"), busy: false };
  return undefined;
}

/**
 * The app-language button (globe icon): opens a menu of the app languages (useUiLanguages) with the current one
 * ticked, so a stray tap never changes the language; from four languages, the shared list sheet instead. Used in the
 * pre-login header (signed in, the language is in the Account sheet).
 */
export function LanguageButton({ color }: { color: string }) {
  const { uiLocale, chooseUiLocale } = useAppState();
  const { ui: tokens } = useTheme();
  const insets = useSafeAreaInsets();
  const [open, setOpen] = useState(false);
  const languages = useUiLanguages();
  const current = languages.find((locale) => locale.code === uiLocale) ?? languages[0];
  const asSheet = languages.length >= LANGUAGE_LIST_FROM;
  const choose = (code: string) => {
    setOpen(false);
    if (code !== uiLocale) void chooseUiLocale(code);
  };
  return (
    <>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={t("appLanguageMenu", { language: current?.label ?? "" })}
        accessibilityState={{ expanded: open }}
        onPress={() => setOpen(true)}
        style={{ width: 48, height: 48, alignItems: "center", justifyContent: "center" }}
      >
        <Icon name={icons.language} color={color} size={24} />
      </Pressable>
      {asSheet ? <LanguageSheet visible={open} title={t("appLanguage")} languages={languages} value={uiLocale} onChoose={choose} onClose={() => setOpen(false)} /> : null}
      <Modal transparent visible={open && !asSheet} animationType="fade" onRequestClose={() => setOpen(false)}>
        <Pressable accessibilityRole="button" accessibilityLabel={t("cancel")} onPress={() => setOpen(false)} style={{ flex: 1 }}>
          <View
            accessibilityRole="menu"
            accessibilityLabel={t("appLanguage")}
            style={{ position: "absolute", top: insets.top + 52, right: spacing.sm, minWidth: 200, paddingVertical: spacing.xxs, borderRadius: radius.lg, borderWidth: 1, borderColor: tokens.border, backgroundColor: tokens.popover, elevation: 6 }}
          >
            <Text style={{ ...typography.caption, color: tokens.mutedForeground, paddingHorizontal: spacing.md, paddingVertical: spacing.xs }}>{t("appLanguage")}</Text>
            {languages.map((locale) => {
              const selected = locale.code === current?.code;
              return (
                <MenuChoiceRow key={locale.code} role="menuitem" label={locale.label} language={locale.language} detail={machineTranslated(locale) ? t("uiLanguageMachineTranslated") : undefined} selected={selected} onPress={() => choose(locale.code)} />
              );
            })}
          </View>
        </Pressable>
      </Modal>
    </>
  );
}

export function NativeHeader() {
  const shell = useShell();
  const { ready } = useAppState();
  return ready && shell.header ? <HeaderBar /> : null;
}

function HeaderBar() {
  const shell = useShell();
  const router = useRouter();
  const { accounts, device } = useAppState();
  const insets = useSafeAreaInsets();
  const account = accounts.find((item) => item.user_id === shell.userId);
  const chip = syncIndicator(shell.sync);
  const pathname = usePathname().replace(/\/$/, "") || "/";
  const preLogin = isPreLoginRoute(pathname);
  // Help and the language button live in the Account sheet once an account is open; without one (pre-login, or the accounts list
  // at `/`, which has no userId) the bar keeps them so the language and Help stay reachable.
  const noAccountMenu = preLogin || !account;
  // Unlock and PIN setup are pre-login routes, so these security gates never get an arrow.
  const back = showNativeBackTitle(pathname, account);
  const goBack = () => {
    if (router.canGoBack()) return router.back();
    // Opened with no history (a cold start or a replace): the account's Home, or the accounts list.
    router.replace(account ? { pathname: homeRoute(account) as never, params: { userId: account.user_id } } : "/");
  };
  const { ui: tokens } = useTheme();
  // A pushed screen's title is here, not on the page: the screen reader moves to it when the screen changes.
  const titleRef = useRef<Text>(null);
  const screenTitle = back ? shell.screenTitle : undefined;
  useEffect(() => {
    if (screenTitle) focusForAccessibility(titleRef.current);
  }, [screenTitle]);
  return (
    <View style={{ backgroundColor: barBackground(tokens.page), paddingTop: insets.top, borderBottomWidth: StyleSheet.hairlineWidth, borderColor: tokens.border }}>
      <BarFill />
      <View style={{ height: HEADER_HEIGHT, flexDirection: "row", alignItems: "center", gap: spacing.xs, paddingLeft: spacing.sm, paddingRight: spacing.xxs }}>
        {back ? (
          <>
            <Pressable accessibilityRole="button" accessibilityLabel={t("back")} onPress={goBack} style={{ width: 48, height: 48, marginLeft: -spacing.sm, alignItems: "center", justifyContent: "center" }}>
              <Icon name={icons.back} color={tokens.primary} size={22} />
            </Pressable>
            {/* The screen's title (Screen publishes it); one line, shrinking so the sync chip and account stay on the bar. */}
            <Text ref={titleRef} accessibilityRole="header" numberOfLines={1} ellipsizeMode="tail" style={{ ...typography.headline, color: tokens.foreground, flex: 1, flexShrink: 1 }}>
              {shell.screenTitle ?? ""}
            </Text>
          </>
        ) : (
          <>
            <Image source={require("../../assets/icon.png")} accessibilityLabel={t("appName")} style={{ width: 28, height: 28, borderRadius: 6, backgroundColor: tokens.card }} />
            <Text accessibilityRole="header" numberOfLines={1} style={{ ...typography.headline, color: tokens.foreground, flex: 1 }}>DigitVA</Text>
          </>
        )}
        <DemoBadge server={device?.server} />
        {account && chip && !preLogin ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={chip.label}
            onPress={() => shell.openSheet("sync")}
            hitSlop={{ top: 6, bottom: 6 }}
            style={{ height: 32, paddingHorizontal: spacing.sm, borderRadius: 16, backgroundColor: tokens.muted, flexDirection: "row", alignItems: "center", gap: spacing.xxs }}
          >
            {chip.busy ? <ActivityIndicator size="small" color={tokens.primary} /> : <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: tokens.warningBorder }} />}
            {chip.busy ? null : <Text style={{ ...typography.caption, color: tokens.foreground }}>{chip.label}</Text>}
          </Pressable>
        ) : null}
        {/* Signed in, Help and the language are in the Account sheet; before sign-in there is no sheet. */}
        {(preLogin ? canTryDorisDemo() : !account) ? (
          <Pressable accessibilityRole="button" accessibilityLabel={t("formHelp")} onPress={() => shell.openSheet("help")} style={{ width: 48, height: 48, alignItems: "center", justifyContent: "center" }}>
            <Icon name={icons.help} color={tokens.primary} size={24} />
          </Pressable>
        ) : null}
        {noAccountMenu ? <LanguageButton color={tokens.primary} /> : null}
        {account && !preLogin ? (
          <Pressable accessibilityRole="button" accessibilityLabel={t("accountMenu")} onPress={() => shell.openSheet("account")} style={{ width: 48, height: 48, alignItems: "center", justifyContent: "center" }}>
            <View style={{ width: 32, height: 32, borderRadius: 16, backgroundColor: tokens.accent, alignItems: "center", justifyContent: "center" }}>
              <Text style={{ ...typography.caption, fontWeight: "700", color: tokens.accentForeground }}>{initials(account.name)}</Text>
            </View>
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}

export function NativeTabs() {
  const shell = useShell();
  return shell.tabs && shell.userId ? <TabBar /> : null;
}

function TabBar() {
  const shell = useShell();
  const router = useRouter();
  const navigation = useNavigationContainerRef();
  const pathname = usePathname().replace(/\/$/, "") || "/";
  const params = useGlobalSearchParams<{ view?: string | string[] }>();
  const { accounts } = useAppState();
  const { ui: tokens } = useTheme();
  const insets = useSafeAreaInsets();
  const account = accounts.find((item) => item.user_id === shell.userId);
  const tabs = nativeTabs(account);
  const active = activeNativeTab(pathname, params);
  const atTabRoot = isNativeTabRoot(pathname, account);
  useToastClearance(TAB_HEIGHT + insets.bottom);
  const open = (tab: NativeTab) => {
    if (!tab.route) return shell.openSheet("sync");
    if (tab.key === active) return;
    const stack = (navigation.isReady() ? navigation.getRootState()?.routes : undefined)?.map((route) => route.name) ?? [];
    router[tabMove(tab, tabs[0].route!, stack, atTabRoot)]({ pathname: tab.route as never, params: { userId: shell.userId, ...tab.params } });
  };
  // Android Back on a tab root other than Home goes Home, as the Home tab would; Home and pushed screens keep the
  // Stack's Back (Home leaves the app or returns to the accounts list). One listener per tab root, not per render.
  const goHome = useRef(() => open(tabs[0]));
  goHome.current = () => open(tabs[0]);
  const backGoesHome = active !== undefined && active !== "home" && atTabRoot;
  useEffect(() => {
    if (!backGoesHome) return;
    const subscription = BackHandler.addEventListener("hardwareBackPress", () => {
      goHome.current();
      return true;
    });
    return () => subscription.remove();
  }, [backGoesHome]);
  return (
    <View accessibilityRole="tablist" style={{ flexDirection: "row", height: TAB_HEIGHT + insets.bottom, paddingBottom: insets.bottom, backgroundColor: barBackground(tokens.page), borderTopWidth: StyleSheet.hairlineWidth, borderColor: tokens.border }}>
      <BarFill />
      {tabs.map((tab) => {
        const on = tab.key === active;
        const color = on ? tokens.primary : tokens.mutedForeground;
        const badge = tab.key === "sync" && shell.sync.work?.unsent ? shell.sync.work.unsent : 0;
        return (
          <Pressable
            key={tab.key}
            accessibilityRole="tab"
            accessibilityLabel={badge ? `${t(tab.labelKey)}, ${t("syncChipUnsent", { count: badge })}` : t(tab.labelKey)}
            accessibilityState={{ selected: on }}
            onPress={() => open(tab)}
            style={{ flex: 1, alignItems: "center", justifyContent: "center", gap: 2 }}
          >
            {/* The badge hangs off the icon's top-right corner with a ring in the bar tone; drawn over the middle of the
                tab it covered the Sync arrows, which read as a clipped glyph. */}
            <View>
              <Icon name={icons[tab.key]} color={color} size={24} />
              {badge ? (
                <View style={{ position: "absolute", top: -7, left: 14, minWidth: 20, height: 20, borderRadius: radius.full, paddingHorizontal: 4, borderWidth: 2, borderColor: tokens.page, backgroundColor: tokens.attention, alignItems: "center", justifyContent: "center" }}>
                  {/* Amber only as a filled badge with ink text; red is for errors. */}
                  <Text style={{ fontSize: typography.caption.fontSize, lineHeight: 14, fontWeight: "700", color: tokens.onAttention }}>{badge > 99 ? "99+" : badge}</Text>
                </View>
              ) : null}
            </View>
            <Text numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.92} maxFontSizeMultiplier={1.2} style={{ ...typography.caption, ...controlText, lineHeight: 18, alignSelf: "stretch", paddingHorizontal: 2, fontWeight: on ? "600" : "400", color }}>{t(tab.labelKey)}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}
