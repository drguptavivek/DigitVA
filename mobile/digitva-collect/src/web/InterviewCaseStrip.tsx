import { StyleSheet, Text, View, type ViewStyle } from "react-native";

import type { Prefill } from "../cases";
import { t, type StringKey } from "../i18n";
import { fontSize, useTheme } from "../theme";

const NBSP = " ";
const DAY_MS = 86_400_000;

function sexLabel(value: string | undefined): string {
  if (!value) return "";
  const key = `sex${value[0]?.toUpperCase()}${value.slice(1).toLowerCase()}` as StringKey;
  const label = t(key);
  return label === key ? value : label;
}

function isoParts(value: unknown): [number, number, number] | null {
  const match = typeof value === "string" ? /^(\d{4})-(\d{2})(?:-(\d{2}))?/.exec(value) : null;
  return match ? [Number(match[1]), Number(match[2]), Number(match[3] ?? 1)] : null;
}

/** "51 y"; under a year "7 m"; under a month "12 d". Whole units, never rounded up. */
function ageAtDeath(birth: [number, number, number], death: [number, number, number]): string | null {
  const months = (death[0] - birth[0]) * 12 + (death[1] - birth[1]) - (death[2] < birth[2] ? 1 : 0);
  if (months < 0) return null;
  if (months >= 12) return `${Math.floor(months / 12)}${NBSP}y`;
  if (months >= 1) return `${months}${NBSP}m`;
  const utc = ([y, m, d]: [number, number, number]) => Date.UTC(y, m - 1, d);
  const days = Math.round((utc(death) - utc(birth)) / DAY_MS);
  return `${days}${NBSP}d`;
}

/**
 * The strip's parts from the draft's prefill (the death register's name, sex, age
 * and date of death; never informant or address). Age: exact or partial birth date
 * first (partial ones prefill dob_month_year / dob_year), else the registered age.
 * Empty when the prefill carries no deceased block (a case still awaiting identity).
 */
export function caseStripParts(prefill: Prefill | undefined): string[] {
  const deceased = prefill?.deceased as
    | { givenNames?: string; surname?: string; sex?: string; dateOfDeath?: string; dateOfBirth?: string; ageInYears?: number }
    | undefined;
  if (!deceased) return [];
  const answers = (prefill?.answers ?? {}) as Record<string, unknown>;
  const death = isoParts(deceased.dateOfDeath);
  const birth = isoParts(deceased.dateOfBirth) ?? isoParts(answers.dob_month_year) ?? isoParts(answers.dob_year);
  let age: string | null = null;
  if (birth && death) {
    // Year-only birth: the calendar-year difference; the day and month are unknown.
    const yearOnly = !isoParts(deceased.dateOfBirth) && !isoParts(answers.dob_month_year);
    age = yearOnly ? `${Math.max(0, death[0] - birth[0])}${NBSP}y` : ageAtDeath(birth, death);
  }
  if (!age) {
    const years = deceased.ageInYears ?? (answers.age_child_unit === "years" ? Number(answers.age_child_years) : NaN);
    if (Number.isFinite(years)) age = `${years}${NBSP}y`;
  }
  const name = [deceased.givenNames, deceased.surname].filter(Boolean).join(" ").trim();
  return [
    name,
    age ?? "",
    sexLabel(deceased.sex),
    deceased.dateOfDeath ? t("interviewCaseDied", { date: deceased.dateOfDeath }).replace(/ /g, NBSP) : "",
  ].filter(Boolean);
}

/**
 * Compact case line for an interview started from a reported death. Sticky (web)
 * at the top of the screen's scroller: the header bar, title row and Back to
 * collection above it scroll away, so it ends up pinned at the top of the
 * viewport. `onHeight` lets the screen keep the form's own sticky progress below it.
 */
export function InterviewCaseStrip({ prefill, onHeight }: { prefill: Prefill | undefined; onHeight?: (height: number) => void }) {
  const theme = useTheme();
  const parts = caseStripParts(prefill);
  if (!parts.length) return null;
  return (
    <View
      nativeID="digitva-interview-case-strip"
      onLayout={(event) => onHeight?.(Math.ceil(event.nativeEvent.layout.height))}
      style={[styles.strip, { backgroundColor: theme.colors.background }]}
    >
      <View style={[styles.chip, { backgroundColor: theme.colors.surfaceMuted, borderColor: theme.colors.border }]}>
        <Text style={[styles.text, { color: theme.colors.textMuted }]}>{parts.join(" · ")}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  strip: {
    // Web only (this screen is the browser interview); the cast is for RN's position type.
    position: "sticky",
    top: 0,
    zIndex: 5,
    // Opaque so scrolled form content never shows through behind the text.
    paddingVertical: 4,
  } as unknown as ViewStyle,
  chip: { paddingVertical: 6, paddingHorizontal: 12, borderRadius: 8, borderWidth: 1 },
  text: { fontSize: fontSize.body, lineHeight: 20 },
});
