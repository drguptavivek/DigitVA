/**
 * Locale-aware conversion between canonical ISO dates and the text-based date
 * format used when a platform-native date picker is unavailable.
 */
import { isValidIsoDate } from "../date.js";

type DatePart = "day" | "month" | "year";

function localizedMonthNames(locale: string): string[] {
  return Array.from({ length: 12 }, (_, month) =>
    new Intl.DateTimeFormat(locale, {
      month: "short",
      timeZone: "UTC"
    })
      .format(new Date(Date.UTC(2000, month, 1)))
      .replace(/\.$/, "")
  );
}

function localizedDateOrder(locale: string): DatePart[] {
  const order = new Intl.DateTimeFormat(locale, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "UTC"
  })
    .formatToParts(new Date(Date.UTC(2000, 10, 22)))
    .map((part) => part.type)
    .filter((part): part is DatePart => part === "day" || part === "month" || part === "year");
  return order.length === 3 ? order : ["day", "month", "year"];
}

function displayDateParts(day: string, month: string, year: string, locale: string): string {
  const values: Record<DatePart, string> = { day, month, year };
  return localizedDateOrder(locale)
    .map((part) => values[part])
    .join("-");
}

export function dateFormatPlaceholder(locale: string): string {
  return displayDateParts("DD", "MMM", "YYYY", locale);
}

export function formatDisplayDate(value: string, locale: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return value;
  const month = Number(match[2]);
  const monthName = localizedMonthNames(locale)[month - 1];
  return monthName ? displayDateParts(match[3] ?? "", monthName, match[1] ?? "", locale) : value;
}

export function parseDisplayDate(value: string, locale: string): string | undefined {
  const tokens = value.trim().split("-");
  if (tokens.length !== 3) return undefined;
  const localizedParts = Object.fromEntries(
    localizedDateOrder(locale).map((part, index) => [part, tokens[index]])
  ) as Partial<Record<DatePart, string>>;
  const dayToken = localizedParts.day;
  const monthToken = localizedParts.month?.replace(/\.$/, "").toLocaleLowerCase(locale);
  const yearToken = localizedParts.year;
  if (!dayToken || !monthToken || !yearToken || !/^\d{1,2}$/.test(dayToken) || !/^\d{4}$/.test(yearToken))
    return undefined;
  const localizedMonths = localizedMonthNames(locale).map((month) => month.toLocaleLowerCase(locale));
  const englishMonths = localizedMonthNames("en").map((month) => month.toLowerCase());
  let monthIndex = localizedMonths.indexOf(monthToken);
  if (monthIndex < 0) monthIndex = englishMonths.indexOf(monthToken.toLowerCase());
  const day = Number(dayToken);
  const year = Number(yearToken);
  if (monthIndex < 0 || day < 1 || day > 31) return undefined;
  const isoDate = `${String(year).padStart(4, "0")}-${String(monthIndex + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  return isValidIsoDate(isoDate) ? isoDate : undefined;
}
