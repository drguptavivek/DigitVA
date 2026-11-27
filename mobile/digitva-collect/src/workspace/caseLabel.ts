/**
 * The short case number inside a masked case id: "PHC01-000020_172313647" -> "000020" (the register number, without
 * the project prefix and the trailing import stamp). Undefined for any other shape (including an id without the stamp), so callers show the id as given.
 */
export function shortCaseNumber(masked: string | null | undefined): string | undefined {
  return /-(\d{4,})_\d+$/.exec(masked ?? "")?.[1];
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * A queue card date as dd-mmm-yyyy ("03-Oct-2026"). A plain "YYYY-MM-DD" is that calendar day as written; a timestamp
 * is its day in the device's time zone, read as UTC when it has no offset (the server's naive columns are UTC, and
 * engines differ on an offset-less ISO time). Null for nothing or anything unreadable (never a guess).
 */
export function formatCardDate(raw: string | null | undefined): string | null {
  const text = (raw ?? "").trim();
  if (!text) return null;
  const plain = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
  let year: number; let month: number; let day: number;
  if (plain) {
    [year, month, day] = [Number(plain[1]), Number(plain[2]), Number(plain[3])];
  } else {
    const at = new Date(/T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(text) ? `${text}Z` : text);
    if (Number.isNaN(at.getTime())) return null;
    [year, month, day] = [at.getFullYear(), at.getMonth() + 1, at.getDate()];
  }
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  return `${String(day).padStart(2, "0")}-${MONTHS[month - 1]}-${year}`;
}

/**
 * The card's age with its unit, as `{unit, n}`: under 30 days in days, under a year in whole months (at least 1), else
 * in whole years (at least 1), from *days* (`va_deceased_age_normalized_days`); without it, *years* as given
 * (`va_deceased_age`). Null when neither is a usable number.
 */
export function cardAge(days: number | null | undefined, years: string | number | null | undefined): { unit: "d" | "m" | "y"; n: number } | null {
  if (typeof days === "number" && Number.isFinite(days) && days >= 0) {
    if (days < 30) return { unit: "d", n: Math.floor(days) };
    if (days < 365) return { unit: "m", n: Math.max(1, Math.floor(days / 30.4375)) };
    return { unit: "y", n: Math.max(1, Math.floor(days / 365.25)) };
  }
  const given = typeof years === "number" ? years : typeof years === "string" && years.trim() !== "" ? Number(years) : NaN;
  return Number.isFinite(given) && given >= 0 ? { unit: "y", n: Math.floor(given) } : null;
}
