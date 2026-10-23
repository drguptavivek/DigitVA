/**
 * Interviewer assists: pure rules that suggest answers from other answers.
 * Nothing here stores anything; the form applies a suggestion through the
 * session as an ordinary answer and remembers (in memory only) which answers
 * it filled so it never overrides one the interviewer chose.
 *
 *  - age group, age in days / months / years from the dates of birth and death
 *    (digitva-12ks), with one-tap fixes for the WHO age boundaries;
 *  - narration language from the script of the typed narrative (digitva-v5zz).
 *
 * The WHO question text and constraints are untouched (see
 * docs/policy/digitva-who-form-overrides.md, "Interviewer assists").
 */
import type { AnswerValue, SubmissionData } from "../types.js";

export type AgeGroupCode = "neonate" | "child" | "adult";
export type AssistKind = "suggested" | "calculated" | "estimate";

const DAYS_PER_YEAR = 365.25;
const DAYS_PER_MONTH = 30.4375;
const MS_PER_DAY = 86_400_000;
const ADULT_FROM_DAYS = 12 * DAYS_PER_YEAR;

/** The WHO thresholds (isNeonatal1 / isChild1 / isAdult1) on an exact number of days. */
export function ageGroupOfDays(days: number): AgeGroupCode {
  if (days <= 27) return "neonate";
  return days < ADULT_FROM_DAYS ? "child" : "adult";
}

type Precision = "day" | "month" | "year";
interface DatePart {
  year: number;
  month: number;
  day: number;
  precision: Precision;
}

function parseIso(value: unknown, precision: Precision): DatePart | undefined {
  const match = typeof value === "string" ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(value) : null;
  if (!match) return undefined;
  const part = { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]), precision };
  return Number.isNaN(Date.UTC(part.year, part.month - 1, part.day)) ? undefined : part;
}

/** The date of birth the interviewer gave, with the precision they gave it at. */
function birthOf(data: SubmissionData): DatePart | undefined {
  if (data.Id10020 === "yes") return parseIso(data.Id10021, "day");
  if (data.dob_precision === "month_year") return parseIso(data.dob_month_year, "month");
  if (data.dob_precision === "year") return parseIso(data.dob_year, "year");
  return undefined;
}

/** The date of death: the exact date when known, else the year of death. */
function deathOf(data: SubmissionData): DatePart | undefined {
  if (data.Id10022 === "yes") return parseIso(data.Id10023, "day");
  if (data.Id10022 === "no" || data.Id10022 === "ref") return parseIso(data.Id10024, "year");
  return undefined;
}

const utcDay = (part: DatePart, edge: "start" | "end"): number => {
  if (part.precision === "day") return Date.UTC(part.year, part.month - 1, part.day) / MS_PER_DAY;
  if (part.precision === "month") {
    return edge === "start"
      ? Date.UTC(part.year, part.month - 1, 1) / MS_PER_DAY
      : Date.UTC(part.year, part.month, 0) / MS_PER_DAY;
  }
  return edge === "start" ? Date.UTC(part.year, 0, 1) / MS_PER_DAY : Date.UTC(part.year, 11, 31) / MS_PER_DAY;
};

export interface DerivedAge {
  /** exact: both dates to the day; months: a month is approximate; years: a year is approximate. */
  precision: "exact" | "months" | "years";
  /** Unset when the dates cannot say which group (a year-only difference of 0 or 12). */
  group?: AgeGroupCode;
  days?: number;
  years?: number;
}

/**
 * What the dates say about the age. Exact dates use ageInDays; a year-only date
 * uses the difference of the years, suggesting a group only when it is
 * unambiguous (13 or more is an adult, 1 to 11 a child; 0 and 12 could be
 * either); a month-only date suggests a group when every day in the month
 * range falls in the same group.
 */
