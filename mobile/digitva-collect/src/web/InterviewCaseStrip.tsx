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

function clean(value: unknown): string | undefined {
  if (value === null || value === undefined) return undefined;
  const text = String(value).trim();
  return text ? text : undefined;
}

function fullYearsBetween(birthIso: string, deathIso: string): number {
  const [by, bm, bd] = birthIso.split("-").map(Number);
  const [dy, dm, dd] = deathIso.split("-").map(Number);
  let years = dy - by;
  if (dm < bm || (dm === bm && dd < bd)) years -= 1;
  return years;
}

export function formatLiveCaseSummary(
  prefill: Prefill | undefined,
  answers?: Record<string, unknown>,
): string[] {
  const deceased = prefill?.deceased as Record<string, unknown> | undefined;
  const allAnswers: Record<string, unknown> = {
    ...((prefill?.answers ?? {}) as Record<string, unknown>),
    ...(answers ?? {}),
  };

  const answeredName = [clean(allAnswers.Id10017), clean(allAnswers.Id10018)]
    .filter(Boolean)
    .join(" ");
  const registeredName =
    clean(deceased?.name) ??
    ([clean(deceased?.givenNames), clean(deceased?.surname)].filter(Boolean).join(" ") || undefined);
  const name = answeredName || registeredName || "—";

  const dod =
    clean(allAnswers.Id10023) ??
    clean(deceased?.date_of_death) ??
    clean(deceased?.dateOfDeath) ??
    "—";

  let age = "—";
  let foundAnswerAge = false;
  for (const key of ["ageInYears", "ageInYears2", "age_adult", "age_child_years"]) {
    const val = allAnswers[key];
    if (val !== null && val !== undefined && String(val).trim() !== "" && Number.isFinite(Number(val))) {
      age = `${String(val).trim()} yr`;
      foundAnswerAge = true;
      break;
    }
  }
  if (!foundAnswerAge) {
    if (allAnswers.dob_known === "yes" && /^\d{4}-\d{2}-\d{2}$/.test(dod)) {
      const exactDob = String(allAnswers.Id10021 ?? "").trim();
      const monthYearDob = String(allAnswers.dob_month_year ?? "").trim();
      const yearDob = String(allAnswers.dob_year ?? "").trim();
      if (allAnswers.dob_type === "exact" && /^\d{4}-\d{2}-\d{2}$/.test(exactDob)) {
        const years = fullYearsBetween(exactDob, dod);
        if (years >= 0) age = `${years} yr`;
      } else if (allAnswers.dob_type === "month_year" && /^\d{4}-\d{2}$/.test(monthYearDob)) {
        const years = fullYearsBetween(`${monthYearDob}-01`, dod);
        if (years >= 0) age = `~${years} yr`;
      } else if (allAnswers.dob_type === "year" && /^\d{4}$/.test(yearDob)) {
        const years = Number(dod.slice(0, 4)) - Number(yearDob);
        if (years >= 0) age = `~${years} yr`;
      }
    } else {
      const regAge = deceased?.age_years ?? deceased?.ageInYears;
      const regDob = clean(deceased?.date_of_birth) ?? clean(deceased?.dateOfBirth);
      if (regAge !== null && regAge !== undefined && String(regAge).trim() !== "" && Number.isFinite(Number(regAge))) {
        age = `${String(regAge).trim()} yr`;
      } else if (regDob && /^\d{4}-\d{2}-\d{2}$/.test(regDob) && /^\d{4}-\d{2}-\d{2}$/.test(dod)) {
        const years = fullYearsBetween(regDob, dod);
        if (years >= 0) age = `${years} yr`;
      }
    }
  }

  const rawSex = clean(allAnswers.Id10019) ?? clean(deceased?.sex);
  const sex = rawSex ? rawSex.charAt(0).toUpperCase() + rawSex.slice(1) : "—";

  const parts = [name, `DOD: ${dod}`, `Age: ${age}`, `Sex: ${sex}`];
  const informantName = clean(deceased?.informant_name ?? deceased?.informantName);
  const informantPhone = clean(deceased?.informant_phone ?? deceased?.informantPhone);
  const address = clean(deceased?.address);
  if (informantName) parts.push(`Informant: ${informantName}`);
  if (informantPhone) parts.push(informantPhone);
  if (address) parts.push(address);
  return parts;
}

export interface InterviewCaseStripProps {
  prefill: Prefill | undefined;
  onHeight?: (height: number) => void;
  uniqueId?: string | null;
  locationLabel?: string | null;
  saveStatus?: string | null;
  answers?: Record<string, unknown>;
  showLiveSummary?: boolean;
}

/**
 * Compact case line for an interview started from a reported death or direct intake. Sticky (web)
 * at the top of the screen's scroller: the header bar, title row and Back to
 * collection above it scroll away, so it ends up pinned at the top of the
 * viewport. `onHeight` lets the screen keep the form's own sticky progress below it.
 */
export function InterviewCaseStrip({
  prefill,
  onHeight,
  uniqueId,
  locationLabel,
  saveStatus,
  answers,
  showLiveSummary,
}: InterviewCaseStripProps) {
  const theme = useTheme();
  const isLiveMode = Boolean(showLiveSummary || uniqueId || locationLabel || saveStatus || answers);
  if (!isLiveMode) {
    const parts = caseStripParts(prefill);
    if (!parts.length) return null;
    return (
      <View
        nativeID="digitva-interview-case-strip"
        testID="interview-case-strip"
        onLayout={(event) => onHeight?.(Math.ceil(event.nativeEvent.layout.height))}
        style={[styles.strip, { backgroundColor: theme.colors.background }]}
      >
        <View style={[styles.chip, { backgroundColor: theme.colors.surfaceMuted, borderColor: theme.colors.border }]}>
          <Text style={[styles.text, { color: theme.colors.textMuted }]}>{parts.join(" · ")}</Text>
        </View>
      </View>
    );
  }

  const metaParts = [uniqueId ? t("interviewCaseId", { id: uniqueId }) : null, locationLabel].filter(Boolean);
  const hasHeader = Boolean(metaParts.length > 0 || saveStatus);
  const summaryText = formatLiveCaseSummary(prefill, answers).join(" · ");

  return (
    <View
      nativeID="digitva-interview-case-strip"
      testID="interview-case-strip"
      onLayout={(event) => onHeight?.(Math.ceil(event.nativeEvent.layout.height))}
      style={[styles.strip, { backgroundColor: theme.colors.background }]}
    >
      <View style={[styles.chip, { backgroundColor: theme.colors.surfaceMuted, borderColor: theme.colors.border }]}>
        {hasHeader ? (
          <View style={styles.headerRow}>
            <Text testID="interview-case-meta" style={[styles.metaText, { color: theme.colors.text }]}>
              {metaParts.join(" · ")}
            </Text>
            {saveStatus ? (
              <Text testID="interview-save-status" style={[styles.saveText, { color: theme.colors.textMuted }]}>
                {saveStatus}
              </Text>
            ) : null}
          </View>
        ) : null}
        <Text
          testID="interview-case-summary"
          numberOfLines={1}
          style={[styles.text, { color: theme.colors.textMuted }]}
        >
          {summaryText}
        </Text>
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
  chip: { paddingVertical: 6, paddingHorizontal: 12, borderRadius: 8, borderWidth: 1, gap: 2 },
  headerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    flexWrap: "wrap",
    gap: 8,
  },
  metaText: { fontSize: fontSize.body, lineHeight: 20, fontWeight: "600" },
  saveText: { fontSize: fontSize.body, lineHeight: 20 },
  text: { fontSize: fontSize.body, lineHeight: 20 },
});
