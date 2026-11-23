/** Age constants and the WHO 2022 age-group boundaries, shared by coding and DORIS (mirror of icd_coding_policy). */

export type AgeGroup = "neonate" | "infant" | "child" | "adult";

export const DAYS_PER_MONTH = 30.4375;
export const DAYS_PER_YEAR = 365.25;

/** neonate/infant/child/adult by the WHO 2022 boundaries (icd_coding_policy.coding_age_group_for_submission). */
export function ageGroupForDays(days: number | null): AgeGroup | null {
  if (days === null) return null;
  if (days < 28) return "neonate";
  if (days < 365) return "infant";
  return days < 12 * DAYS_PER_YEAR ? "child" : "adult";
}
