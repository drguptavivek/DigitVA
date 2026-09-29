// Pinned deceased summary of the web intake form (digitva-wdj): name, date
// of death, age and sex from the answers the host hands draftStore.save().
// Pure: no DOM, no network; tests/js/intake_summary_check.mjs runs it in node.

export const SUMMARY_SEX_LABELS = { female: "Female", male: "Male", undetermined: "Undetermined" };
const SUMMARY_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function formatSummaryDate(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  if (!m) return undefined;
  const [, y, mo, d] = m;
  const mi = Number(mo) - 1;
  return mi >= 0 && mi <= 11 ? `${d}-${SUMMARY_MONTHS[mi]}-${y}` : undefined;
}

const finiteNumber = (value) => {
  if (value == null || value === "") return undefined;
  const n = Number(value);
  return Number.isFinite(n) ? n : undefined;
};

// The age shown: the first finite one of the calculated age from the dates
// (ageInYears), the calculated age from the age-group answers (ageInYears2),
// then the raw adult or child years. ageInYears is NaN without a date of
// birth -- NaN is not null, so a plain `!= null` check hid an age-only
// case's age (digitva-vzk.1).
export function summaryAge(data) {
  for (const key of ["ageInYears", "ageInYears2", "age_adult", "age_child_years"]) {
    const n = finiteNumber(data[key]);
    if (n !== undefined) return n;
  }
  return undefined;
}

export function summaryFromAnswers(data) {
  if (!data) return {};
  const name = [data.Id10017, data.Id10018].filter(Boolean).join(" ") || undefined;
  return {
    name,
    dod: formatSummaryDate(data.Id10023),
    age: summaryAge(data),
    sex: SUMMARY_SEX_LABELS[data.Id10019],
  };
}

// The summary before the form has answered anything, from the server prefill.
export function summaryFromPrefill(prefill) {
  const deceased = (prefill && prefill.deceased) || {};
  const answers = (prefill && prefill.answers) || {};
  return {
    name: [deceased.givenNames, deceased.surname].filter(Boolean).join(" ") || undefined,
    dod: formatSummaryDate(deceased.dateOfDeath),
    age: finiteNumber(deceased.ageInYears) ?? finiteNumber(answers.age_child_years),
    sex: SUMMARY_SEX_LABELS[deceased.sex],
  };
}
