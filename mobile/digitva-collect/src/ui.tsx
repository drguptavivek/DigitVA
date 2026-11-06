/** Shared screen chrome and controls. */
import type { ReactNode } from "react";
import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { AccessibilityInfo, ActivityIndicator, findNodeHandle, Platform, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View, useWindowDimensions, type StyleProp, type SwitchProps, type TextInputProps, type ViewStyle } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { ApiError } from "./api";
import { APP_VERSION } from "./appVersion";
import { AccountStoreCollisionError, AlreadyEnrolledError, NotInSlotError, SessionRevokedError, SignInRequiredError } from "./authErrors";
import { describeError, recordError } from "./errorLog";
import { Icon, icons, type IconName } from "./Icon";
import { isStorageFull } from "./storageErrors";
import { t, type StringKey } from "./i18n";
import { useShell } from "./nativeShell/shellContext";
import { CheckboxBox } from "./ui/controls";
import { BUTTON_MIN_WIDTH, SWITCH_THUMB, buttonTone, controlText, disabledButtonTone, controls, getTheme, radius, spacing, useTheme, type ButtonSize, type ButtonVariant, type Theme } from "./theme";

/** Same phone breakpoint as the DORIS kit. */
const PHONE_BREAKPOINT = 768;

export function Screen({
  title,
  children,
  scroll = true,
  sidebar,
  headerAction,
  footer,
  lead,
  variant = "standard",
  wide = false
}: {
  title: string;
  children: ReactNode;
  scroll?: boolean;
  sidebar?: ReactNode;
  headerAction?: ReactNode;
  footer?: ReactNode;
  /** With scroll: rendered at the top of the scroller, and the title row moves into the scroller under it, so both
   * scroll away with the page (the browser interview's header bar; the phone Home's logo block). */
  lead?: ReactNode;
  /** "immersive": no title bar, no dev banner, no padding or max width; `children` own the full height (the
   * interview and revision forms put their one compact top bar first). */
  variant?: "standard" | "immersive";
  /** Lift the 720px reading width so a table can use the whole page (the Users list). */
  wide?: boolean;
}) {
  const theme = useTheme();
  const screenStyles = useUiStyles();
  // The phone header and tabs pad the status and navigation bars themselves; Screen must not pad them again.
  const shell = useShell();
  const edges = (["top", "bottom", "left", "right"] as const).filter((edge) => !(edge === "top" && shell.header) && !(edge === "bottom" && shell.tabs));
  // The phone bar shows the title of a pushed screen next to its back arrow (src/nativeShell/shell.tsx).
  const titleKey = useRef({}).current;
  const { publishTitle } = shell;
  useEffect(() => publishTitle(titleKey, title), [publishTitle, titleKey, title]);
  useEffect(() => () => publishTitle(titleKey, undefined), [publishTitle, titleKey]);
  // A new screen puts the screen reader on its title (in the phone bar, NativeChrome does it).
  const titleRef = useRef<Text>(null);
  const titleOnPage = variant !== "immersive" && !shell.titleInBar;
  useEffect(() => {
    if (titleOnPage) focusForAccessibility(titleRef.current);
  }, [titleOnPage]);
  if (variant === "immersive") {
    return (
      <SafeAreaView style={[screenStyles.safe, { backgroundColor: theme.colors.background }]}>
        <View style={screenStyles.fill}>{children}</View>
        {footer ? <View style={screenStyles.footer}>{footer}</View> : null}
      </SafeAreaView>
    );
  }
  const widen = wide ? { maxWidth: "100%" as const } : null;
  // With the title in the phone bar, the page keeps only the header action (right-aligned), or no title row at all.
  const titleNode = shell.titleInBar ? (
    headerAction ? (
      <View style={[screenStyles.titleWrap, widen]}>
        <View style={[screenStyles.titleBar, { justifyContent: "flex-end" }]}>{headerAction}</View>
      </View>
    ) : null
  ) : (
    <View style={[screenStyles.titleWrap, widen]}>
      <View style={screenStyles.titleBar}>
        <Text ref={titleRef} style={[screenStyles.title, { color: theme.colors.text }]} accessibilityRole="header">
          {title}
        </Text>
        {headerAction}
      </View>
    </View>
  );
  const body = sidebar ? (
    <View style={[screenStyles.frame, { backgroundColor: theme.colors.background }]}>
      {sidebar}
      <View style={screenStyles.mainColumn}>
        {lead && scroll ? (
          <ScrollView automaticallyAdjustKeyboardInsets keyboardDismissMode="on-drag" keyboardShouldPersistTaps="handled" style={screenStyles.mainScroll}>
            {lead}
            {titleNode}
            <View style={[screenStyles.body, widen, { backgroundColor: theme.colors.background }]}>{children}</View>
          </ScrollView>
        ) : (
          <>
            {titleNode}
            {scroll ? (
              <ScrollView automaticallyAdjustKeyboardInsets keyboardDismissMode="on-drag" keyboardShouldPersistTaps="handled" style={screenStyles.mainScroll} contentContainerStyle={[screenStyles.body, widen, { backgroundColor: theme.colors.background }]}>
                {children}
              </ScrollView>
            ) : (
              <View style={[screenStyles.body, widen, screenStyles.mainScroll, { backgroundColor: theme.colors.background }]}>
                {children}
              </View>
            )}
          </>
        )}
      </View>
    </View>
  ) : scroll ? (
    // The title row scrolls with the fields (a pinned title clipped the form under it on phones).
    <ScrollView automaticallyAdjustKeyboardInsets keyboardDismissMode="on-drag" keyboardShouldPersistTaps="handled">
      {lead}
      {titleNode}
      <View style={[screenStyles.body, widen, { backgroundColor: theme.colors.background }]}>{children}</View>
    </ScrollView>
  ) : (
    <View style={[screenStyles.body, widen, screenStyles.fill, { backgroundColor: theme.colors.background }]}>{children}</View>
  );
  return (
    <SafeAreaView edges={edges} style={[screenStyles.safe, { backgroundColor: theme.colors.background }]}>
      {__DEV__ ? (
        <Text
          style={[screenStyles.debug, { backgroundColor: theme.colors.warning, color: theme.colors.onAccent }]}
          accessibilityRole="alert"
        >
          {t("debugWarning")}
        </Text>
      ) : null}
      {!sidebar && !scroll ? titleNode : null}
      {body}
      {footer ? <View style={screenStyles.footer}>{footer}</View> : null}
    </SafeAreaView>
  );
}

