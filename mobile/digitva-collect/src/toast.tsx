/**
 * App-wide transient notices. `useToast().show` never shifts the page: toasts float above the bottom inset
 * (or above the phone's tab bar, which reserves its height with `useToastClearance`), the wrapper ignores
 * touches, and only the toast itself takes a tap. No outline: the kind is a tint fill (error, info, success). At most two are stacked (the oldest is
 * dropped), and a repeat of the same text only restarts the timer of the one already shown.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AccessibilityInfo, Platform, Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { recordToastError } from "./errorLog";
import { radius, spacing, useTheme } from "./theme";

export const TOAST_MS = 4_000;
export const TOAST_ERROR_MS = 6_000;
export const TOAST_EXPANDED_MS = 15_000;
const MAX_TOASTS = 2;

export interface ToastInput {
  kind: "info" | "success" | "error";
  text: string;
  /** Shown after a tap (an error's Ref line). */
  detail?: string;
  /** A button under the text (the update notice's Download); the toast then stays longer. */
  action?: { label: string; onPress(): void };
}
interface ToastItem extends ToastInput {
  id: number;
  /** Bumped by a duplicate show() so the timer restarts. */
  nonce: number;
}
interface ToastApi {
  show(toast: ToastInput): void;
}

const NOOP: ToastApi = { show: () => undefined };
const Context = createContext<ToastApi>(NOOP);
/** Sets the height of the bar at the bottom of the screen (0 = none), so toasts sit above it. */
const ClearanceContext = createContext<(height: number) => void>(() => undefined);

/**
 * The bottom bar (the phone's tab bar) calls this with its full height, safe area included, while it is on
 * screen; toasts then float above it instead of over it. Safe without a provider.
 */
export function useToastClearance(height: number): void {
  const setClearance = useContext(ClearanceContext);
  useEffect(() => {
    setClearance(height);
    return () => setClearance(0);
  }, [height, setClearance]);
}

/** Safe without a provider (tests, web): show() does nothing. */
export function useToast(): ToastApi {
  return useContext(Context);
}

/** An error text from `errorText` carries its support line after a newline; the toast keeps it as `detail`. */
function splitRef(toast: ToastInput): ToastInput {
  if (toast.detail !== undefined) return toast;
  const at = toast.text.indexOf("\nRef:");
  return at < 0 ? toast : { ...toast, text: toast.text.slice(0, at), detail: toast.text.slice(at + 1) };
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const [clearance, setClearance] = useState(0);
  const nextId = useRef(1);
  const show = useCallback((input: ToastInput) => {
    const toast = splitRef(input);
    if (!toast.text) return;
    if (toast.kind === "error" && toast.detail === undefined) recordToastError(toast.text);
    // A toast follows an action: VoiceOver says it without moving focus (TalkBack reads the polite live region).
    if (Platform.OS === "ios" && typeof AccessibilityInfo.announceForAccessibility === "function") AccessibilityInfo.announceForAccessibility(toast.text);
    setItems((current) => {
      const same = current.find((item) => item.text === toast.text);
      if (same) return current.map((item) => (item === same ? { ...item, ...toast, nonce: item.nonce + 1 } : item));
      return [...current, { ...toast, id: nextId.current++, nonce: 0 }].slice(-MAX_TOASTS);
    });
  }, []);
  const hide = useCallback((id: number) => setItems((current) => current.filter((item) => item.id !== id)), []);
  const api = useMemo(() => ({ show }), [show]);
  return (
    <Context.Provider value={api}>
      <ClearanceContext.Provider value={setClearance}>{children}</ClearanceContext.Provider>
      {items.length ? <ToastStack items={items} clearance={clearance} onHide={hide} /> : null}
    </Context.Provider>
  );
}

function ToastStack({ items, clearance, onHide }: { items: ToastItem[]; clearance: number; onHide: (id: number) => void }) {
  const insets = useSafeAreaInsets();
  // The tab bar's height already holds the bottom inset; without a bar the inset alone.
  return (
    <View
      pointerEvents="box-none"
      style={{ position: "absolute", left: 0, right: 0, bottom: (clearance || insets.bottom) + spacing.md, paddingHorizontal: spacing.md, alignItems: "center", gap: spacing.xs }}
    >
      {items.map((item) => <ToastView key={item.id} item={item} onHide={() => onHide(item.id)} />)}
    </View>
  );
}

function ToastView({ item, onHide }: { item: ToastItem; onHide: () => void }) {
  const { ui, typography } = useTheme();
  const [expanded, setExpanded] = useState(false);
  const hideRef = useRef(onHide);
  hideRef.current = onHide;

  useEffect(() => {
    const ms = expanded || item.action ? TOAST_EXPANDED_MS : item.kind === "error" ? TOAST_ERROR_MS : TOAST_MS;
    const timer = setTimeout(() => hideRef.current(), ms);
    return () => clearTimeout(timer);
  }, [expanded, item.kind, item.nonce, item.action]);

  // Tint fill, never an outline: error = error tint and text, info = primary tint, success = success text on the card.
  const fill = item.kind === "error" ? ui.destructiveSoft : item.kind === "info" ? ui.accent : ui.popover;
  const ink = item.kind === "error" ? ui.destructiveText : item.kind === "info" ? ui.accentForeground : ui.success;
  return (
    <Pressable
      accessibilityRole="alert"
      accessibilityLiveRegion="polite"
      focusable={false}
      onPress={() => item.detail && setExpanded((open) => !open)}
      style={{ maxWidth: 480, width: "100%", backgroundColor: fill, borderRadius: radius.lg, padding: spacing.sm, elevation: 3, shadowColor: "#000", shadowOpacity: 0.12, shadowRadius: 8, shadowOffset: { width: 0, height: 2 } }}
    >
      <Text selectable={expanded} numberOfLines={expanded ? undefined : 2} style={{ ...typography.subhead, color: ink }}>
        {expanded && item.detail ? item.detail : item.text}
      </Text>
      {item.action ? (
        <Pressable accessibilityRole="button" accessibilityLabel={item.action.label} onPress={() => { item.action?.onPress(); hideRef.current(); }} style={{ minHeight: 48, justifyContent: "center" }}>
          <Text style={{ ...typography.body, color: ui.primary, fontWeight: "600" }}>{item.action.label}</Text>
        </Pressable>
      ) : null}
    </Pressable>
  );
}
