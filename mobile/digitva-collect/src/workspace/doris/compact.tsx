import { useEffect, useRef, useState, type ReactNode } from "react";
import { Platform, Pressable, TextInput, View, useWindowDimensions, type TextStyle, type ViewStyle } from "react-native";
import Svg, { Circle, Line } from "react-native-svg";

import { ui as uiTokens, type ColorMode } from "../../theme";
import { INTERVAL_UNITS, UNKNOWN_UNIT, parseInterval, serializeInterval } from "./interval";
import { unitTooLarge, type Age } from "./rules";
import { FieldError, FieldHint, FieldWarning, HIT_SLOP, Input, Label, Badge, MenuSelect, RING_ROOM, RadioGroup, RadioRow, chartFor, font, gap, uiRadius, useLayout, useUi } from "./ui";

export interface LineShade {
  /** Card left bar and the colour handed to the picker header. */
  bar: string;
  /** Light header tint. */
  tint: string;
  chipBg: string;
  chipText: string;
}

/** Distinct colour family per certificate line (chart-1..5 tokens; Part II slate). */
export function lineShade(mode: ColorMode, index: number, part2: boolean): LineShade {
  const chart = chartFor(uiTokens[mode], index, part2);
  return { bar: chart.bar, tint: chart.tint, chipBg: chart.soft, chipText: chart.foreground };
}

/** Soft warning under the field it concerns; never blocks anything. */
export function Warn({ text, id }: { text?: string; id: string }) {
  return text ? <FieldWarning testID={`warn-${id}`}>{text}</FieldWarning> : null;
}

/** Characters and pause after which the search box opens the picker by itself. */
export const AUTO_SEARCH_MIN_CHARS = 3;
export const AUTO_SEARCH_DELAY_MS = 500;

/**
 * Empty text input with a magnifier on its right. Enter or the icon opens the
 * picker on the typed term (empty: search focused); the box clears on open so
 * it is empty again when the picker closes. Typing 3 or more characters and
 * pausing opens it the same way; `suspended` (a picker is already open) holds that off.
 */
