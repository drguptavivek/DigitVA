/**
 * Tiny DORIS UI kit: shadcn/ui's tokens and composition ideas on plain React Native
 * components. No UI library; variants are small style maps (the cva idea).
 * Token table and rules: docs/current-state/doris-ui-tokens.md.
 */
import { useMemo, useState, type ComponentProps, type ReactNode } from "react";
import { ActivityIndicator, Platform, Pressable, Text, TextInput, View, useWindowDimensions, type StyleProp, type TextStyle, type ViewStyle } from "react-native";

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

export function Badge({ variant = "secondary", children }: { variant?: BadgeVariant; children: ReactNode }) {
  const { t } = useUi();
  const tone = badgeTone(t, variant);
  return (
    <View style={{ alignSelf: "flex-start", borderRadius: uiRadius.full, borderWidth: 1, borderColor: tone.border, backgroundColor: tone.bg, paddingHorizontal: gap.sm - 2, paddingVertical: 1, flexShrink: 1 }}>
      <Text style={{ fontSize: font.caption, lineHeight: 16, fontWeight: "600", color: tone.fg }}>{children}</Text>
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
      {children ?? <Text style={{ fontSize: font.body, lineHeight: 20, fontWeight: "500", color: tone.fg }}>{label}</Text>}
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
    iconRow: { flexDirection: "row", alignItems: "center", gap: gap.xs, flexShrink: 0 } as ViewStyle,
    grid: { flexDirection: "row", flexWrap: "wrap", gap: gap.md } as ViewStyle,
    cell: { flexGrow: 1, flexBasis: 240, minWidth: 0, gap: gap.xs } as ViewStyle,
    stack: { gap: gap.xs } as ViewStyle,
    dim: { opacity: 0.45 } as ViewStyle,
  }), [phone]);
}
