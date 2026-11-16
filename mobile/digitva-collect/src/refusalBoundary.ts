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

/**
 * The respondent agreed on the consent screens (owner 2026-11-13): answer the WHO consent question Id10013 "yes" so
 * the interviewer is not asked twice. Only an empty Id10013 is filled; an existing "yes" or "no" is never changed.
 */
export function withConsentAgreed<T extends object>(data: T | undefined, decision?: string | null): T | undefined {
  if (decision !== "granted") return data;
  const current = (data as Record<string, unknown> | undefined)?.Id10013;
  if (current !== undefined && current !== null && String(current).trim() !== "") return data;
  return { ...(data ?? {}), Id10013: "yes" } as unknown as T;
}

/** Structural slice of WhoVaSession that the consent-page check needs. */
export type ConsentSession = {
  getSnapshot(): { data: object; questions: ReadonlyArray<{ name: string }> };
  setAnswer(name: string, value: string): void;
};

/**
 * When the page that asks Id10013 is shown (a form opened on it, a section change to it, a saved draft restored
 * onto it) and the respondent agreed, answer it "yes" through the form's own answer path so the draft save keeps it.
 * Idempotent: call it on every form change and ready.
 */
export function agreeConsentOnPage(session: ConsentSession | undefined, decision?: string | null): void {
  if (!session || decision !== "granted") return;
  const snapshot = session.getSnapshot();
  if (!snapshot.questions.some((question) => question.name === "Id10013")) return;
  if (withConsentAgreed(snapshot.data, decision) !== snapshot.data) session.setAnswer("Id10013", "yes");
}
