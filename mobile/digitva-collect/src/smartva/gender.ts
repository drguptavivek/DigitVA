/** Gender text as the server shows it (engine.rs): 1 = Male, 2 = Female, anything else Missing. Accepts the words too. */
export function genderLabel(raw: string | null | undefined): "Male" | "Female" | "Missing" {
  const text = (raw ?? "").trim();
  if (text === "Male" || text === "Female") return text;
  const code = Number(text);
  return text !== "" && code === 1 ? "Male" : text !== "" && code === 2 ? "Female" : "Missing";
}
