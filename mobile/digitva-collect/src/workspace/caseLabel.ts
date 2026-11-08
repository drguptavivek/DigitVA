/**
 * The short case number inside a masked case id: "PHC01-000020_172313647" -> "000020" (the register number, without
 * the project prefix and the trailing import stamp). Undefined for any other shape (including an id without the stamp), so callers show the id as given.
 */
export function shortCaseNumber(masked: string | null | undefined): string | undefined {
  return /-(\d{4,})_\d+$/.exec(masked ?? "")?.[1];
}