export function deriveAge(data: SubmissionData): DerivedAge | undefined {
  const birth = birthOf(data);
  const death = deathOf(data);
  if (!birth || !death) return undefined;
  if (birth.precision === "day" && death.precision === "day") {
    const days = utcDay(death, "start") - utcDay(birth, "start");
    if (!Number.isFinite(days) || days < 0) return undefined;
    return { precision: "exact", days, group: ageGroupOfDays(days) };
  }
  if (birth.precision === "year" || death.precision === "year") {
    const years = death.year - birth.year;
    if (years < 0) return undefined;
    const group: AgeGroupCode | undefined = years >= 13 ? "adult" : years >= 1 && years <= 11 ? "child" : undefined;
    return { precision: "years", years, ...(group ? { group } : {}) };
  }
  const shortest = utcDay(death, "start") - utcDay(birth, "end");
  const longest = utcDay(death, "end") - utcDay(birth, "start");
  if (longest < 0) return undefined;
  const low = ageGroupOfDays(Math.max(0, shortest));
  return low === ageGroupOfDays(longest) ? { precision: "months", group: low } : { precision: "months" };
}

export interface AgeSuggestion {
  value: AnswerValue;
  kind: AssistKind;
}

/** The answers the dates suggest, by question name; only for questions in `shown`. */
export function ageSuggestions(
  data: SubmissionData,
  shown: ReadonlySet<string>
): Record<string, AgeSuggestion> {
  const age = deriveAge(data);
  const found: Record<string, AgeSuggestion> = {};
  if (!age) return found;
  const add = (name: string, value: AnswerValue, kind: AssistKind) => {
    if (shown.has(name)) found[name] = { value, kind };
  };
  if (age.group) add("age_group", age.group, "suggested");
  if (age.precision === "exact" && age.days !== undefined) {
    const days = age.days;
    if (age.group === "neonate") add("age_neonate_days", days, "calculated");
    else if (age.group === "adult") add("age_adult", Math.floor(days / DAYS_PER_YEAR), "calculated");
    else if (age.group === "child") {
      const unit = days <= 60 ? "days" : days < 24 * DAYS_PER_MONTH ? "months" : "years";
      add("age_child_unit", unit, "calculated");
      // The number follows the unit the interviewer has chosen, if they chose one.
      const active = data.age_child_unit === "days" || data.age_child_unit === "months" || data.age_child_unit === "years"
        ? data.age_child_unit
        : unit;
      if (active === "days") add("age_child_days", days, "calculated");
      else if (active === "months") add("age_child_months", Math.floor(days / DAYS_PER_MONTH), "calculated");
      else add("age_child_years", Math.floor(days / DAYS_PER_YEAR), "calculated");
    }
  } else if (age.precision === "years" && age.years !== undefined) {
    // Years only: an estimate for years, never days.
    if (age.group === "adult") add("age_adult", age.years, "estimate");
    else if (age.group === "child") {
      add("age_child_unit", "years", "estimate");
      if (data.age_child_unit === undefined || data.age_child_unit === "years") {
        add("age_child_years", age.years, "estimate");
      }
    }
  }
  return found;
}

/** A short description of the derived age for the confirmation ("4 years"); undefined when none. */
export function ageDetail(age: DerivedAge, unit: (key: "days" | "months" | "years", count: number) => string): string | undefined {
  if (age.precision === "exact" && age.days !== undefined) {
    if (age.days <= 60) return unit("days", age.days);
    if (age.days < 24 * DAYS_PER_MONTH) return unit("months", Math.floor(age.days / DAYS_PER_MONTH));
    return unit("years", Math.floor(age.days / DAYS_PER_YEAR));
  }
  if (age.precision === "years" && age.years !== undefined) return unit("years", age.years);
  return undefined;
}

/** How far a typed age may sit from the calculated one before it is called a disagreement. */
export function agreesWithSuggestion(name: string, entered: AnswerValue | undefined, suggested: AnswerValue): boolean {
  if (typeof entered === "number" && typeof suggested === "number") {
    // Rounding: a day for days, a month for months, a year for years (a year-only estimate is +/- 1).
    return Math.abs(entered - suggested) <= 1;
  }
  return entered === suggested;
}

