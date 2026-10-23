/**
 * Search matching for phone lists. NFC-normalised and case-folded so a Hindi query typed with a different
 * Unicode form (decomposed nukta, for example) still matches; combining marks are kept, because dropping
 * Devanagari matras would make "राम" and "रम" the same word.
 */
export function normaliseSearch(value: string | null | undefined): string {
  return (value ?? "").normalize("NFC").toLocaleLowerCase().replace(/\s+/g, " ").trim();
}

/** Every whitespace-separated word of the query appears in some field. An empty query matches everything. */
export function matchesSearch(fields: Array<string | null | undefined>, query: string): boolean {
  const words = normaliseSearch(query).split(" ").filter(Boolean);
  if (words.length === 0) return true;
  const haystack = fields.map(normaliseSearch).join("\n");
  return words.every((word) => haystack.includes(word));
}
