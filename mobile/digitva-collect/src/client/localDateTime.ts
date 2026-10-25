/**
 * Format a date as local ISO 8601 with a numeric offset and milliseconds.
 * Defaults to the current device time; throws RangeError for an invalid date.
 */
export function localDateTimeWithOffset(date = new Date()): string {
  if (Number.isNaN(date.getTime())) throw new RangeError("invalid_device_time");
  const offsetMinutes = date.getTimezoneOffset();
  const localDate = new Date(date.getTime() - offsetMinutes * 60_000);
  const pad = (value: number, width = 2) => String(value).padStart(width, "0");
  const sign = offsetMinutes <= 0 ? "+" : "-";
  const absoluteOffset = Math.abs(offsetMinutes);
  return `${localDate.getUTCFullYear()}-${pad(localDate.getUTCMonth() + 1)}-${pad(localDate.getUTCDate())}` +
    `T${pad(localDate.getUTCHours())}:${pad(localDate.getUTCMinutes())}:${pad(localDate.getUTCSeconds())}.` +
    `${pad(localDate.getUTCMilliseconds(), 3)}${sign}${pad(Math.floor(absoluteOffset / 60))}:${pad(absoluteOffset % 60)}`;
}