export interface BoundaryFix {
  messageKey: "fixToNeonate" | "fixToMonths" | "fixToAdult" | "fixToChild";
  actionKey: "fixToNeonateAction" | "fixToMonthsAction" | "fixToAdultAction" | "fixToChildAction";
  /** The number the message names. */
  count: number;
  /** Answers to set, in order; `undefined` clears. */
  set: Array<[string, AnswerValue | undefined]>;
}

/**
 * The one-tap fix for a value that sits just outside its WHO age boundary, or
 * undefined. Child days 1..27 are a neonate's age, child days over 60 belong
 * in months, child years from 12 are an adult's, neonate days over 27 are a
 * child's.
 */
export function boundaryFix(name: string, value: AnswerValue | undefined): BoundaryFix | undefined {
  if (typeof value !== "number" || !Number.isInteger(value)) return undefined;
  if (name === "age_child_days") {
    if (value >= 0 && value <= 27) {
      return {
        messageKey: "fixToNeonate",
        actionKey: "fixToNeonateAction",
        count: value,
        set: [
          ["age_group", "neonate"],
          ["age_neonate_days", value],
          ["age_child_days", undefined],
          ["age_child_unit", undefined]
        ]
      };
    }
    if (value > 60) {
      const months = Math.max(1, Math.round(value / DAYS_PER_MONTH));
      return {
        messageKey: "fixToMonths",
        actionKey: "fixToMonthsAction",
        count: value,
        set: [
          ["age_child_unit", "months"],
          ["age_child_months", months],
          ["age_child_days", undefined]
        ]
      };
    }
  }
  if (name === "age_child_years" && value >= 12) {
    return {
      messageKey: "fixToAdult",
      actionKey: "fixToAdultAction",
      count: value,
      set: [
        ["age_group", "adult"],
        ["age_adult", value],
        ["age_child_years", undefined],
        ["age_child_unit", undefined]
      ]
    };
  }
  if (name === "age_neonate_days" && value > 27) {
    const set: BoundaryFix["set"] = [["age_group", "child"]];
    if (value <= 60) set.push(["age_child_unit", "days"], ["age_child_days", value]);
    else set.push(["age_child_unit", "months"], ["age_child_months", Math.max(1, Math.round(value / DAYS_PER_MONTH))]);
    set.push(["age_neonate_days", undefined]);
    return { messageKey: "fixToChild", actionKey: "fixToChildAction", count: value, set };
  }
  return undefined;
}

// --- narration language -----------------------------------------------------

const SCRIPT_LANGUAGES: ReadonlyArray<readonly [RegExp, string]> = [
  [/[ऀ-ॿ]/g, "hindi"],
  [/[ঀ-৿]/g, "bangla"],
  [/[ಀ-೿]/g, "kannada"],
  [/[ഀ-ൿ]/g, "malayalam"],
  [/[A-Za-zÀ-ɏ]/g, "english"]
];

/**
 * The narration language the script of `text` points to: Devanagari is
 * Hindi (Marathi shares the script; the interviewer changes it), Latin is
 * English (Hinglish typed in Latin letters stays English). Undefined when the
 * text has no letters or two scripts tie.
 */
export function narrationLanguageFromText(text: string): string | undefined {
  const counts = SCRIPT_LANGUAGES.map(([pattern, language]) => [language, (text.match(pattern) ?? []).length] as const)
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1]);
  if (!counts.length || (counts[1] && counts[1][1] === counts[0]![1])) return undefined;
  return counts[0]![0];
}

const LOCALE_LANGUAGES: Record<string, string> = {
  en: "english",
  hi: "hindi",
  mr: "marathi",
  kn: "kannada",
  ml: "malayalam",
  bn: "bangla"
};

/**
 * The narration language to pre-select: from the narrative's script, or, with
 * no narrative yet, the app language. Only a language the question offers.
 */
export function narrationLanguageSuggestion(
  narrative: AnswerValue | undefined,
  locale: string,
  offered: ReadonlySet<string>
): string | undefined {
  const text = typeof narrative === "string" ? narrative.trim() : "";
  const language = text ? narrationLanguageFromText(text) : LOCALE_LANGUAGES[locale.split("-")[0]!.toLowerCase()];
  return language && offered.has(language) ? language : undefined;
}
