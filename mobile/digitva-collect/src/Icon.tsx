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
  code: { ios: "checkmark.seal", android: "verified" },
  review: { ios: "checkmark.circle", android: "task_alt" },
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
  pause: { ios: "pause.fill", android: "pause" },
  // The full-screen photo viewer (src/AttachmentImageViewer.tsx).
  rotate: { ios: "rotate.right", android: "rotate_right" },
  rotateLeft: { ios: "rotate.left", android: "rotate_left" },
  // The coding workspace's full-screen image viewer (src/workspace/media/ImageViewer.native.tsx).
  previous: { ios: "chevron.left", android: "chevron_left" },
  zoomIn: { ios: "plus.magnifyingglass", android: "zoom_in" },
  zoomOut: { ios: "minus.magnifyingglass", android: "zoom_out" },
  resetView: { ios: "arrow.counterclockwise", android: "fit_screen" },
  accepted: { ios: "checkmark", android: "check" },
  settings: { ios: "gearshape", android: "settings" },
  lock: { ios: "lock", android: "lock" },
  switchUser: { ios: "person.2", android: "group" },
  signOut: { ios: "rectangle.portrait.and.arrow.right", android: "logout" },
  // Coding case lists (Home, Interviews, Settings).
  localCases: { ios: "iphone", android: "phone_android" },
  onlineCases: { ios: "cloud", android: "cloud" },
  codedCases: { ios: "checkmark.seal", android: "verified" },
  // The phone coding workspace's section rail (src/workspace/PhoneSectionRail.native.tsx).
  menu: { ios: "line.3.horizontal", android: "menu" },
  dismiss: { ios: "xmark", android: "close" },
  attachments: { ios: "paperclip", android: "attach_file" }
} as const satisfies Record<string, IconName>;

const folderIcon = { ios: "folder", android: "folder_open" } as const satisfies IconName;

/** Coding section icons by the server's FontAwesome `icon_name` (the web rail draws the same names); unknown or missing: a folder. */
const SECTION_ICONS = {
  "fa-brain": { ios: "brain.head.profile", android: "psychology" },
  "fa-female": { ios: "figure.stand.dress", android: "female" },
  "fa-allergies": { ios: "allergens", android: "allergy" },
  "fa-info-circle": { ios: "info.circle", android: "info" },
  "fa-history": { ios: "clock.arrow.circlepath", android: "history" },
  "fa-lungs": { ios: "lungs", android: "pulmonology" },
  "fa-baby": { ios: "figure.child", android: "child_care" },
  "fa-user": { ios: "person", android: "person" },
  "fa-first-aid": { ios: "cross.case", android: "medical_services" },
  "fa-hospital-alt": { ios: "cross.circle", android: "local_hospital" },
  "fa-thermometer": { ios: "thermometer.medium", android: "thermostat" },
  "fa-file-medical-alt": { ios: "doc.text", android: "description" },
  "fa-capsules": { ios: "pills", android: "medication" },
  "fa-baby-carriage": { ios: "stroller", android: "stroller" },
  "fa-users": { ios: "person.2", android: "group" },
  "fa-folder-open": folderIcon
} as const satisfies Record<string, IconName>;

export function sectionIcon(name?: string | null): IconName {
  return (name && (SECTION_ICONS as Record<string, IconName>)[name]) || folderIcon;
}

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
