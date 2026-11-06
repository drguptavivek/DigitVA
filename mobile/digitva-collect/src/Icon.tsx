/**
 * Native icons (docs/policy/expo-client.md "Theme"): SF Symbols on iOS, Material Symbols on Android and the web,
 * one meaning per icon. expo-symbols draws Material Symbols from a bundled font on Android and the web, so the web
 * export needs no native module; a name missing on a platform renders `fallback` (default: an empty box of `size`).
 */
import type { ReactNode } from "react";
import { View } from "react-native";
import { SymbolView, type AndroidSymbol, type SFSymbol } from "expo-symbols";

export type IconName = { ios: SFSymbol; android: AndroidSymbol };

/** The shared icon meanings; add a pair here rather than naming symbols in a screen. */
export const icons = {
  info: { ios: "info.circle.fill", android: "info" },
  warning: { ios: "exclamationmark.triangle.fill", android: "warning" },
  error: { ios: "exclamationmark.circle.fill", android: "error" },
  success: { ios: "checkmark.circle.fill", android: "check_circle" },
  chevronRight: { ios: "chevron.right", android: "chevron_right" },
  close: { ios: "xmark.circle.fill", android: "cancel" },
  // The phone shell (src/nativeShell/NativeChrome.tsx): tabs, back, Help, app language.
  home: { ios: "house", android: "home" },
  interviews: { ios: "list.bullet.rectangle", android: "list_alt" },
  register: { ios: "plus.circle", android: "add_circle" },
  sync: { ios: "arrow.triangle.2.circlepath", android: "sync" },
  back: { ios: "chevron.left", android: "arrow_back_ios_new" },
  help: { ios: "questionmark.circle", android: "help" },
  // 文A: the translate glyph says "language" to a first-time Hindi user; a globe does not.
  language: { ios: "translate", android: "translate" },
  // Password and PIN fields: the trailing show/hide button.
  show: { ios: "eye", android: "visibility" },
  hide: { ios: "eye.slash", android: "visibility_off" },
  // Welcome / enrol option rows (design sheet 11) and the Account sheet menu.
  qr: { ios: "qrcode.viewfinder", android: "qr_code_scanner" },
  atSign: { ios: "at", android: "alternate_email" },
  phoneOnly: { ios: "iphone", android: "phone_android" },
  play: { ios: "play.fill", android: "play_arrow" },
  accepted: { ios: "checkmark", android: "check" },
  settings: { ios: "gearshape", android: "settings" },
  lock: { ios: "lock", android: "lock" },
  switchUser: { ios: "person.2", android: "group" },
  signOut: { ios: "rectangle.portrait.and.arrow.right", android: "logout" },
  // Coding case lists (Home, Interviews, Settings).
  localCases: { ios: "iphone", android: "phone_android" },
  onlineCases: { ios: "cloud", android: "cloud" },
  codedCases: { ios: "checkmark.seal", android: "verified" }
} as const satisfies Record<string, IconName>;

export function Icon({ name, color, size = 20, fallback, accessibilityLabel }: {
  name: IconName;
  color: string;
  size?: number;
  fallback?: ReactNode;
  /** Omitted: the icon is decorative and hidden from screen readers (its row or button carries the words). */
  accessibilityLabel?: string;
}) {
  return (
    <SymbolView
      name={{ ios: name.ios, android: name.android, web: name.android }}
      tintColor={color}
      size={size}
      fallback={fallback ?? <View style={{ width: size, height: size }} />}
      accessible={Boolean(accessibilityLabel)}
      accessibilityLabel={accessibilityLabel}
      importantForAccessibility={accessibilityLabel ? "yes" : "no-hide-descendants"}
    />
  );
}
