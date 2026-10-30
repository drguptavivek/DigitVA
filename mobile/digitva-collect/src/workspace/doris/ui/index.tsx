/**
 * Tiny DORIS UI kit: shadcn/ui's tokens and composition ideas on plain React Native
 * components. No UI library; variants are small style maps (the cva idea).
 * Token table and rules: docs/current-state/doris-ui-tokens.md.
 */
import { useMemo, useRef, useState, type ComponentProps, type ReactNode } from "react";
import { ActivityIndicator, Modal, Platform, Pressable, ScrollView, Text, TextInput, View, useWindowDimensions, type StyleProp, type TextStyle, type ViewStyle } from "react-native";

import { BUTTON_MIN_WIDTH, buttonTone, fontSize, uiRadius, useTheme, type ButtonSize, type ButtonVariant, type ChartToken, type UiTokens } from "../../../theme";

export { uiRadius };
export type { ChartToken, UiTokens };

/** Spacing scale 4/8/12/16/24 (the `spacing` steps of src/theme.ts). */
export const gap = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 } as const;
/** Font scale of src/theme.ts: 14 body/label, 12 caption, 16 titles and inputs/choice rows on phones. */
export const font = { body: fontSize.body, caption: fontSize.caption, title: fontSize.input } as const;
/** Control height 40; phones get 44 so every control is a 44px tap target (`controlHeight`). */
export const CONTROL_HEIGHT = 40;
export const PHONE_CONTROL_HEIGHT = 44;
/** Chips and small buttons never shrink below this width, so "No"/"Yes" read as buttons, not circles. */
export const CHIP_MIN_WIDTH = BUTTON_MIN_WIDTH;
/** Visual 40px controls reach the 48px touch target through hit-slop. */
export const HIT_SLOP = 4;
/** Focus ring: 2px line + 2px offset, i.e. 4px outside the control; groups of rows pad by this much so overflow clips never cut it. */
export const RING_ROOM = 4;
const isWeb = Platform.OS === "web";

/** Semantic tokens of the current colour mode plus the phone breakpoint. */
export function useUi(): { t: UiTokens; phone: boolean; controlHeight: number } {
  const { ui } = useTheme();
  const phone = useWindowDimensions().width < 768;
  return { t: ui, phone, controlHeight: phone ? PHONE_CONTROL_HEIGHT : CONTROL_HEIGHT };
}

/** Focus ring: 2px in the ring colour with a 2px offset on the web, a ring-coloured border on native. */
function useFocusRing(ring: string) {
  const [focused, setFocused] = useState(false);
  const style = focused && isWeb ? ({ outlineStyle: "solid", outlineWidth: 2, outlineColor: ring, outlineOffset: 2 } as ViewStyle) : null;
  return { focused, style, handlers: { onFocus: () => setFocused(true), onBlur: () => setFocused(false) } };
}

const disabledStyle = (disabled?: boolean): ViewStyle | null => (disabled ? ({ opacity: 0.5, ...(isWeb ? { cursor: "not-allowed" } : {}) } as ViewStyle) : null);

/* ---------------------------------------------------------------- Card */

export function Card({ children, style, testID }: { children: ReactNode; style?: StyleProp<ViewStyle>; testID?: string }) {
  const { t } = useUi();
  return <View testID={testID} style={[{ backgroundColor: t.card, borderRadius: uiRadius.lg, borderWidth: 1, borderColor: t.border, padding: gap.lg, gap: gap.md }, style]}>{children}</View>;
}

export function CardHeader({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[{ gap: gap.xs }, style]}>{children}</View>;
}

export function CardTitle({ children, style, numberOfLines }: { children: ReactNode; style?: StyleProp<TextStyle>; numberOfLines?: number }) {
  const { t } = useUi();
  return <Text accessibilityRole="header" numberOfLines={numberOfLines} style={[{ fontSize: font.title, lineHeight: 22, fontWeight: "600", color: t.cardForeground, flexShrink: 1 }, style]}>{children}</Text>;
}

