// Words the server joins into keys that title-casing alone gets wrong ("vacoder" -> "Vacoder").
const WORDS: Record<string, string> = {
  va: "VA", cod: "COD", smartva: "SmartVA", icd: "ICD", nqa: "NQA", odk: "ODK",
  vasystem: "system", vacoder: "coder", vareviewer: "reviewer", vaadmin: "admin",
};

/** A raw state or section key ("risk_factors") as a phone label ("Risk factors"); anything else is returned as is. */
export function humanizeKey(value: string): string {
  if (!/^[a-z0-9]+(?:_[a-z0-9]+)*$/.test(value)) return value;
  const words = value.split("_").map((word) => WORDS[word] ?? word).join(" ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
