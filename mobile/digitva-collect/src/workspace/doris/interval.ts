// ISO 8601 duration <-> number + unit, ported from app/static/js/doris_interval.js
// so the mobile and web DORIS editors read and write the same strings.

export const INTERVAL_UNITS = [
  { value: "Y", label: "Years", prefix: "P" },
  { value: "M", label: "Months", prefix: "P" },
  { value: "W", label: "Weeks", prefix: "P" },
  { value: "D", label: "Days", prefix: "P" },
  { value: "H", label: "Hours", prefix: "PT" },
  { value: "MI", label: "Minutes", prefix: "PT" },
  { value: "S", label: "Seconds", prefix: "PT" },
] as const;

export const UNKNOWN_UNIT = "unknown";

export type ParsedInterval = { value: string; unit: string; representable: boolean };

/** Splits a stored duration; non-representable values (for example P1Y2M) are reported, never rewritten. */
export function parseInterval(raw: unknown): ParsedInterval {
  const value = typeof raw === "string" ? raw.trim() : "";
  let match = value.match(/^P(\d+(?:\.\d+)?)(Y|M|W|D)$/);
  if (!match) {
    match = value.match(/^PT(\d+(?:\.\d+)?)(H|M|S)$/);
    if (match && match[2] === "M") match[2] = "MI";
  }
  if (match) return { value: match[1], unit: match[2], representable: true };
  if (value === "P" || value === "PT") return { value: "", unit: UNKNOWN_UNIT, representable: true };
  return { value: "", unit: "", representable: false };
}

/** Builds the duration string; `error` is non-empty when the pair cannot be saved. */
export function serializeInterval(value: string, unit: string): { value: string; error: string } {
  const number = value.trim();
  const selected = unit.trim();
  if (number === "" && (selected === "" || selected === UNKNOWN_UNIT)) return { value: "", error: "" };
  if (selected === "") return { value: "", error: "Choose a time unit." };
  if (selected === UNKNOWN_UNIT) return { value: "", error: "Remove the value or choose a time unit." };
  if (!/^\d+(?:\.\d+)?$/.test(number)) return { value: "", error: "Enter a non-negative number." };
  const matched = INTERVAL_UNITS.find((item) => item.value === selected);
  if (!matched) return { value: "", error: "Choose a valid time unit." };
  return { value: `${matched.prefix}${number}${selected === "MI" ? "M" : selected}`, error: "" };
}
