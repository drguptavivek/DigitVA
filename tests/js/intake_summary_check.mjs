// digitva-vzk.1: the pinned summary's age for an age-only case.
// Run: node tests/js/intake_summary_check.mjs (no test runner; throws on failure).
import { summaryAge, summaryFromAnswers, summaryFromPrefill } from "../../app/static/js/intake/summary.js";

const eq = (actual, expected, label) => {
  if (actual !== expected) throw new Error(`${label}: expected ${expected}, got ${actual}`);
};

// Age only, no date of birth: the form's ageInYears calculation is NaN.
const ageOnly = { Id10017: "Ram", Id10018: "Kumar", Id10019: "male", Id10023: "2026-09-01",
  ageInYears: NaN, ageInYears2: 64, age_adult: 64 };
eq(summaryFromAnswers(ageOnly).age, 64, "age-only answers");
eq(summaryFromAnswers(ageOnly).dod, "01-Sep-2026", "date of death");
eq(summaryFromAnswers(ageOnly).name, "Ram Kumar", "name");
eq(summaryAge({ ageInYears: "NaN", age_adult: 70 }), 70, "NaN as a string");
eq(summaryAge({ age_group: "child", age_child_years: 5 }), 5, "child years");
eq(summaryAge({ ageInYears: 30, age_adult: 64 }), 30, "dates win");
eq(summaryAge({ ageInYears: 0 }), 0, "zero is an age");
eq(summaryAge({}), undefined, "nothing answered");

// Before the form answers anything: the server prefill.
eq(summaryFromPrefill({ deceased: { givenNames: "Ram", ageInYears: 64, sex: "male" } }).age, 64, "prefill adult");
eq(summaryFromPrefill({ deceased: {}, answers: { age_child_years: 5 } }).age, 5, "prefill child");
eq(summaryFromPrefill({}).age, undefined, "empty prefill");

console.log("OK: intake summary age");