/** Legacy `kind` names of the queue and native routes, mapped onto the kit's variants (secondary is tint-filled). */
const KIND_VARIANT = { primary: "default", secondary: "secondary", danger: "destructive" } as const;

/**
 * The app's one button: the DORIS kit's variants (default, secondary, ghost, destructive; `outline` is retired and
 * draws as secondary) and sizes (default 48pt, sm 36pt for in-row actions with a 44pt hit area, icon), no border,
 * 6px radius, 72px minimum width, the focus ring on the web. `kind` stays as an alias of `variant` for existing callers.
 */
export function Button({
  label,
  onPress,
  kind,
  variant = kind ? KIND_VARIANT[kind] : "default",
  size = "default",
  disabled,
  loading = false,
  accessibilityLabel,
  expanded,
  selected,
  style,
  testID
}: {
  label: string;
  onPress: () => void;
  testID?: string;
  kind?: "primary" | "secondary" | "danger";
  variant?: ButtonVariant;
  size?: ButtonSize;
  disabled?: boolean;
  loading?: boolean;
  accessibilityLabel?: string;
  /** Set on a button that shows or hides a section, so screen readers hear its state. */
  expanded?: boolean;
  /** Set on a button that is one tab of a tablist, so screen readers hear it as a tab and whether it is selected. */
  selected?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  const theme = useTheme();
  const styles = useUiStyles();
  const [focused, setFocused] = useState(false);
  const height = size === "sm" ? controls.compactHeight : controls.minHeight;
  const disabledOrBusy = Boolean(disabled || loading);
  // Petrol has no outlined control: the retired `outline` variant draws as the tint-filled secondary.
  const look: ButtonVariant = variant === "outline" ? "secondary" : variant;
  // Disabled (not busy) filled buttons keep the primary tint with a faded label that still reads at 4.5:1.
  const filled = look === "default" || look === "secondary";
  const tone = disabled && !loading && filled ? disabledButtonTone(theme.ui) : buttonTone(theme.ui, look);
  const dimmed = disabled && !loading && !filled;
  return (
    <Pressable
      testID={testID}
      accessibilityRole={selected === undefined ? "button" : "tab"}
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityState={{ disabled: disabledOrBusy, busy: loading, expanded, selected }}
      disabled={disabledOrBusy}
      // 4pt all round: a 36pt small button still has a 44pt target.
      hitSlop={spacing.xxs}
      onPress={onPress}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      style={({ pressed }) => [
        styles.button,
        { minHeight: height, backgroundColor: tone.bg, borderColor: tone.border, opacity: dimmed ? 0.5 : pressed ? 0.85 : 1 },
        size === "sm" && { paddingHorizontal: spacing.sm },
        size === "icon" && { minWidth: height, paddingHorizontal: 0 },
        focused && Platform.OS === "web" && ({ outlineStyle: "solid", outlineWidth: theme.focusWidth, outlineColor: theme.ui.ring, outlineOffset: 2 } as ViewStyle),
        style
      ]}
    >
      <Text style={[styles.buttonText, { color: tone.fg }]}>{label}</Text>
      {/* Absolute, so the button keeps its width while busy. */}
      {loading ? <ActivityIndicator size="small" color={tone.fg} style={styles.buttonSpinner} /> : null}
    </Pressable>
  );
}

/** Set by ListRow around its `trailing` control: a TextLink there defaults to the small in-row size. */
const TrailingContext = createContext(false);

/**
 * A quiet action as text: body size, medium weight, primary (red with `tone="destructive"`, never grey), left-aligned,
 * 44pt target. The secondary ways in beside a screen's one button. `size="sm"`: caption size, semibold, the in-row
 * action size (Allow, Remove, Sign out); a TextLink in a ListRow's `trailing` slot is "sm" unless it says otherwise.
 */
export function TextLink({ label, onPress, disabled = false, accessibilityLabel, tone, testID, size }: {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  accessibilityLabel?: string;
  tone?: "destructive";
  testID?: string;
  size?: "sm" | "default";
}) {
  const { ui: tokens, typography } = useTheme();
  const inRow = useContext(TrailingContext);
  const small = (size ?? (inRow ? "sm" : "default")) === "sm";
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => ({ minHeight: controls.minTouchTarget, minWidth: controls.minTouchTarget, justifyContent: "center", alignItems: "flex-start", alignSelf: "flex-start", opacity: disabled ? 0.5 : pressed ? 0.7 : 1 })}
    >
      <Text style={{ ...(small ? typography.caption : typography.body), fontWeight: small ? "600" : "500", color: tone === "destructive" ? tokens.destructiveText : tokens.primary, fontFamily: controls.fontFamily }}>{label}</Text>
    </Pressable>
  );
}