export function CardDescription({ children }: { children: ReactNode }) {
  const { t } = useUi();
  return <Text style={{ fontSize: font.body, lineHeight: 20, color: t.mutedForeground }}>{children}</Text>;
}

/* --------------------------------------------------------------- Typography */

/** Plain body text (text-sm, foreground). */
export function Body({ children, style }: { children: ReactNode; style?: StyleProp<TextStyle> }) {
  const { t } = useUi();
  return <Text style={[{ fontSize: font.body, lineHeight: 20, color: t.foreground }, style]}>{children}</Text>;
}

/** Secondary body text (text-sm, muted-foreground). */
export function Muted({ children, style }: { children: ReactNode; style?: StyleProp<TextStyle> }) {
  const { t } = useUi();
  return <Text style={[{ fontSize: font.body, lineHeight: 20, color: t.mutedForeground }, style]}>{children}</Text>;
}

/** Heading of a section inside the editor (16px semibold). */
export function SectionTitle({ children, style, numberOfLines }: { children: ReactNode; style?: StyleProp<TextStyle>; numberOfLines?: number }) {
  const { t } = useUi();
  return <Text accessibilityRole="header" numberOfLines={numberOfLines} style={[{ fontSize: font.title, lineHeight: 22, fontWeight: "600", color: t.foreground, flexShrink: 1 }, style]}>{children}</Text>;
}

/** Field label: full foreground, 14px semibold, so it stands out from the muted hints and badges. */
export function Label({ children }: { children: ReactNode }) {
  const { t } = useUi();
  return <Text style={{ fontSize: font.body, lineHeight: 20, fontWeight: "600", color: t.foreground }}>{children}</Text>;
}

/** 12px helper text under a field. */
export function FieldHint({ children, testID }: { children: ReactNode; testID?: string }) {
  const { t } = useUi();
  return <Text testID={testID} style={{ fontSize: font.caption, lineHeight: 16, color: t.mutedForeground }}>{children}</Text>;
}

/** 12px error text under a field; announced as an alert. */
export function FieldError({ children }: { children: ReactNode }) {
  const { t } = useUi();
  return <Text accessibilityRole="alert" style={{ fontSize: font.caption, lineHeight: 16, color: t.destructiveText }}>{children}</Text>;
}

/** Soft rule warning under the field it concerns; never blocks anything. */
export function FieldWarning({ children, testID }: { children: ReactNode; testID?: string }) {
  const { t } = useUi();
  return <Text testID={testID} style={{ fontSize: font.caption, lineHeight: 16, color: t.warningForeground, fontWeight: "500" }}>{children}</Text>;
}

export function Separator({ style, testID }: { style?: StyleProp<ViewStyle>; testID?: string }) {
  const { t } = useUi();
  return <View testID={testID} accessibilityRole="none" style={[{ height: 1, alignSelf: "stretch", backgroundColor: t.border }, style]} />;
}

/** Scrollable-looking block for a long engine report: muted fill, 1px border. */
export function ReportBox({ children }: { children: ReactNode }) {
  const { t } = useUi();
  return (
    <View style={{ backgroundColor: t.muted, borderWidth: 1, borderColor: t.border, borderRadius: uiRadius.md, padding: gap.sm }}>
      <Text selectable style={{ fontSize: font.caption, lineHeight: 18, color: t.foreground }}>{children}</Text>
    </View>
  );
}

/* ------------------------------------------------------------------ Alert */

export type AlertVariant = "default" | "warning" | "destructive";

const alertTone = (t: UiTokens, variant: AlertVariant) =>
  variant === "warning" ? { bg: t.warning, border: t.warningBorder, fg: t.warningForeground }
    : variant === "destructive" ? { bg: t.background, border: t.destructiveText, fg: t.destructiveText }
      : { bg: t.background, border: t.border, fg: t.foreground };

