/**
 * The phone's header (48dp brand bar: emblem, sync chip, Help, account) and bottom tabs (56dp, 3px active
 * indicator). Look follows the browser shell (src/web/AppHeader.web.tsx): brand blue with white text in both
 * colour modes. Both step aside by the rules in navAdapter.ts.
 */
import { useGlobalSearchParams, usePathname, useRouter } from "expo-router";
import { ActivityIndicator, Image, Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import Svg, { Path } from "react-native-svg";

import { useAppState } from "../AppState";
import DemoBadge from "../DemoBadge";
import { t, UI_LOCALES } from "../i18n";
import { controlText, spacing, typography, ui, useTheme } from "../theme";
import { activeNativeTab, isPreLoginRoute, nativeTabs, type NativeTab } from "./navAdapter";
import { useShell, type SyncStatus } from "./shellContext";

// Brand blue with white text in both colour modes, like the browser strip (AppHeader.web.tsx).
const bar = () => ui.light.primary;
const onBar = () => ui.light.primaryForeground;
const HEADER_HEIGHT = 48;
const TAB_HEIGHT = 56;

/** Tabler outline icons (24 grid, stroke 2), the same set the browser bottom bar draws. */
const ICONS: Record<NativeTab["key"] | "help", string[]> = {
  home: ["M5 12l-2 0l9 -9l9 9l-2 0", "M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2 -2v-7", "M9 21v-6a2 2 0 0 1 2 -2h2a2 2 0 0 1 2 2v6"],
  interviews: ["M9 6l11 0", "M9 12l11 0", "M9 18l11 0", "M5 6l0 .01", "M5 12l0 .01", "M5 18l0 .01"],
  register: ["M12 5l0 14", "M5 12l14 0"],
  sync: ["M20 11a8.1 8.1 0 0 0 -15.5 -2m-.5 -4v4h4", "M4 13a8.1 8.1 0 0 0 15.5 2m.5 4v-4h-4"],
  help: ["M3 12a9 9 0 1 0 18 0a9 9 0 0 0 -18 0", "M12 17l0 .01", "M12 13.5a1.5 1.5 0 0 1 1 -1.5a2.6 2.6 0 1 0 -3 -4"],
};

function Icon({ name, color, size = 24 }: { name: keyof typeof ICONS; color: string; size?: number }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      {ICONS[name].map((d) => <Path key={d} d={d} />)}
    </Svg>
  );
}

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

/** The app-language button (文A): one tap switches English and हिन्दी. Used in the header and on the pre-login screens. */
export function LanguageButton({ color }: { color: string }) {
  const { uiLocale, chooseUiLocale } = useAppState();
  const next = UI_LOCALES.find((locale) => locale.code !== uiLocale) ?? UI_LOCALES[0];
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={t("appLanguageSwitch", { language: next.label })}
      onPress={() => void chooseUiLocale(next.code)}
      style={{ width: 48, height: 48, alignItems: "center", justifyContent: "center" }}
    >
      <Text style={{ ...typography.subhead, fontWeight: "700", color }}>文A</Text>
    </Pressable>
  );
}

export function NativeHeader() {
  const shell = useShell();
  const { ready } = useAppState();
  return ready && shell.header ? <HeaderBar /> : null;
}

