import { useEffect, useRef, useState, type ReactNode } from "react";
import { View } from "react-native";

import { FieldError, FieldHint, Input, MenuSelect, useLayout } from "./ui";

export interface DateFieldProps {
  /** Accessible name; the visible label is drawn by the caller. */
  label: string;
  /** ISO "YYYY-MM-DD", or with `precision` also "YYYY-MM" / "YYYY" (DORIS accepts all three); "" is unset. */
  value: string;
  onChange: (value: string) => void;
  /** Injected clock and IANA zone so "today" can be tested; default is the device clock and zone. */
  now?: Date;
  timeZone?: string;
  /** Adds the precision dropdown (Date / Year-Month / Year); only date of birth, injury and surgery have it. */
  precision?: boolean;
}

const FULL = /^(\d{4})-(\d{2})-(\d{2})$/;
const PARTIAL = /^\d{4}(-(0[1-9]|1[0-2]))?$/;

/** Real calendar date in ISO form; "2026-02-30" is not one. */
export function isFullIso(value: string): boolean {
  const match = FULL.exec(value);
  if (!match) return false;
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

export const isPartialIso = (value: string): boolean => PARTIAL.test(value);

/** Today as YYYY-MM-DD in the given zone (default: the device's), never the UTC date. */
export function todayIso(now: Date = new Date(), timeZone?: string): string {
  try {
    const parts = new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(now);
    const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
    return `${get("year")}-${get("month")}-${get("day")}`;
  } catch {
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  }
}

/** A Date at local midnight for an ISO day (the native picker works in local time). */
export function localDate(iso: string): Date {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(year, month - 1, day);
}

/** The picked local calendar day as ISO, with no time part and no timezone shift. */
export function isoFromLocal(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

export type Precision = "date" | "month" | "year";
export const PRECISIONS: ReadonlyArray<{ value: Precision; label: string }> = [{ value: "date", label: "Date" }, { value: "month", label: "Year-Month" }, { value: "year", label: "Year" }];
const KEEP: Record<Precision, number> = { date: 10, month: 7, year: 4 };
const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;
const YEAR = /^\d{4}$/;
const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** The precision a stored value is written in; null for "" or anything that is not YYYY, YYYY-MM or a real date. */
export function precisionOf(value: string): Precision | null {
  return isFullIso(value) ? "date" : MONTH.test(value) ? "month" : YEAR.test(value) ? "year" : null;
}

/** Switching precision keeps what fits: a finer value is cut (date to month to year); a coarser one cannot be expressed in the finer field, so it is cleared. */
export function convertPrecision(value: string, to: Precision): string {
  const from = precisionOf(value);
  if (from === null) return "";
  return KEEP[from] >= KEEP[to] ? value.slice(0, KEEP[to]) : "";
}

/**
 * Local text for a field whose typing is only emitted once valid ("" otherwise). `emitted` lets the parent echo
 * of our own value pass without resetting what the user is still typing.
 */
function useEmitText(value: string) {
  const [text, setText] = useState(value);
  const emitted = useRef(value);
  useEffect(() => {
    if (value === emitted.current) return;
    emitted.current = value;
    setText(value);
  }, [value]);
  return { text, setText, emitted };
}

/** Year-Month for builds without a native month input: a month list and a four-digit year. */
export function MonthYearFallback({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  const layout = useLayout();
  const [month, setMonth] = useState(MONTH.test(value) ? value.slice(5) : "");
  const [year, setYear] = useState(MONTH.test(value) ? value.slice(0, 4) : "");
  const emitted = useRef(value);
  useEffect(() => {
    if (value === emitted.current) return;
    emitted.current = value;
    setMonth(MONTH.test(value) ? value.slice(5) : "");
    setYear(MONTH.test(value) ? value.slice(0, 4) : "");
  }, [value]);
  const commit = (nextMonth: string, nextYear: string) => {
    setMonth(nextMonth);
    setYear(nextYear);
    const ok = nextMonth !== "" && YEAR.test(nextYear);
    const next = ok ? `${nextYear}-${nextMonth}` : "";
    emitted.current = next;
    onChange(next);
  };
  return (
    <View style={{ gap: 4, flexGrow: 1 }}>
      <View style={layout.row}>
        <MenuSelect triggerLabel={`${label} month`} valueText={month ? MONTH_NAMES[Number(month) - 1] : "Month"} selected={month} options={MONTH_NAMES.map((name, index) => ({ value: String(index + 1).padStart(2, "0"), label: name, accessibilityLabel: `${label} month: ${name}` }))} onSelect={(code) => commit(code, year)} />
        <Input accessibilityLabel={`${label} year`} placeholder="Year" keyboardType="numeric" inputMode="numeric" maxLength={4} value={year} onChangeText={(next) => commit(month, next.replace(/\D/g, ""))} style={{ width: 90 }} />
      </View>
    </View>
  );
}

/**
 * Shared behaviour of the date controls. `date` and `month` draw the platform inputs for a full date and a
 * year-month; the year is a numeric field unless a `year` renderer (the web dropdown) is given. Without `precision` the field is a plain calendar date: a stored
 * partial value (the interview can prefill "1997-07") is shown in a text field that only accepts a full date,
 * and stays as stored until the user replaces or clears it.
 */
export function DateFieldShell({ label, value, onChange, precision, date, month, year }: DateFieldProps & { date: (value: string, onChange: (value: string) => void) => ReactNode; month?: (value: string, onChange: (value: string) => void) => ReactNode; year?: (value: string, onChange: (value: string) => void) => ReactNode }) {
  const layout = useLayout();
  const [mode, setMode] = useState<Precision>(precisionOf(value) ?? "date");
  const [error, setError] = useState("");
  const { text, setText, emitted } = useEmitText(value);
  const emit = (next: string) => { emitted.current = next; onChange(next); };

  // A prefilled or restored value opens in its own precision; an empty value keeps the chosen one.
  useEffect(() => {
    const own = precisionOf(value);
    if (own !== null && own !== mode) setMode(own);
  }, [value]);

  if (!precision) {
    const stored = value !== "" && !isFullIso(value);
    if (!stored) return <>{date(value, onChange)}</>;
    return (
      <View style={{ gap: 4 }}>
        <Input accessibilityLabel={label} placeholder="YYYY-MM-DD" maxLength={10} value={text} invalid={Boolean(error)} onChangeText={(next) => {
          setText(next);
          const ok = isFullIso(next);
          setError(ok || next === "" ? "" : "Enter a full date as YYYY-MM-DD.");
          if (ok || next === "") emit(next);
        }} />
        <FieldHint>Stored as a partial date. Enter a full date to replace it.</FieldHint>
        {error ? <FieldError>{error}</FieldError> : null}
      </View>
    );
  }

  const choose = (next: Precision) => {
    setError("");
    if (next === mode) return;
    const converted = convertPrecision(value, next);
    setMode(next);
    setText(converted);
    if (converted !== value) emit(converted);
  };
  const current = PRECISIONS.find((item) => item.value === mode)!;
  const field = mode === "date" ? date(value, onChange)
    : mode === "month" ? (month ? month(value, onChange) : <MonthYearFallback label={label} value={value} onChange={onChange} />)
      : year ? year(value, onChange) : (
        <Input accessibilityLabel={label} placeholder="Year" keyboardType="numeric" inputMode="numeric" maxLength={4} value={text} invalid={Boolean(error)} style={{ flexGrow: 1, flexBasis: 90, minWidth: 90 }} onChangeText={(next) => {
          const digits = next.replace(/\D/g, "");
          setText(digits);
          // No min or max: an out-of-range year is the V10 warning's business, not a block.
          const out = YEAR.test(digits) ? digits : "";
          if (out !== value) emit(out);
        }} />
      );
  return (
    <View style={{ gap: 4 }}>
      <View style={layout.row}>
        <MenuSelect triggerLabel={`${label} precision`} valueText={current.label} accessibilityValue={{ text: current.label }} selected={mode} style={{ minWidth: 130 }} onSelect={choose}
          options={PRECISIONS.map((item) => ({ value: item.value, label: item.label, accessibilityLabel: `${label} precision: ${item.label}` }))} />
        {field}
      </View>
      {error ? <FieldError>{error}</FieldError> : null}
    </View>
  );
}