/** Bordered callout. `warning` keeps the 4px accent edge the N/A notes use. */
export function Alert({ variant = "default", children, testID, role }: { variant?: AlertVariant; children: ReactNode; testID?: string; role?: "alert" | "none" }) {
  const { t } = useUi();
  const tone = alertTone(t, variant);
  return (
    <View testID={testID} accessibilityRole={role ?? (variant === "destructive" ? "alert" : undefined)} style={{ backgroundColor: tone.bg, borderWidth: 1, borderColor: tone.border, borderLeftWidth: variant === "warning" ? 4 : 1, borderRadius: uiRadius.md, paddingHorizontal: gap.md, paddingVertical: gap.sm }}>
      {typeof children === "string" ? <Text style={{ fontSize: font.caption, lineHeight: 16, color: tone.fg }}>{children}</Text> : children}
    </View>
  );
}

/* ------------------------------------------------------------------ Badge */

export type BadgeVariant = "default" | "secondary" | "outline" | "destructive";

const badgeTone = (t: UiTokens, variant: BadgeVariant) =>
  variant === "default" ? { bg: t.primary, border: t.primary, fg: t.primaryForeground }
    : variant === "secondary" ? { bg: t.secondary, border: t.secondary, fg: t.secondaryForeground }
      : variant === "destructive" ? { bg: t.destructive, border: t.destructive, fg: t.destructiveForeground }
        : { bg: "transparent", border: t.border, fg: t.foreground };

