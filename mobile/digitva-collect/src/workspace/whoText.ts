/**
 * Small text and truthiness helpers shared by the ports of the server's WHO rules (icd11_postcoordination.py `_plain`,
 * doris_clinical.py `_plain_text`, icd11_titles.py). They keep Python's behaviour where it differs from JavaScript's:
 * `x or y` falls through on empty lists, dicts and strings, and a length is counted in code points.
 */

export type JsonRecord = Record<string, unknown>;

export function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Python truthiness of a JSON value: null, false, 0, "", [] and {} are falsy. */
export function truthy(value: unknown): boolean {
  if (Array.isArray(value)) return value.length > 0;
  if (isRecord(value)) return Object.keys(value).length > 0;
  return Boolean(value);
}

/** Python `a or b` for JSON values. */
export function or(first: unknown, second: unknown): unknown {
  return truthy(first) ? first : second;
}

/** Python `len(text)`: code points, not UTF-16 units. */
export function codePointLength(text: string): number {
  let count = 0;
  for (const _char of text) count += 1;
  return count;
}

function firstCodePoints(text: string, max: number): string {
  let out = "";
  let count = 0;
  for (const char of text) {
    if (count === max) break;
    out += char;
    count += 1;
  }
  return out;
}

const TAG_RE = /<[^>]+>/g;
// The entities WHO text carries; html.unescape knows the whole HTML5 table, which no WHO title uses.
const NAMED_ENTITIES: Record<string, string> = {
  amp: "&", lt: "<", gt: ">", quot: "\"", apos: "'", nbsp: " ",
  ndash: "–", mdash: "—", lsquo: "‘", rsquo: "’", ldquo: "“", rdquo: "”", hellip: "…",
};

/** Single-pass entity decoding (so `&amp;lt;` is `&lt;`, as html.unescape gives). Unknown or invalid entities stay as they are. */
export function unescapeHtml(text: string): string {
  return text.replace(/&(#[xX][0-9a-fA-F]+|#[0-9]+|[A-Za-z][A-Za-z0-9]*);/g, (whole, body: string) => {
    if (body[0] !== "#") return NAMED_ENTITIES[body] ?? whole;
    const point = body[1] === "x" || body[1] === "X" ? parseInt(body.slice(2), 16) : parseInt(body.slice(1), 10);
    return point >= 1 && point <= 0x10ffff && !(point >= 0xd800 && point <= 0xdfff) ? String.fromCodePoint(point) : whole;
  });
}

function stripAndDecode(text: string): string {
  return unescapeHtml(text.replace(TAG_RE, "")).trim();
}

/** A WHO text value that may be `{@value|label}`: the server's `_plain` of icd11_postcoordination.py (capped at `maxChars`). */
export function plain(value: unknown, maxChars = 200): string {
  const inner = isRecord(value) ? or(value["@value"], or(value.label, "")) : value;
  return typeof inner === "string" ? firstCodePoints(stripAndDecode(inner), maxChars) : "";
}

/** The server's `_plain_text` of doris_clinical.py and icd11_titles.py: also joins a list of strings, no cap. */
export function plainText(value: unknown): string {
  let inner = isRecord(value) ? or(value["@value"], or(value.label, "")) : value;
  if (Array.isArray(inner)) inner = inner.filter((item): item is string => typeof item === "string").join(" ");
  return typeof inner === "string" ? stripAndDecode(inner) : "";
}