function HeaderBar() {
  const shell = useShell();
  const { accounts, device } = useAppState();
  const insets = useSafeAreaInsets();
  const account = accounts.find((item) => item.user_id === shell.userId);
  const chip = syncIndicator(shell.sync);
  const preLogin = isPreLoginRoute(usePathname().replace(/\/$/, "") || "/");
  const BAR = bar();
  const ON_BAR = onBar();
  return (
    <View style={{ backgroundColor: BAR, paddingTop: insets.top }}>
      <View style={{ height: HEADER_HEIGHT, flexDirection: "row", alignItems: "center", gap: spacing.xs, paddingLeft: spacing.sm, paddingRight: spacing.xxs }}>
        <Image source={require("../../assets/icon.png")} accessibilityLabel={t("appName")} style={{ width: 28, height: 28, borderRadius: 6, backgroundColor: "#FFFFFF" }} />
        <Text accessibilityRole="header" numberOfLines={1} style={{ ...typography.headline, color: ON_BAR, flex: 1 }}>DigitVA</Text>
        <DemoBadge server={device?.server} />
        {account && chip && !preLogin ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={chip.label}
            onPress={() => shell.openSheet("sync")}
            style={{ height: 32, paddingHorizontal: spacing.sm, borderRadius: 16, backgroundColor: "rgba(255,255,255,0.18)", flexDirection: "row", alignItems: "center", gap: spacing.xxs }}
          >
            {chip.busy ? <ActivityIndicator size="small" color={ON_BAR} /> : <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: "#FCD34D" }} />}
            {chip.busy ? null : <Text style={{ ...typography.caption, color: ON_BAR }}>{chip.label}</Text>}
          </Pressable>
        ) : null}
        {preLogin ? null : (
          <Pressable accessibilityRole="button" accessibilityLabel={t("formHelp")} onPress={() => shell.openSheet("help")} style={{ width: 48, height: 48, alignItems: "center", justifyContent: "center" }}>
            <Icon name="help" color={ON_BAR} />
          </Pressable>
        )}
        <LanguageButton color={ON_BAR} />
        {account && !preLogin ? (
          <Pressable accessibilityRole="button" accessibilityLabel={t("accountMenu")} onPress={() => shell.openSheet("account")} style={{ width: 48, height: 48, alignItems: "center", justifyContent: "center" }}>
            <View style={{ width: 32, height: 32, borderRadius: 16, backgroundColor: "#FFFFFF", alignItems: "center", justifyContent: "center" }}>
              <Text style={{ ...typography.caption, fontWeight: "700", color: BAR }}>{initials(account.name)}</Text>
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
  const pathname = usePathname().replace(/\/$/, "") || "/";
  const params = useGlobalSearchParams<{ view?: string | string[] }>();
  const { accounts } = useAppState();
  const { ui: tokens } = useTheme();
  const insets = useSafeAreaInsets();
  const account = accounts.find((item) => item.user_id === shell.userId);
  const active = activeNativeTab(pathname, params);
  const open = (tab: NativeTab) => {
    if (!tab.route) return shell.openSheet("sync");
    if (tab.key === active) return;
    router.replace({ pathname: tab.route as never, params: { userId: shell.userId, ...tab.params } });
  };
  return (
    <View accessibilityRole="tablist" style={{ flexDirection: "row", height: TAB_HEIGHT + insets.bottom, paddingBottom: insets.bottom, backgroundColor: tokens.background, borderTopWidth: 1, borderColor: tokens.border }}>
      {nativeTabs(account).map((tab) => {
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
            {on ? <View style={{ position: "absolute", top: 0, left: 8, right: 8, height: 3, borderRadius: 4, backgroundColor: tokens.primary }} /> : null}
            <Icon name={tab.key} color={color} />
            <Text numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.92} maxFontSizeMultiplier={1.2} style={{ ...typography.caption, ...controlText, lineHeight: 18, alignSelf: "stretch", paddingHorizontal: 2, fontWeight: "500", color }}>{t(tab.labelKey)}</Text>
            {badge ? (
              <View style={{ position: "absolute", top: 4, left: "55%", minWidth: 18, height: 18, borderRadius: 9, paddingHorizontal: 5, backgroundColor: tokens.destructiveText, alignItems: "center", justifyContent: "center" }}>
                <Text style={{ fontSize: 11, fontWeight: "700", color: "#FFFFFF" }}>{badge > 99 ? "99+" : badge}</Text>
              </View>
            ) : null}
          </Pressable>
        );
      })}
    </View>
  );
}