export function Badge({ variant = "secondary", children, mono }: { variant?: BadgeVariant; children: ReactNode; mono?: boolean }) {
  const { t } = useUi();
  const tone = badgeTone(t, variant);
  return (
    <View style={{ alignSelf: "flex-start", borderRadius: uiRadius.full, borderWidth: 1, borderColor: tone.border, backgroundColor: tone.bg, paddingHorizontal: gap.sm - 2, paddingVertical: 1, flexShrink: 1 }}>
      <Text style={{ fontSize: font.caption, lineHeight: 16, fontWeight: "600", color: tone.fg, ...(mono ? { fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace" } : null) }}>{children}</Text>
    </View>
  );
}

/* ----------------------------------------------------------------- Button */

export type { ButtonVariant, ButtonSize };

/** Heights are the control scale (40, 44 on phones); `sm` only trims the padding. */
const buttonSize = (size: ButtonSize, height: number): ViewStyle => ({
  sm: { minHeight: height, minWidth: CHIP_MIN_WIDTH, paddingHorizontal: gap.md },
  default: { minHeight: height, minWidth: CHIP_MIN_WIDTH, paddingHorizontal: gap.lg },
  icon: { minHeight: height, minWidth: height, paddingHorizontal: 0 },
})[size];

type ButtonProps = {
  label?: string;
  children?: ReactNode;
  onPress: () => void;
  variant?: ButtonVariant;
  size?: ButtonSize;
  disabled?: boolean;
  loading?: boolean;
  accessibilityLabel?: string;
  accessibilityState?: ComponentProps<typeof Pressable>["accessibilityState"];
  accessibilityRole?: ComponentProps<typeof Pressable>["accessibilityRole"];
  testID?: string;
  style?: StyleProp<ViewStyle>;
};

/** Text button (`label`) or icon button (`size="icon"` with `children`). Disabled is 50% opacity. */
export function Button({ label, children, onPress, variant = "default", size = "default", disabled, loading = false, accessibilityLabel, accessibilityState, accessibilityRole = "button", testID, style }: ButtonProps) {
  const { t, controlHeight } = useUi();
  const ring = useFocusRing(t.ring);
  const off = Boolean(disabled || loading);
  const tone = buttonTone(t, variant);
  return (
    <Pressable
      accessibilityRole={accessibilityRole}
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityState={{ ...accessibilityState, disabled: off, busy: loading }}
      testID={testID}
      disabled={off}
      hitSlop={HIT_SLOP}
      onPress={onPress}
      {...ring.handlers}
      style={({ pressed }) => [
        { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: gap.sm, borderRadius: uiRadius.md, borderWidth: 1, backgroundColor: tone.bg, borderColor: tone.border },
        buttonSize(size, controlHeight), pressed && !off ? { opacity: 0.85 } : null, ring.style, disabledStyle(off), style,
      ]}
    >
      {loading ? <ActivityIndicator size="small" color={tone.fg} /> : null}
      {children ?? <Text style={{ flexShrink: 1, textAlign: "center", fontSize: font.body, lineHeight: 20, fontWeight: "500", color: tone.fg }}>{label}</Text>}
    </Pressable>
  );
}

/** Glyph for an icon Button; red only when the button is destructive. */
export function ButtonGlyph({ children, destructive }: { children: string; destructive?: boolean }) {
  const { t } = useUi();
  return <Text style={{ fontSize: font.title, color: destructive ? t.destructiveText : t.foreground }}>{children}</Text>;
}

/* ------------------------------------------------------- Input / Textarea */

type InputProps = ComponentProps<typeof TextInput>;

function useFieldStyle(invalid?: boolean) {
  const { t, phone, controlHeight } = useUi();
  const ring = useFocusRing(t.ring);
  // 16px on phones: smaller text makes iOS zoom the page on focus.
  const base: TextStyle = { borderWidth: 1, borderColor: ring.focused ? t.ring : invalid ? t.destructiveText : t.input, borderRadius: uiRadius.md, paddingHorizontal: gap.md, paddingVertical: gap.xs, fontSize: phone ? fontSize.input : font.body, color: t.foreground, backgroundColor: t.background };
  return { t, base, ring, minHeight: controlHeight };
}

/** Single-line field: 40px high (44 on phones), input border, ring on focus, muted placeholder. */
export function Input({ style, invalid, editable, onFocus, onBlur, ...rest }: InputProps & { invalid?: boolean }) {
  const f = useFieldStyle(invalid);
  return (
    <TextInput
      placeholderTextColor={f.t.mutedForeground}
      editable={editable}
      onFocus={(event) => { f.ring.handlers.onFocus(); onFocus?.(event); }}
      onBlur={(event) => { f.ring.handlers.onBlur(); onBlur?.(event); }}
      style={[f.base, { minHeight: f.minHeight }, f.ring.style as TextStyle, editable === false ? disabledStyle(true) as TextStyle : null, style]}
      {...rest}
    />
  );
}

export function Textarea({ style, invalid, onFocus, onBlur, ...rest }: InputProps & { invalid?: boolean }) {
  const f = useFieldStyle(invalid);
  return (
    <TextInput
      multiline
      placeholderTextColor={f.t.mutedForeground}
      onFocus={(event) => { f.ring.handlers.onFocus(); onFocus?.(event); }}
      onBlur={(event) => { f.ring.handlers.onBlur(); onBlur?.(event); }}
      style={[f.base, { minHeight: 72, paddingVertical: gap.sm, textAlignVertical: "top" }, f.ring.style as TextStyle, style]}
      {...rest}
    />
  );
}

/** Field-looking Pressable (date button, select trigger). */
export function FieldButton({ children, onPress, accessibilityLabel, accessibilityValue, accessibilityState, style }: { children: ReactNode; onPress: () => void; accessibilityLabel: string; accessibilityValue?: ComponentProps<typeof Pressable>["accessibilityValue"]; accessibilityState?: ComponentProps<typeof Pressable>["accessibilityState"]; style?: StyleProp<ViewStyle> }) {
  const f = useFieldStyle();
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={accessibilityLabel} accessibilityValue={accessibilityValue} accessibilityState={accessibilityState} hitSlop={HIT_SLOP} onPress={onPress} {...f.ring.handlers} style={[f.base as ViewStyle, { minHeight: f.minHeight, minWidth: CHIP_MIN_WIDTH, flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: gap.sm }, f.ring.style, style]}>
      {children}
    </Pressable>
  );
}

/** Text inside a FieldButton or Chip. */
export function ControlText({ children, style }: { children: ReactNode; style?: StyleProp<TextStyle> }) {
  const { t } = useUi();
  return <Text style={[{ fontSize: font.body, lineHeight: 20, color: t.foreground }, style]}>{children}</Text>;
}

/* ------------------------------------------------- Select / Radio / Chip */

/**
 * Toggle chip for small controls (units, date buttons, remove-condition): 72px minimum width, 40px (44 on phones)
 * minimum height, 12px side padding, centred text, 6px radius; outline when off, brand-soft with a brand border when on.
 */
export function Chip({ children, selected, onPress, accessibilityRole = "button", accessibilityLabel, accessibilityState, testID, disabled, style, textStyle }: { children: ReactNode; selected?: boolean; onPress: () => void; accessibilityRole?: "button" | "radio"; accessibilityLabel: string; accessibilityState?: ComponentProps<typeof Pressable>["accessibilityState"]; testID?: string; disabled?: boolean; style?: StyleProp<ViewStyle>; textStyle?: StyleProp<TextStyle> }) {
  const { t, controlHeight } = useUi();
  const ring = useFocusRing(t.ring);
  return (
    <Pressable accessibilityRole={accessibilityRole} accessibilityLabel={accessibilityLabel} accessibilityState={accessibilityState} testID={testID} disabled={disabled} hitSlop={HIT_SLOP} onPress={onPress} {...ring.handlers}
      style={[{ flexDirection: "row", alignItems: "center", justifyContent: "center", minWidth: CHIP_MIN_WIDTH, minHeight: controlHeight, paddingHorizontal: gap.md, borderRadius: uiRadius.md, borderWidth: 1, borderColor: selected ? t.primary : t.input, backgroundColor: selected ? t.accent : t.background }, ring.style, disabledStyle(disabled), style]}>
      {typeof children === "string" ? <ControlText style={[{ textAlign: "center" }, textStyle]}>{children}</ControlText> : children}
    </Pressable>
  );
}

/**
 * Choice row, the same look as the WHO choice row of the Narrative-quality panel (both read the `ui` tokens):
 * input fill, 1px `input` edge, 6px radius, 48px minimum height, 12px/11px padding, a 22px radio circle with a
 * 10px dot, 16px text. Selected = brand border, brand dot, brand-soft fill.
 */
export function RadioRow({ label, selected, onPress, accessibilityLabel, accessibilityState, testID, disabled, style }: { label: string; selected: boolean; onPress: () => void; accessibilityLabel: string; accessibilityState?: ComponentProps<typeof Pressable>["accessibilityState"]; testID?: string; disabled?: boolean; style?: StyleProp<ViewStyle> }) {
  const { t } = useUi();
  const ring = useFocusRing(t.ring);
  return (
    <Pressable accessibilityRole="radio" accessibilityLabel={accessibilityLabel} accessibilityState={accessibilityState} testID={testID} disabled={disabled} onPress={onPress} {...ring.handlers}
      style={[{ flexDirection: "row", alignItems: "flex-start", columnGap: gap.md, minHeight: ROW_MIN_HEIGHT, paddingHorizontal: gap.md, paddingVertical: 11, borderWidth: 1, borderColor: selected ? t.primary : t.input, borderRadius: uiRadius.md, backgroundColor: selected ? t.accent : t.background }, ring.style, disabledStyle(disabled), style]}>
      <View style={{ width: RADIO_SIZE, height: RADIO_SIZE, marginTop: 1, borderRadius: uiRadius.full, borderWidth: 2, borderColor: selected ? t.primary : t.input, backgroundColor: t.background, alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
        {selected ? <View style={{ width: RADIO_DOT, height: RADIO_DOT, borderRadius: uiRadius.full, backgroundColor: t.primary }} /> : null}
      </View>
      <Text style={{ flexShrink: 1, fontSize: fontSize.input, lineHeight: 24, color: t.foreground }}>{label}</Text>
    </Pressable>
  );
}

/** Choice-row metrics shared with the WHO control: 48px row, 22px circle, 10px dot. */
const ROW_MIN_HEIGHT = 48;
const RADIO_SIZE = 22;
const RADIO_DOT = 10;

export interface MenuOption<T extends string> {
  value: T;
  label: string;
  /** Screen-reader name, for example "Estimated age unit: Years". */
  accessibilityLabel: string;
  /** Greyed but still selectable (units longer than the age). */
  dimmed?: boolean;
}

type Anchor = { x: number; y: number; width: number; height: number };

/**
 * Dropdown: a field-style trigger (button with expanded state) that opens a vertical list of options (radio with
 * selected state) laid over the content, so it never pushes or spills into sibling controls. The list closes on a
 * choice, on an outside press and on Escape (Modal's onRequestClose on web and native). It sits under the trigger
 * once the trigger is measured, else at a fixed offset. `triggerLabel` is the trigger's accessible name.
 */
/** Gap between a menu and the window edges. */
const MENU_EDGE = gap.sm;

/**
 * Top of a menu of `menuHeight` beside its trigger: below the trigger when it fits the window, else above it, else
 * pinned inside the window. Pure so the placement is testable without a device.
 */
export function menuTop(anchor: Anchor, menuHeight: number, windowHeight: number): number {
  const below = anchor.y + anchor.height + gap.xs;
  if (below + menuHeight <= windowHeight - MENU_EDGE) return below;
  const above = anchor.y - gap.xs - menuHeight;
  if (above >= MENU_EDGE) return above;
  return Math.max(MENU_EDGE, windowHeight - MENU_EDGE - menuHeight);
}

/**
 * Vertical choice menu over the content: a Modal with its options in a ScrollView capped to the window, placed
 * by menuTop, hidden until measured so it never paints at a guessed position. Closes on a choice, an outside
 * press or back; on web the trigger regains focus.
 */
export function MenuSelect<T extends string>({ triggerLabel, valueText, accessibilityValue, options, selected, onSelect, style }: { triggerLabel: string; valueText: string; accessibilityValue?: { text: string }; options: ReadonlyArray<MenuOption<T>>; selected: string; onSelect: (value: T) => void; style?: StyleProp<ViewStyle> }) {
  const { t, controlHeight } = useUi();
  const layout = useLayout();
  const { width: windowWidth, height: windowHeight } = useWindowDimensions();
  const trigger = useRef<View>(null);
  const [open, setOpen] = useState(false);
  const [anchor, setAnchor] = useState<Anchor | null>(null);
  const [menuHeight, setMenuHeight] = useState(0);
  const focusTrigger = () => {
    if (Platform.OS !== "web") return;
    // The trigger is the wrapper's only button; web focus needs the DOM node.
    const node = trigger.current as unknown as { querySelector?: (selector: string) => { focus?: () => void } | null } | null;
    node?.querySelector?.('[role="button"]')?.focus?.();
  };
  const close = () => {
    setOpen(false);
    setAnchor(null);
    setMenuHeight(0);
    focusTrigger();
  };
  const openMenu = () => {
    // measureInWindow is absent in unit tests: the menu then stays hidden, which is the point of measuring first.
    trigger.current?.measureInWindow?.((x, y, width, height) => setAnchor({ x, y, width, height }));
    setOpen(true);
  };
  const ready = anchor !== null && menuHeight > 0;
  const width = Math.max(anchor?.width ?? 0, CHIP_MIN_WIDTH);
  const left = anchor ? Math.min(Math.max(MENU_EDGE, anchor.x), windowWidth - MENU_EDGE - width) : MENU_EDGE;
  const top = anchor && ready ? menuTop(anchor, menuHeight, windowHeight) : 0;
  // The option list scrolls inside the window; the menu's own padding is the gap to the window edge.
  const listMaxHeight = Math.max(controlHeight, windowHeight - 2 * (MENU_EDGE + gap.xs));
  return (
    <View ref={trigger} collapsable={false}>
      <FieldButton accessibilityLabel={triggerLabel} accessibilityValue={accessibilityValue} accessibilityState={{ expanded: open }} onPress={() => (open ? close() : openMenu())} style={style}>
        <ControlText>{`${valueText} ▾`}</ControlText>
      </FieldButton>
      {open ? (
        <Modal visible transparent animationType="none" statusBarTranslucent onRequestClose={close}>
          <View style={{ flex: 1 }}>
            <Pressable accessibilityLabel="Close menu" onPress={close} style={{ position: "absolute", top: 0, bottom: 0, left: 0, right: 0 }} />
            <View accessibilityRole="menu" onLayout={(event) => setMenuHeight(event.nativeEvent.layout.height)}
              style={[{ position: "absolute", top, left, minWidth: width, opacity: ready ? 1 : 0, backgroundColor: t.popover, borderWidth: 1, borderColor: t.border, borderRadius: uiRadius.md, padding: gap.xs, elevation: 4 }]}>
              <ScrollView keyboardDismissMode="on-drag" style={{ maxHeight: listMaxHeight }} keyboardShouldPersistTaps="handled">
                {options.map((option) => {
                  const on = option.value === selected;
                  return (
                    <Pressable key={option.value} accessibilityRole="menuitem" accessibilityLabel={option.accessibilityLabel} accessibilityState={{ selected: on }} hitSlop={HIT_SLOP} onPress={() => { close(); onSelect(option.value); }}
                      style={[{ minHeight: controlHeight, justifyContent: "center", paddingHorizontal: gap.md, marginBottom: gap.xs, borderRadius: uiRadius.sm, backgroundColor: on ? t.accent : "transparent" }, option.dimmed ? layout.dim : null]}>
                      <ControlText>{option.label}</ControlText>
                    </Pressable>
                  );
                })}
              </ScrollView>
            </View>
          </View>
        </Modal>
      ) : null}
    </View>
  );
}

/** Wrapping group of choices with 12px gaps; padded so the focus ring of the first and last item is never clipped. */
export function RadioGroup({ children, style, onLayout }: { children: ReactNode; style?: StyleProp<ViewStyle>; onLayout?: ComponentProps<typeof View>["onLayout"] }) {
  return <View accessibilityRole="radiogroup" onLayout={onLayout} style={[{ flexDirection: "row", flexWrap: "wrap", alignItems: "stretch", gap: gap.md, padding: RING_ROOM, margin: -RING_ROOM }, style]}>{children}</View>;
}

/* ------------------------------------------------------- Colour helpers */

/** Chart token for a certificate line: Part I by position (cycling past five), Part II slate. */
export function chartFor(t: UiTokens, index: number, part2: boolean): ChartToken {
  if (part2) return t.chartPart2;
  return t.chart[((index % t.chart.length) + t.chart.length) % t.chart.length];
}

/** Memoised layout-only styles shared by the editor sections. */
export function useLayout() {
  const { phone } = useUi();
  return useMemo(() => ({
    // Phones: the panel cancels the page card's 14px padding on the web so cards sit ~8px from the screen edge, and keeps its own 8px gutter.
    panel: phone ? { borderWidth: 0, borderRadius: 0, padding: gap.sm, ...(isWeb ? { marginHorizontal: -14 } : {}) } as ViewStyle : {} as ViewStyle,
    row: { flexDirection: "row", alignItems: "center", gap: gap.md, flexWrap: "wrap" } as ViewStyle,
    nowrap: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: gap.sm, flexWrap: "nowrap" } as ViewStyle,
    // 8px apart: the 4px hit-slop of two neighbouring 36px buttons then meets without overlapping.
    iconRow: { flexDirection: "row", alignItems: "center", gap: gap.sm, flexShrink: 0 } as ViewStyle,
    // Cells are row items (flexBasis is their width). Anything with flexGrow or flexBasis inside a cell must itself be in a
    // row: in a column Yoga reads them as a height, and with RN's legacy stretch errata a growing child fills the height it was offered.
    grid: { flexDirection: "row", flexWrap: "wrap", gap: gap.md } as ViewStyle,
    cell: { flexGrow: 1, flexBasis: 240, minWidth: 0, gap: gap.xs } as ViewStyle,
    stack: { gap: gap.xs } as ViewStyle,
    dim: { opacity: 0.45 } as ViewStyle,
  }), [phone]);
}
