import { computeUtf8Sha256HexSync } from "./consent";

/** Exact JSON value identity, independent of Python/JS numeric and Unicode JSON formatting.
 * Values are tagged; finite numbers use their big-endian IEEE754 bytes, with -0 equal to 0.
 * Objects sort by Unicode code point; ASCII JSON escaping also preserves lone surrogates.
 */
export function codingReceiptSha256(value: unknown): string {
  const tagged = (item: unknown): unknown => {
    if (item === null) return ["null"];
    if (typeof item === "string" || typeof item === "boolean") return [typeof item, item];
    if (typeof item === "number") {
      if (!Number.isFinite(item)) throw new Error("invalid_offline_coding_number");
      const bytes = new DataView(new ArrayBuffer(8));
      bytes.setFloat64(0, item === 0 ? 0 : item, false);
      return ["number", Array.from({ length: 8 }, (_, index) => bytes.getUint8(index).toString(16).padStart(2, "0")).join("")];
    }
    if (Array.isArray(item)) return ["array", item.map(tagged)];
    if (typeof item !== "object") throw new Error("invalid_offline_coding_value");
    const record = item as Record<string, unknown>;
    const keys = Object.keys(record).sort((left, right) => {
      const a = Array.from(left, (letter) => letter.codePointAt(0)!);
      const b = Array.from(right, (letter) => letter.codePointAt(0)!);
      for (let index = 0; index < Math.min(a.length, b.length); index += 1) {
        if (a[index] !== b[index]) return a[index] - b[index];
      }
      return a.length - b.length;
    });
    return ["object", keys.map((key) => [key, tagged(record[key])])];
  };
  const text = JSON.stringify(tagged(value)).replace(/[\u007f-\uffff]/g, (character) =>
    `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`);
  return computeUtf8Sha256HexSync(text);
}
