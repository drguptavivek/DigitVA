import { useCallback, useEffect, useMemo, useState } from "react";
import { Platform, useColorScheme, type TextStyle } from "react-native";

import {
  getUiTheme,
  setUiTheme,
  subscribeUiPreferences,
  type ThemePreference
} from "./preferences";

export type ColorMode = "light" | "dark";

/** Semantic blue-accent palettes. Text and surfaces retain readable contrast in both modes. */
export const palette = {
  light: {
    background: "#F6F8FB",
    surface: "#FFFFFF",
    surfaceMuted: "#EEF3F8",
    text: "#10233F",
    textMuted: "#53657A",
    border: "#D9E2EC",
    accent: "#1D4ED8",
    accentPressed: "#1E40AF",
    accentSoft: "#E8F0FF",
    onAccent: "#FFFFFF",
    danger: "#B42318",
    dangerSoft: "#FDECEC",
    success: "#1F7A4D",
    warning: "#9A6700",
    focus: "#2563EB",
    disabled: "#8A99AA"
  },
  dark: {
    background: "#0B1220",
    surface: "#131E2E",
    surfaceMuted: "#1B2A3D",
    text: "#F4F7FB",
    textMuted: "#B5C2D1",
    border: "#314157",
    accent: "#78A9FF",
    accentPressed: "#A7C4FF",
    accentSoft: "#1C3764",
    onAccent: "#081429",
    danger: "#FF8A80",
    dangerSoft: "#4B2025",
    success: "#75D5A4",
    warning: "#F5C76B",
    focus: "#9CC0FF",
    disabled: "#718097"
  }
} as const;

export const spacing = {
  xxs: 4,
  xs: 8,
  sm: 12,
  md: 16,
  lg: 24,
  xl: 32,
  xxl: 48
} as const;

const webFontFamily = "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";

/** System fonts provide broad multi-script coverage; the web gets an explicit fallback stack. */
export const typography = {
  largeTitle: { fontSize: 30, lineHeight: 38, fontWeight: "700" as const },
  title: { fontSize: 24, lineHeight: 32, fontWeight: "700" as const },
  headline: { fontSize: 18, lineHeight: 26, fontWeight: "600" as const },
  body: { fontSize: 17, lineHeight: 26, fontWeight: "400" as const },
  subhead: { fontSize: 15, lineHeight: 22, fontWeight: "400" as const },
  caption: { fontSize: 13, lineHeight: 18, fontWeight: "400" as const }
} as const satisfies Record<string, TextStyle>;

export const radius = {
  sm: 8,
  md: 12,
  lg: 16,
  full: 9999
} as const;

export const controls = {
  minHeight: 48,
  minTouchTarget: 48,
  screenPadding: spacing.md,
  contentMaxWidth: 720,
  fontFamily: Platform.select({ web: webFontFamily, default: undefined })
} as const;

export type Theme = {
  mode: ColorMode;
  colors: (typeof palette)[ColorMode];
  spacing: typeof spacing;
  typography: typeof typography;
  radius: typeof radius;
  controls: typeof controls;
};

export function getTheme(mode: ColorMode): Theme {
  return { mode, colors: palette[mode], spacing, typography, radius, controls };
}

/**
 * Theme hook. The stored preference is UI-only and defaults to the platform
 * colour scheme. Hindi and other scripts continue to use the platform font.
 */
export function useTheme(): Theme & {
  preference: ThemePreference;
  setPreference: (preference: ThemePreference) => Promise<void>;
} {
  const systemScheme = useColorScheme();
  const [preference, setPreferenceState] = useState<ThemePreference>("system");

  useEffect(() => {
    let active = true;
    void getUiTheme().then((stored) => {
      if (active) setPreferenceState(stored);
    });
    const unsubscribe = subscribeUiPreferences(() => {
      void getUiTheme().then((stored) => {
        if (active) setPreferenceState(stored);
      });
    });
    return () => {
      active = false;
      unsubscribe();
    };
  }, []);

  const mode: ColorMode = preference === "system" ? (systemScheme === "dark" ? "dark" : "light") : preference;
  const theme = useMemo(() => getTheme(mode), [mode]);
  const updatePreference = useCallback(async (next: ThemePreference) => {
    setPreferenceState(next);
    await setUiTheme(next);
  }, []);
  return { ...theme, preference, setPreference: updatePreference };
}
