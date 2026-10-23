/**
 * App-wide transient notices. `useToast().show` never shifts the page: toasts float above the bottom inset,
 * the wrapper ignores touches, and only the toast itself takes a tap. At most two are stacked (the oldest is
 * dropped), and a repeat of the same text only restarts the timer of the one already shown.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { recordToastError } from "./errorLog";
import { radius, spacing, typography, useTheme } from "./theme";

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
  const nextId = useRef(1);
  const show = useCallback((input: ToastInput) => {
    const toast = splitRef(input);
    if (!toast.text) return;
    if (toast.kind === "error" && toast.detail === undefined) recordToastError(toast.text);
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
      {children}
      {items.length ? <ToastStack items={items} onHide={hide} /> : null}
    </Context.Provider>
  );
}

function ToastStack({ items, onHide }: { items: ToastItem[]; onHide: (id: number) => void }) {
  const insets = useSafeAreaInsets();
  return (
    <View
      pointerEvents="box-none"
      style={{ position: "absolute", left: 0, right: 0, bottom: insets.bottom + spacing.md, paddingHorizontal: spacing.md, alignItems: "center", gap: spacing.xs }}
    >
      {items.map((item) => <ToastView key={item.id} item={item} onHide={() => onHide(item.id)} />)}
    </View>
  );
}

function ToastView({ item, onHide }: { item: ToastItem; onHide: () => void }) {
  const { ui } = useTheme();
  const [expanded, setExpanded] = useState(false);
  const hideRef = useRef(onHide);
  hideRef.current = onHide;

  useEffect(() => {
    const ms = expanded || item.action ? TOAST_EXPANDED_MS : item.kind === "error" ? TOAST_ERROR_MS : TOAST_MS;
    const timer = setTimeout(() => hideRef.current(), ms);
    return () => clearTimeout(timer);
  }, [expanded, item.kind, item.nonce, item.action]);

  const tone = item.kind === "error" ? ui.destructiveText : item.kind === "success" ? ui.success : ui.border;
  return (
    <Pressable
      accessibilityRole="alert"
      accessibilityLiveRegion="polite"
      focusable={false}
      onPress={() => item.detail && setExpanded((open) => !open)}
      style={{ maxWidth: 480, width: "100%", backgroundColor: ui.popover, borderColor: tone, borderWidth: 1, borderRadius: radius.lg, padding: spacing.sm }}
    >
      <Text selectable={expanded} numberOfLines={expanded ? undefined : 2} style={{ ...typography.subhead, color: ui.popoverForeground }}>
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
