/** Refusal of either the interview or the data-protection notice stops the interview. */
export function isRefused(data: Record<string, unknown> | undefined, decision?: string | null): boolean {
  return data?.Id10013 === "no" || decision === "refused";
}

/** Only the optional, deliberately broad refusal profile and an actual WHO decision may remain. */
export function refusalAnswers(data: Record<string, unknown> | undefined): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  if (data?.Id10013 === "yes" || data?.Id10013 === "no") result.Id10013 = data.Id10013;
  if (["neonate", "child", "15_49y", "50_64y", "65_plus", "unknown"].includes(String(data?.refusal_age_group))) {
    result.refusal_age_group = data?.refusal_age_group;
  }
  if (["male", "female", "unknown"].includes(String(data?.refusal_sex))) result.refusal_sex = data?.refusal_sex;
  return result;
}