/**
 * The app's one switch: primary track when on, border track when off, a white thumb (Android draws Material teal
 * and grey otherwise). Every prop passes through, so callers keep their role, label and hint.
 */
export function ThemedSwitch(props: SwitchProps) {
  const { ui: t } = useTheme();
  return <Switch trackColor={{ false: t.border, true: t.primary }} thumbColor={SWITCH_THUMB} ios_backgroundColor={t.border} {...props} />;
}

/** Fields and full-width buttons: 48pt everywhere (above the 44pt minimum touch target). */
export function useControlHeight(): number {
  return controls.minHeight;
}

/** A section's caption above its card: small, semibold, upper case, secondary, a little tracking. */
export function SectionLabel({ children }: { children: string }) {
  const { ui: t, typography } = useTheme();
  return (
    <Text accessibilityRole="header" style={{ ...typography.caption, fontWeight: "600", textTransform: "uppercase", letterSpacing: 0.6, color: t.mutedForeground, fontFamily: controls.fontFamily, paddingHorizontal: spacing.md, paddingTop: spacing.xs }}>
      {children}
    </Text>
  );
}

/** A field's helper line (format, example, what it is for): secondary text under the field, never a Notice. */
export function FieldHint({ children, testID }: { children: string; testID?: string }) {
  const { ui: t, typography } = useTheme();
  return <Text testID={testID} style={{ ...typography.subhead, color: t.mutedForeground, fontFamily: controls.fontFamily }}>{children}</Text>;
}

/**
 * A form question's label (body size, semibold, ink). `required` adds the grey "Required" word after it at the
 * secondary size (never an asterisk), until the screen shows the field's red message instead.
 */
export function FieldLabel({ label, required = false, testID }: { label: string; required?: boolean; testID?: string }) {
  const s = useUiStyles();
  const { ui: tokens, typography } = useTheme();
  return (
    <Text testID={testID} style={s.fieldLabel}>
      {label}
      {required ? <Text style={{ fontSize: typography.subhead.fontSize, fontWeight: "400", color: tokens.mutedForeground }}>{`  ${t("fieldRequiredMark")}`}</Text> : null}
    </Text>
  );
}

/**
 * A text field with the shared look: a fill with no edge (`onCard`: the neutral tone, for a field inside a white
 * card), the focus ring only while typing in it, the error tint when `invalid`.
 */
export function TextField({ onCard = false, invalid = false, style, onFocus, onBlur, ...input }: TextInputProps & { onCard?: boolean; invalid?: boolean }) {
  const s = useUiStyles();
  const { ui: tokens } = useTheme();
  const [focused, setFocused] = useState(false);
  return (
    <TextInput
      placeholderTextColor={tokens.mutedForeground}
      {...input}
      onFocus={(event) => { setFocused(true); onFocus?.(event); }}
      onBlur={(event) => { setFocused(false); onBlur?.(event); }}
      style={[s.input, onCard && s.inputOnCard, invalid && s.inputError, focused && s.inputFocused, style]}
    />
  );
}

export function Row({ children }: { children: ReactNode }) {
  return <View style={styles.row}>{children}</View>;
}

/** Set by a grouped Card whose rows mix chevron and plain rows: every ListRow keeps the chevron's slot. */
const ChevronSlotContext = createContext(false);
/** Set by every Card: a SegmentedControl on the white card marks its choice with the primary tint, not white. */
const InCardContext = createContext(false);

/**
 * A borderless card. `grouped`: rows (ListRow, ChoiceRow) run edge to edge inside it and `Separator` splits them;
 * the shadow sits on an outer view so the inner one can clip the rows to the rounded corners. `label`: the section
 * caption above the card; `footer`: the group's explanation under it (never prose inside the card). `chevronSlot`:
 * every row reserves the chevron's width, so the values of chevron and plain rows line up.
 */
export function Card({ children, grouped = false, style, testID, label, footer, chevronSlot = false }: {
  children: ReactNode;
  grouped?: boolean;
  style?: StyleProp<ViewStyle>;
  testID?: string;
  label?: string;
  footer?: ReactNode;
  chevronSlot?: boolean;
}) {
  const s = useUiStyles();
  const card = !grouped ? <View testID={testID} style={[s.card, style]}><InCardContext.Provider value>{children}</InCardContext.Provider></View> : (
    <View testID={testID} style={[s.group, style]}>
      <ChevronSlotContext.Provider value={chevronSlot}>
        <InCardContext.Provider value>
          <View style={{ borderRadius: radius.lg, overflow: "hidden" }}>{children}</View>
        </InCardContext.Provider>
      </ChevronSlotContext.Provider>
    </View>
  );
  if (!label && footer === undefined) return card;
  return (
    <View style={{ gap: spacing.xs }}>
      {label ? <SectionLabel>{label}</SectionLabel> : null}
      {card}
      {typeof footer === "string" ? <View style={{ paddingHorizontal: spacing.md }}><FieldHint>{footer}</FieldHint></View> : footer ? <View style={{ paddingHorizontal: spacing.md }}>{footer}</View> : null}
    </View>
  );
}