export function SearchBox({ label, iconLabel, onOpen, suspended = false }: { label: string; iconLabel: string; onOpen: (query: string) => void; suspended?: boolean }) {
  const { t, controlHeight } = useUi();
  const [text, setText] = useState("");
  const [focused, setFocused] = useState(false);
  const open = () => { const query = text.trim(); setText(""); onOpen(query); };
  // Each keystroke restarts the pause; emptying the box, unmounting or a picker opening cancels it.
  useEffect(() => {
    if (suspended || text.trim().length < AUTO_SEARCH_MIN_CHARS) return undefined;
    const timer = setTimeout(open, AUTO_SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [text, suspended]);
  return (
    <View style={{ flexDirection: "row", alignItems: "center", flexGrow: 1, flexShrink: 1, minWidth: 200, height: controlHeight, borderWidth: 1, borderColor: focused ? t.ring : t.input, borderRadius: uiRadius.md, backgroundColor: t.background }}>
      <TextInput accessibilityLabel={label} placeholder="Search a condition or ICD-11 code" placeholderTextColor={t.mutedForeground} value={text} maxLength={80} onChangeText={setText} onSubmitEditing={open} onFocus={() => setFocused(true)} onBlur={() => setFocused(false)} returnKeyType="search" style={{ flex: 1, minWidth: 0, minHeight: controlHeight - 2, paddingHorizontal: gap.md, paddingVertical: gap.xs, fontSize: font.body, color: t.foreground, ...(Platform.OS === "web" ? { outlineStyle: "none" } : {}) } as TextStyle} />
      <Pressable accessibilityRole="button" accessibilityLabel={iconLabel} hitSlop={HIT_SLOP} onPress={open} style={{ width: 40, height: controlHeight - 2, alignItems: "center", justifyContent: "center" }}>
        <Svg width={16} height={16} viewBox="0 0 18 18">
          <Circle cx={7.5} cy={7.5} r={5.25} stroke={t.mutedForeground} strokeWidth={1.8} fill="none" />
          <Line x1={11.5} y1={11.5} x2={16} y2={16} stroke={t.mutedForeground} strokeWidth={1.8} strokeLinecap="round" />
        </Svg>
      </Pressable>
    </View>
  );
}

/** Vector ✕ icon button (44px target) that clears a field; drawn like the SearchBox magnifier. */
export function ClearButton({ label, onPress, size = 44, style }: { label: string; onPress: () => void; size?: number; style?: ViewStyle }) {
  const { t } = useUi();
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={label} hitSlop={HIT_SLOP} onPress={onPress} style={[{ width: size, height: size, alignItems: "center", justifyContent: "center", flexShrink: 0 }, style]}>
      <Svg width={14} height={14} viewBox="0 0 14 14">
        <Line x1={2} y1={2} x2={12} y2={12} stroke={t.mutedForeground} strokeWidth={1.8} strokeLinecap="round" />
        <Line x1={12} y1={2} x2={2} y2={12} stroke={t.mutedForeground} strokeWidth={1.8} strokeLinecap="round" />
      </Svg>
    </Pressable>
  );
}

/** `badge` is the provenance text, for example "from interview (Id10077)"; `onClear` (only while the field has a value) draws the ✕ at the right of the row. */
export function FieldLabel({ text, badge, onClear }: { text: string; badge?: string; onClear?: () => void }) {
  const layout = useLayout();
  return (
    // flexGrow: in a stretched grid cell the label block takes the spare height, so the control under it lines up across the row.
    <View style={{ flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", gap: gap.sm, flexGrow: 1 }}>
      <View style={[layout.row, { flex: 1, minWidth: 0 }]}>
        <Label>{text}</Label>
        {badge ? <Badge variant="secondary">{badge}</Badge> : null}
      </View>
      {/* 44px target in a 20px label line: the negative margin keeps the row height. */}
      {onClear ? <ClearButton label={`Clear ${text}`} onPress={onClear} style={{ marginVertical: -12 }} /> : null}
    </View>
  );
}

export function Cell({ children }: { children: ReactNode }) {
  return <View style={useLayout().cell}>{children}</View>;
}

/** Labels longer than this keep one column on phones, as in the WHO control. */
const LONG_LABEL = 28;
/** Pixels of one character at 16px, deliberately generous: a word that does not fit its cell would overflow the row. */
const CHAR_PX = 8.5;
/** Row chrome around the label: 12px padding twice, 2px border, 22px circle, 12px gap. */
const ROW_CHROME_PX = 62;

/**
 * Columns of a choice group. Before the group is measured (`inner` 0) the window stands in: phones 2, or 1 when any
 * label is long; wide screens one per option for up to four short options, else 3 columns for short labels and 2
 * for long ones. Once measured, the group's own width decides: the most columns (within that cap) in which every
 * label's longest word still fits its cell, else 1. A squeezed group in a narrow grid cell therefore drops to 1 column.
 */
export function choiceColumns(width: number, labels: ReadonlyArray<string>, inner = 0): number {
  const long = labels.some((label) => [...label].length > LONG_LABEL);
  const cap = width < 768 ? (long ? 1 : 2) : labels.length <= 4 && !long ? Math.max(labels.length, 1) : long ? 2 : 3;
  if (inner <= 0) return cap;
  const longestWord = Math.max(0, ...labels.flatMap((label) => label.split(/\s+/).map((word) => [...word].length)));
  for (let columns = cap; columns > 1; columns -= 1) {
    const cell = (inner - gap.md * (columns - 1)) / columns;
    if (longestWord * CHAR_PX <= cell - ROW_CHROME_PX) return columns;
  }
  return 1;
}

/**
 * Labelled single choice in the Narrative-quality (WHO) row style; the first option is the unset state.
 * Cells are measured px widths of an equal grid with 12px gaps; before the first layout (and in tests) a percentage fallback is used.
 */
export function ChipChoice({ name, label, value, options, onChange, badge, disabled, onClear }: { name: string; label: string; value: string; options: ReadonlyArray<{ value: string; label: string }>; onChange: (value: string) => void; badge?: string; disabled?: boolean; onClear?: () => void }) {
  const { width } = useWindowDimensions();
  const [inner, setInner] = useState(0);
  const columns = choiceColumns(width, options.map((option) => option.label), inner);
  const cell = inner > 0 ? Math.floor((inner - gap.md * (columns - 1)) / columns) : undefined;
  const style: ViewStyle = cell ? { width: cell } : { flexBasis: `${Math.floor(100 / columns) - 3}%`, flexGrow: 1 };
  return (
    <View style={[{ gap: gap.md }, disabled && { opacity: 0.5 }]}>
      <FieldLabel text={label} badge={badge} onClear={onClear} />
      <RadioGroup onLayout={(event) => setInner(event.nativeEvent.layout.width - 2 * RING_ROOM)}>
        {options.map((option) => {
          const on = value === option.value;
          return <RadioRow key={option.value} label={option.label} selected={on} style={style} accessibilityLabel={`${label}: ${option.label}`} accessibilityState={{ selected: on, disabled: Boolean(disabled) }} testID={`question-${name}-choice-${option.value}`} disabled={disabled} onPress={() => onChange(option.value)} />;
        })}
      </RadioGroup>
    </View>
  );
}

/**
 * Number + unit editor for an ISO 8601 duration. Partial input stays local;
 * only a valid pair is written back, and a stored value the pickers cannot
 * represent is shown read-only until the user edits.
 */
/**
 * `onTyped` reports whether the coder has typed a number or picked a unit, even an incomplete pair that emits
 * nothing useful (a number without a unit). The panel holds that flag so a date change never refills over it
 * (the web's mayRefillAge rule). It reads false again when the value is replaced from outside.
 */
export function IntervalField({ raw, onChange, onTyped, inputLabel, unitLabel, placeholder = "Number", unitPlaceholder = "Time unit", label, age }: { raw: string; onChange: (value: string) => void; onTyped?: (typed: boolean) => void; inputLabel: string; unitLabel: string; placeholder?: string; unitPlaceholder?: string; label?: string; age?: Age | null }) {
  const layout = useLayout();
  const parsed = parseInterval(raw);
  const [number, setNumber] = useState(parsed.representable ? parsed.value : "");
  const [unit, setUnit] = useState(parsed.representable ? parsed.unit : "");
  const [error, setError] = useState("");
  const [edited, setEdited] = useState(false);
  const emitted = useRef(raw);

  useEffect(() => {
    if (raw === emitted.current) return;
    emitted.current = raw;
    const next = parseInterval(raw);
    setNumber(next.representable ? next.value : "");
    setUnit(next.representable ? next.unit : "");
    setEdited(false);
    setError("");
    onTyped?.(false);
  }, [raw]);

  const commit = (nextNumber: string, nextUnit: string) => {
    setNumber(nextNumber);
    setUnit(nextUnit);
    setEdited(true);
    onTyped?.(nextNumber.trim() !== "" || nextUnit !== "");
    // A unit without a number yet is a pending edit, not an error; it clears the stored value.
    const result = nextNumber.trim() === "" ? { value: "", error: "" } : serializeInterval(nextNumber, nextUnit);
    setError(result.error);
    if (result.error) return;
    emitted.current = result.value;
    onChange(result.value);
  };

  const unitName = unit === UNKNOWN_UNIT ? "Unknown" : INTERVAL_UNITS.find((item) => item.value === unit)?.label ?? unitPlaceholder;
  const unitOptions = [
    ...INTERVAL_UNITS.map((item) => ({ value: item.value as string, label: item.label as string, accessibilityLabel: `${unitLabel}: ${item.label}`, dimmed: unitTooLarge(item.value, age ?? null) })),
    { value: UNKNOWN_UNIT, label: "Unknown", accessibilityLabel: `${unitLabel}: Unknown`, dimmed: false },
  ];
  return (
    <View style={{ gap: gap.xs, flexShrink: 1, maxWidth: "100%" }}>
      <View style={layout.row}>
        {label ? <Label>{label}</Label> : null}
        <Input accessibilityLabel={inputLabel} placeholder={placeholder} keyboardType="decimal-pad" maxLength={24} value={number} onChangeText={(next) => commit(next, unit)} style={{ width: 104 }} />
        <MenuSelect triggerLabel={unitLabel} valueText={unitName} options={unitOptions} selected={unit} onSelect={(next) => commit(next === UNKNOWN_UNIT ? "" : number, next)} />
      </View>
      {!parsed.representable && raw && !edited ? <FieldHint>{`Existing value: ${raw}`}</FieldHint> : null}
      {error ? <FieldError>{error}</FieldError> : null}
    </View>
  );
}
