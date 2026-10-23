/**
 * The deceased's name for a submitted-interview or revision row, or null.
 * Prefers the server's `deceased_name`; rows stored before that field fall
 * back to the prefill's given names and surname (only set when the case has
 * its identity). Never log the result: it is personal data.
 */
export function revisionName(row: { deceased_name?: string; prefill?: unknown }): string | null {
  if (row.deceased_name) return row.deceased_name;
  const d = (row.prefill as { deceased?: { givenNames?: unknown; surname?: unknown } } | undefined)?.deceased;
  const name = [d?.givenNames, d?.surname].filter((p): p is string => typeof p === "string" && p !== "").join(" ");
  return name || null;
}