/** The inset hairline between two rows of a grouped card, starting at the text (`icon`: after a row's 24pt glyph; `choice`: after a ChoiceRow's ring). */
export function Separator({ icon = false, choice = false }: { icon?: boolean; choice?: boolean }) {
  const s = useUiStyles();
  return <View style={[s.separator, icon && { marginLeft: ICON_TEXT_START }, choice && { marginLeft: CHOICE_TEXT_START }]} />;
}

/** Row height: 48pt for one line, 56pt with a second line (a Hindi label or a detail). */
const rowHeight = (twoLines: boolean) => (twoLines ? 56 : 48);

/** Width of the right-aligned count column, so the numbers of a card line up. */
const COUNT_COLUMN = 48;
/** The trailing chevron's slot, kept on every row of a `chevronSlot` card. */
const CHEVRON_SLOT = 24;
/** Where a row's text starts after its 24pt glyph: 16 padding + 24 glyph + 16 (the row gap plus 4). */
const ICON_TEXT_START = 56;
/** Where a ChoiceRow's label starts: 16 padding + 22 ring + 12 gap. */
const CHOICE_TEXT_START = spacing.md + 22 + spacing.sm;
const monoFont = Platform.select({ ios: "Menlo", android: "monospace", default: "ui-monospace, Menlo, monospace" });

/**
 * A row of a grouped card: label, optional second line and trailing value; tappable when `onPress`. The chevron
 * shows only on rows that push a screen or open a picker (`chevron`, default: when tappable); an action row (Lock
 * now, Sign out) passes `chevron={false}`. `numeric`: the value is a count, right-aligned in a fixed tabular column.
 * `tone="attention"`: the accent tint (Unsent on Home). `badge`: the value as an amber filled badge with ink text
 * (amber is never text on its own). `trailing`: a control at the row's end (a Switch, a TextLink). A plain value
 * takes the room the label leaves, on one line, middle-ellipsised ("2201fd01…28ba9"); the label never shrinks
 * below its words. `action`: the row does something (Export errors, Check for updates): primary label, no chevron.
 */
export function ListRow({ label, secondary, secondaryLanguage, secondaryTone, value, onPress, accessibilityLabel, testID, numeric = false, tone, badge = false, icon, tile = false, disabled = false, chevron, trailing, mono = false, onLongPress, action = false, emphasis = false }: {
  label: string;
  secondary?: string;
  /** BCP 47 language of `secondary` when it differs from the screen's (a Hindi line on an English screen): "hi-IN". */
  secondaryLanguage?: string;
  /** `destructive`: the second line is a failure ("Could not reach the server"). */
  secondaryTone?: "destructive";
  value?: string;
  onPress?: () => void;
  accessibilityLabel?: string;
  testID?: string;
  numeric?: boolean;
  /** `attention`: the accent tint row; `destructive`: red label (Sign out), the one red that is not an error. */
  tone?: "attention" | "destructive";
  badge?: boolean;
  /** A leading 24pt glyph in primary; with `tile`, on a 48pt primary-tint square (only the Welcome option rows). */
  icon?: IconName;
  tile?: boolean;
  /** A tappable row that cannot be used now: greyed label, no press. */
  disabled?: boolean;
  chevron?: boolean;
  trailing?: ReactNode;
  /** The value is a reference string (server, device ID): monospace at the secondary size. */
  mono?: boolean;
  onLongPress?: () => void;
  /** An action row: the label in primary (secondary while disabled), never a chevron. */
  action?: boolean;
  /** A semibold label: the row names a person or a thing to open (the profiles list). */
  emphasis?: boolean;
}) {
  const { ui: t, typography, textScale } = useTheme();
  const slot = useContext(ChevronSlotContext);
  const showChevron = !action && (chevron ?? Boolean(onPress));
  // A plain value shares the row with the label; a badge or a count keeps its fixed column instead.
  const plainValue = Boolean(value) && !badge && !numeric;
  const valueText = { ...typography.body, color: t.foreground, fontFamily: controls.fontFamily };
  const countText = { ...valueText, fontWeight: "600" as const, fontVariant: ["tabular-nums" as const], textAlign: "right" as const };
  const valueNode = !value ? null : badge ? (
    <View style={{ minWidth: COUNT_COLUMN, alignItems: "flex-end" }}>
      <View style={{ minWidth: 32, minHeight: 32, paddingHorizontal: spacing.xs, borderRadius: radius.full, backgroundColor: t.attention, alignItems: "center", justifyContent: "center" }}>
        <Text style={{ ...countText, color: t.onAttention, textAlign: "center" }}>{value}</Text>
      </View>
    </View>
  ) : numeric ? (
    <Text style={[countText, { minWidth: COUNT_COLUMN * textScale }]}>{value}</Text>
  ) : mono ? (
    <Text numberOfLines={1} ellipsizeMode="middle" style={{ ...typography.subhead, color: t.mutedForeground, fontFamily: monoFont, flex: 1, minWidth: 0, textAlign: "right" }}>{value}</Text>
  ) : (
    <Text numberOfLines={1} ellipsizeMode="middle" style={{ ...valueText, flex: 1, minWidth: 0, textAlign: "right" }}>{value}</Text>
  );
  const ink = disabled ? t.mutedForeground : action ? t.primary : tone === "destructive" ? t.destructiveText : t.foreground;
  const content = (
    <>
      {icon && tile ? (
        <View style={{ width: 48, height: 48, borderRadius: radius.lg, backgroundColor: t.primaryTint, alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
          <Icon name={icon} color={disabled ? t.mutedForeground : t.primary} size={24} />
        </View>
      ) : icon ? (
        <View style={{ marginRight: spacing.xxs }}>
          <Icon name={icon} color={disabled ? t.mutedForeground : t.primary} size={24} />
        </View>
      ) : null}
      {/* Beside a plain value the label keeps its words whole (at most 70% of the row: a huge text size wraps it at
          a space, never mid-word); otherwise it fills the row so the chevron sits at the end. */}
      <View style={plainValue ? { flexShrink: 0, maxWidth: "70%" } : { flex: 1, minWidth: 0 }}>
        <Text style={{ ...typography.body, color: ink, fontWeight: emphasis ? "600" : "400", fontFamily: controls.fontFamily }}>{label}</Text>
        {secondary ? <Text accessibilityLanguage={secondaryLanguage} style={{ ...typography.subhead, color: secondaryTone === "destructive" && !disabled ? t.destructiveText : t.mutedForeground, fontFamily: controls.fontFamily }}>{secondary}</Text> : null}
      </View>
      {valueNode}
      {trailing ? <TrailingContext.Provider value>{trailing}</TrailingContext.Provider> : null}
      {showChevron || slot ? (
        <View style={{ width: CHEVRON_SLOT, alignItems: "flex-end" }}>{showChevron ? <Icon name={icons.chevronRight} color={t.mutedForeground} size={16} /> : null}</View>
      ) : null}
    </>
  );
  const fill = tone === "attention" ? t.attentionTint : undefined;
  const rowStyle: ViewStyle = { minHeight: rowHeight(Boolean(secondary)) * Math.max(1, textScale), flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingHorizontal: spacing.md, paddingVertical: spacing.xs, backgroundColor: fill };
  if (!onPress) return <View testID={testID} style={rowStyle}>{content}</View>;
  return (
    <Pressable testID={testID} accessibilityRole="button" accessibilityLabel={accessibilityLabel ?? [label, secondary, value].filter(Boolean).join(", ")} accessibilityState={{ disabled }} disabled={disabled} onPress={onPress} onLongPress={onLongPress} style={({ pressed }) => [rowStyle, pressed && { backgroundColor: t.muted }]}>
      {content}
    </Pressable>
  );
}

/**
 * One radio or checkbox answer: the whole row is the target, selected = primary tint fill and a semibold label,
 * never an edge. `secondaryLabel` is the second language, in the same ink (weight, not grey, makes it secondary).
 */
export function ChoiceRow({ label, secondaryLabel, secondaryLanguage, selected, onPress, role = "radio", disabled = false, testID }: {
  label: string;
  secondaryLabel?: string;
  /** BCP 47 language of `secondaryLabel` when it differs from the screen's: "hi-IN". */
  secondaryLanguage?: string;
  selected: boolean;
  onPress: () => void;
  role?: "radio" | "checkbox";
  disabled?: boolean;
  testID?: string;
}) {
  const { ui: t, typography, textScale } = useTheme();
  const ink = disabled ? t.disabled : t.foreground;
  return (
    <Pressable
      testID={testID}
      accessibilityRole={role}
      accessibilityLabel={secondaryLabel ? `${label}, ${secondaryLabel}` : label}
      accessibilityState={{ checked: selected, disabled }}
      aria-checked={selected}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => ({
        minHeight: rowHeight(Boolean(secondaryLabel)) * Math.max(1, textScale),
        flexDirection: "row",
        alignItems: "center",
        gap: spacing.sm,
        paddingHorizontal: spacing.md,
        paddingVertical: spacing.xs,
        backgroundColor: selected ? t.primaryTint : pressed ? t.muted : t.card
      })}
    >
      {role === "checkbox" ? <CheckboxBox checked={selected} disabled={disabled} /> : (
        <View aria-hidden style={{ width: 22, height: 22, borderRadius: radius.full, borderWidth: 1.5, borderColor: disabled ? t.disabled : selected ? t.primary : t.input, alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
          {selected ? <View style={{ width: 10, height: 10, borderRadius: radius.full, backgroundColor: disabled ? t.disabled : t.primary }} /> : null}
        </View>
      )}
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text style={{ ...typography.body, color: ink, fontWeight: selected ? "600" : "400", fontFamily: controls.fontFamily }}>{label}</Text>
        {secondaryLabel ? <Text accessibilityLanguage={secondaryLanguage} style={{ ...typography.body, color: ink, fontFamily: controls.fontFamily }}>{secondaryLabel}</Text> : null}
      </View>
    </Pressable>
  );
}

/**
 * Equal-width choice of two or three short options: a neutral track, the chosen segment filled with the card tone
 * and a semibold label; inside a Card (white on white would read as an outlined pill) the chosen segment takes the
 * primary tint with primary text, like the selected filter chip. Labels wrap inside their segment instead of making it wider. `compact`: 36pt, for a control
 * inside a row or a sheet (the segments' hit slop keeps the 44pt target); otherwise 48pt for a question of its own.
 */
export function SegmentedControl<T extends string>({ options, value, onChange, disabled = false, accessibilityLabel, testID, compact = false }: {
  /** `language`: BCP 47 tag of a label in another language than the screen's (the "हिन्दी" choice), so it is pronounced right. */
  options: ReadonlyArray<{ value: T; label: string; language?: string }>;
  value: T | undefined;
  onChange: (value: T) => void;
  disabled?: boolean;
  accessibilityLabel: string;
  testID?: string;
  compact?: boolean;
}) {
  const { ui: t, fontSize, textScale, mode } = useTheme();
  const inCard = useContext(InCardContext);
  // Dark: the card-tone selected segment is darker than the track (1.15:1), so dark always uses the tint look (round-6 M1).
  const tinted = inCard || mode === "dark";
  const height = compact ? controls.compactHeight : controls.minHeight;
  // A 36pt control in a card row sits in 6pt of row padding, not the 8pt of plain rows, so the row stays 48pt.
  const rowFit = compact && inCard ? -(spacing.xs - 6) : 0;
  // The track's 2pt padding plus this slop make the target 44pt when compact.
  const slop = Math.max(2, (controls.minTouchTarget - (height - 4)) / 2);
  return (
    <View testID={testID} accessibilityRole="radiogroup" accessibilityLabel={accessibilityLabel} style={{ flexDirection: "row", backgroundColor: t.muted, borderRadius: radius.lg, padding: 2, gap: 2, marginVertical: rowFit }}>
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <Pressable
            key={option.value}
            accessibilityRole="radio"
            accessibilityLabel={option.label}
            accessibilityLanguage={option.language}
            accessibilityState={{ checked: selected, disabled }}
            aria-checked={selected}
            disabled={disabled}
            onPress={() => onChange(option.value)}
            hitSlop={{ top: slop, bottom: slop }}
            style={({ pressed }) => ({
              flex: 1,
              flexBasis: 0,
              minHeight: height - 4,
              borderRadius: radius.md,
              paddingHorizontal: spacing.xxs,
              alignItems: "center",
              justifyContent: "center",
              backgroundColor: selected ? (tinted ? t.primaryTint : t.card) : "transparent",
              opacity: pressed ? 0.85 : 1
            })}
          >
            <Text style={{ ...controlText, fontSize: fontSize.body, lineHeight: 20 * textScale, fontWeight: selected ? "600" : "400", color: disabled ? t.mutedForeground : selected && tinted ? t.primary : t.foreground, fontFamily: controls.fontFamily }}>
              {option.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

/**
 * A password (or long PIN) field with a trailing show/hide button inside it (44pt target). Showing it only turns off
 * `secureTextEntry`: autocorrect and capitalisation stay off, and the value lives only in the parent's state.
 * `showLabel` / `hideLabel` name the button (default "Show password" / "Hide password").
 */
export function PasswordInput({ showLabel = t("passwordShow"), hideLabel = t("passwordHide"), style, editable, onCard = false, ...input }: Omit<TextInputProps, "secureTextEntry"> & { showLabel?: string; hideLabel?: string; onCard?: boolean }) {
  const { ui: tokens } = useTheme();
  const [shown, setShown] = useState(false);
  return (
    <View style={{ justifyContent: "center" }}>
      <TextField
        {...input}
        onCard={onCard}
        editable={editable}
        secureTextEntry={!shown}
        autoCapitalize="none"
        autoCorrect={false}
        spellCheck={false}
        style={[{ paddingRight: controls.minTouchTarget + spacing.xxs }, style]}
      />
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={shown ? hideLabel : showLabel}
        onPress={() => setShown((on) => !on)}
        style={{ position: "absolute", right: 0, top: 0, bottom: 0, width: controls.minTouchTarget, minHeight: controls.minTouchTarget, alignItems: "center", justifyContent: "center" }}
      >
        <Icon name={shown ? icons.hide : icons.show} color={tokens.mutedForeground} size={22} />
      </Pressable>
    </View>
  );
}

export type NoticeTone = "info" | "warning" | "error" | "success";

/**
 * A message as a tinted card instead of a loose coloured paragraph: ink text on the tint, the tone carried by the
 * icon. Errors and warnings are announced (`alert`).
 */
export function Notice({ tone = "info", children, action, testID }: { tone?: NoticeTone; children: ReactNode; action?: ReactNode; testID?: string }) {
  const { ui: t, typography } = useTheme();
  const urgent = tone === "error" || tone === "warning";
  // An error or warning appears after an action (a save, a sign-in): the screen reader says it without moving focus.
  const spoken = urgent && typeof children === "string" ? children : undefined;
  useEffect(() => {
    if (spoken) announce(spoken);
  }, [spoken]);
  const look = {
    info: { bg: t.primaryTint, icon: icons.info, iconColor: t.primary },
    warning: { bg: t.attentionTint, icon: icons.warning, iconColor: t.foreground },
    error: { bg: t.destructiveSoft, icon: icons.error, iconColor: t.destructiveText },
    success: { bg: t.successTint, icon: icons.success, iconColor: t.success }
  }[tone];
  return (
    <View
      testID={testID}
      accessibilityRole={urgent ? "alert" : undefined}
      // TalkBack reads a live region when it appears; VoiceOver needs the announcement below.
      accessibilityLiveRegion={urgent ? "assertive" : "polite"}
      style={{ backgroundColor: look.bg, borderRadius: radius.lg, padding: spacing.sm, gap: spacing.xs }}
    >
      <View style={{ flexDirection: "row", gap: spacing.xs, alignItems: "flex-start" }}>
        <Icon name={look.icon} color={look.iconColor} size={20} />
        <View style={{ flex: 1, minWidth: 0 }}>
          {typeof children === "string" ? <Text style={{ ...typography.subhead, color: t.foreground, fontFamily: controls.fontFamily }}>{children}</Text> : children}
        </View>
      </View>
      {action}
    </View>
  );
}

/**
 * Every value is a `ui` token or a theme scale step (src/theme.ts): 48px controls, 6px control radius, 8px card
 * radius, compact 12px/8px mobile padding/gaps. Text follows the theme's Text size (`typography`).
 */
function createStyles(theme: Theme, controlHeight: number = controls.minHeight, compact: boolean = false) {
  const { ui: t, typography, fontSize, textScale } = theme;
  const dark = theme.mode === "dark";
  return StyleSheet.create({
    safe: { flex: 1, backgroundColor: t.page },
    body: {
      padding: compact ? spacing.sm : controls.screenPadding,
      gap: compact ? spacing.xs : spacing.sm,
      width: "100%",
      maxWidth: controls.contentMaxWidth,
      alignSelf: "center"
    },
    fill: { flex: 1 },
    // The sticky action bar under a form: canvas tone, one hairline above, the primary action full width.
    footer: {
      paddingHorizontal: compact ? spacing.sm : controls.screenPadding,
      paddingVertical: spacing.xs,
      gap: spacing.xs,
      borderTopWidth: StyleSheet.hairlineWidth,
      borderColor: t.separator,
      backgroundColor: t.page
    },
    frame: { flex: 1, flexDirection: "row", width: "100%", minWidth: 0, position: "relative" },
    mainColumn: { flex: 1, minWidth: 0 },
    mainScroll: { flex: 1, minWidth: 0 },
    debug: {
      backgroundColor: t.warningText,
      color: t.primaryForeground,
      padding: spacing.xs,
      minHeight: controlHeight,
      textAlign: "center",
      textAlignVertical: "center",
      fontWeight: "600"
    },
    title: {
      ...typography.title,
      // A long case id wraps instead of pushing the header action off the screen.
      flexShrink: 1,
      color: t.foreground,
      fontFamily: controls.fontFamily
    },
    titleWrap: {
      width: "100%",
      maxWidth: controls.contentMaxWidth,
      alignSelf: "center",
      paddingHorizontal: compact ? spacing.sm : controls.screenPadding,
      position: "relative",
      zIndex: 30,
      overflow: "visible"
    },
    titleBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm, paddingTop: compact ? spacing.xs : spacing.sm },
    text: { ...typography.body, color: t.foreground, fontFamily: controls.fontFamily },
    headline: { ...typography.headline, color: t.foreground, fontFamily: controls.fontFamily },
    /** A form question's label: larger and bolder than helper text so the questions lead. */
    fieldLabel: { ...typography.body, lineHeight: 22 * textScale, fontWeight: "600" as const, color: t.foreground, fontFamily: controls.fontFamily },
    muted: { ...typography.subhead, color: t.mutedForeground, fontFamily: controls.fontFamily },
    error: { ...typography.subhead, color: t.destructiveText, fontFamily: controls.fontFamily },
    // Petrol fields: a fill with no edge (white on the canvas, `inputOnCard` the neutral tone inside a white card);
    // the edge is reserved at the ring's width so focusing never moves the text. The focused field draws the ring
    // (`inputFocused`), an error the tint (`inputError`). High contrast keeps a 3:1 edge on every field.
    input: {
      borderWidth: theme.focusWidth,
      borderColor: theme.highContrast ? t.border : "transparent",
      borderRadius: radius.lg,
      minHeight: controlHeight,
      paddingHorizontal: spacing.md,
      paddingVertical: spacing.xs,
      // No lineHeight: iOS draws a TextInput's text at the bottom of a taller line box, so the entry sits low.
      fontSize: typography.body.fontSize,
      fontWeight: typography.body.fontWeight,
      backgroundColor: t.background,
      color: t.foreground,
      fontFamily: controls.fontFamily
    },
    inputOnCard: { backgroundColor: t.muted },
    // A white field inside a white card, matching the WHO form's own fields there: the faint hairline tone only.
    inputHairline: { borderColor: t.border },
    inputFocused: { borderColor: t.ring, borderWidth: theme.focusWidth },
    inputError: { borderColor: t.destructiveSoft, backgroundColor: t.destructiveSoft },
    phoneInputRow: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
    phonePrefix: { ...typography.body, color: t.foreground, fontFamily: controls.fontFamily, minWidth: 40 },
    phoneInput: { flex: 1 },
    authLinks: { gap: spacing.xs },
    button: {
      borderRadius: radius.md,
      borderWidth: 0,
      minHeight: controlHeight,
      minWidth: BUTTON_MIN_WIDTH,
      paddingVertical: spacing.xs,
      paddingHorizontal: spacing.lg,
      alignItems: "center",
      justifyContent: "center"
    },
    primary: { backgroundColor: t.primary },
    secondary: { backgroundColor: t.primaryTint },
    danger: { backgroundColor: t.destructive },
    buttonSpinner: { position: "absolute", right: spacing.xs },
    disabled: { opacity: 0.5 },
    buttonText: { ...controlText, fontSize: fontSize.body, lineHeight: 22 * textScale, fontWeight: "500", color: t.primaryForeground, fontFamily: controls.fontFamily },
    secondaryText: { ...controlText, fontSize: fontSize.body, lineHeight: 22 * textScale, fontWeight: "500", color: t.foreground, fontFamily: controls.fontFamily },
    row: { flexDirection: "row", gap: spacing.xs, alignItems: "center", flexWrap: "wrap" },
    // Borderless: a card stands apart from the canvas by tone and a faint shadow (none in dark mode).
    card: {
      backgroundColor: t.card,
      borderRadius: radius.lg,
      // One padding on every screen (16pt); screens do not override it.
      padding: controls.cardPadding,
      gap: controls.gap,
      shadowColor: t.foreground,
      shadowOpacity: dark ? 0 : 0.06,
      shadowRadius: 6,
      shadowOffset: { width: 0, height: 1 },
      elevation: dark ? 0 : 1
    },
    /** A grouped card whose rows run edge to edge (ListRow, ChoiceRow), split by inset hairlines. */
    group: {
      backgroundColor: t.card,
      borderRadius: radius.lg,
      shadowColor: t.foreground,
      shadowOpacity: dark ? 0 : 0.06,
      shadowRadius: 6,
      shadowOffset: { width: 0, height: 1 },
      elevation: dark ? 0 : 1
    },
    separator: { height: StyleSheet.hairlineWidth, backgroundColor: t.separator, marginLeft: spacing.md }
  });
}

/** Legacy static styles (light, Medium text); screens use useUiStyles so they follow the theme and Text size. */
export const styles = createStyles(getTheme("light"));

/** Use this hook when a screen needs styles that follow the selected UI theme, contrast and text size. */
export function useUiStyles() {
  const theme = useTheme();
  const { width } = useWindowDimensions();
  const compact = width < PHONE_BREAKPOINT;
  const height = controls.minHeight;
  const { ui: tokens, textScale, mode, highContrast } = theme;
  // `theme` is a new object each render; these fields are what it is made of.
  return useMemo(() => createStyles(theme, height, compact), [tokens, textScale, mode, highContrast, height, compact]);
}

/**
 * Say `text` through VoiceOver without moving focus (WCAG 4.1.3). Android needs none: the view carries
 * `accessibilityLiveRegion`, which TalkBack reads when it appears. No-op where the API is missing.
 */
export function announce(text: string) {
  if (Platform.OS !== "ios" || typeof AccessibilityInfo.announceForAccessibility !== "function") return;
  AccessibilityInfo.announceForAccessibility(text);
}

/**
 * Put the screen reader on `node` (a new screen's title) after it mounts; no-op on the web and when the platform
 * has no accessibility event API (tests without a native module).
 */
export function focusForAccessibility(node: unknown) {
  if (!node || Platform.OS === "web" || typeof AccessibilityInfo.sendAccessibilityEvent !== "function") return;
  // Only while a screen reader runs: React Native logs a red console error when the view is already gone (a tab
  // left before the frame), and with no reader there is nothing to move.
  void Promise.resolve(AccessibilityInfo.isScreenReaderEnabled?.())
    .then((on) => {
      // The node exists only after the first layout; a frame later the reader can land on it.
      if (on) setTimeout(() => {
        if (findNodeHandle(node as never) == null) return;
        try {
          AccessibilityInfo.sendAccessibilityEvent(node as never, "focus");
        } catch {
          // A screen unmounted before the frame: nothing to focus.
        }
      }, 0);
    })
    .catch(() => undefined);
}

/**
 * One support line for screenshots: what failed, when, on which build. Only status, machine code, masked
 * route, error class and a scrubbed message prefix; never tokens, server text, URLs, names or answers.
 */
export function errorReference(error: unknown): string {
  return `Ref: ${describeError(error)} · ${new Date().toISOString().slice(11, 16)}Z · v${APP_VERSION}`;
}

/** The UI string for an error from the device API; never shows server text or answers. */
export function errorText(error: unknown): string {
  recordError(describeError(error));
  if (isStorageFull(error)) return t("phoneStorageFull");
  if (error instanceof SessionRevokedError) return t(error.keptUnsent ? "accessRemovedKept" : "sessionRevoked");
  if (error instanceof SignInRequiredError) return t("signInAgain");
  if (error instanceof AlreadyEnrolledError) return t("errAlreadyEnrolled");
  if (error instanceof AccountStoreCollisionError) return t("accountStoreCollision");
  if (error instanceof NotInSlotError) return t("errSlotChanged");
  if (error instanceof ApiError) {
    if (error.code === "device_limit") return t("deviceLimit");
    if (error.code === "enrolment_invalid") return t("errEnrolInvalid");
    if (error.code === "csrf_failed") return t("csrfRefreshed");
    if (error.code === "cookie_session_required") return t("loginRequiredAction");
    if (error.code === "maintenance") return t("serverUnavailable");
    if (error.code === "forbidden" || error.code === "project_forbidden") return t("serverForbidden");
    if (error.code === "password_change_required" || error.code === "terms_required") return t("termsRequired");
    if (error.code === "no_interviewer_grant") return t("errNoGrant");
    if (error.code === "project_intake_off") return t("errProjectIntakeOff");
    if (error.code === "no_collection_access") return t("noCollectionAccess");
    if (error.code === "device_revoked") return t("errDeviceRevoked");
    if (error.code === "demo_limit") return t("demoLimit");
    if (error.code === "cap_reached") return t("demoFull");
    if (error.status === 429) return t("errRateLimited");
    if (error.status === 401) return t("errSignIn");
    return `${t("errGeneric")}\n${errorReference(error)}`;
  }
  if (error instanceof TypeError) return t("errNetwork");
  return `${t("errGeneric")}\n${errorReference(error)}`;
}

/** A case state's UI label (the states a device holds), else the state code itself. */
export function stateLabel(state: string): string {
  const key = `state_${state}` as StringKey;
  const label = t(key);
  return label === key ? state : label;
}
