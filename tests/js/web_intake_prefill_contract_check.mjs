// digitva-dyk: feeds prefill shapes built the same way
// app/services/web_intake_service.py::_prefill_from_death builds them
// (after the fix -- never both deceased.dateOfDeath and deceased.yearOfDeath)
// into the *real* vendored package function, not a re-implementation of it.
//
// Run (needs TS support -- vendor/who-va-2022 already has tsx installed;
// this repo's root does not, and nothing here may add or edit anything
// under vendor/who-va-2022 or app/static/vendor):
//   vendor/who-va-2022/node_modules/.bin/tsx tests/js/web_intake_prefill_contract_check.mjs
// No test runner: throws (non-zero exit) on failure, prints OK on success.
import { createWhoVaInitialDataFromPrefill } from "../../vendor/who-va-2022/src/prefill.ts";

function assertNoThrow(label, prefill) {
  let data;
  try {
    data = createWhoVaInitialDataFromPrefill(prefill);
  } catch (e) {
    throw new Error(`${label}: prefill was rejected (${e.message}) -- the page would silently drop it`);
  }
  return data;
}

// Case 1: a death-register row with only an age (no date of birth) -- what
// _prefill_from_death sends for most registered deaths today.
const ageOnly = assertNoThrow("age-only death", {
  interviewer: { name: "Web Interviewer", id: "11111111-1111-1111-1111-111111111111" },
  deceased: { givenNames: "Asha", surname: "Devi", sex: "female", dateOfDeath: "2026-09-01", ageInYears: 62 },
  answers: {},
});
if (!("Id10022" in ageOnly) || ageOnly.Id10022 !== "yes") throw new Error("dateOfDeath did not set Id10022=yes");
if (!("Id10023_b" in ageOnly)) throw new Error("dateOfDeath (no DOB) should set Id10023_b");
if ("Id10024" in ageOnly) throw new Error("yearOfDeath must never be sent when dateOfDeath is known (Id10024 set)");
if (ageOnly.age_adult !== 62) throw new Error("ageInYears did not set age_adult");
if ("Id10021" in ageOnly) throw new Error("no dateOfBirth was given, Id10021 should be unset");

// Case 2: a death-register row with a known date of birth.
const withDob = assertNoThrow("death with date of birth", {
  interviewer: { name: "Web Interviewer", id: "11111111-1111-1111-1111-111111111111" },
  deceased: { givenNames: "Ram", surname: "Kumar", sex: "male", dateOfDeath: "2026-09-01", dateOfBirth: "1960-01-01" },
  answers: {},
});
if (!("Id10023_a" in withDob)) throw new Error("dateOfDeath with a known DOB should set Id10023_a, not _b");
if ("age_adult" in withDob) throw new Error("dateOfBirth and ageInYears must never both be sent (age_adult set)");

// The contract itself, read only: confirms *why* the server-side fix is
// required -- the vendored function still rejects the pair it used to send.
let rejected = false;
try {
  createWhoVaInitialDataFromPrefill({ deceased: { dateOfDeath: "2026-09-01", yearOfDeath: "2026" } });
} catch (e) {
  rejected = /dateOfDeath.*yearOfDeath/.test(e.message);
}
if (!rejected) throw new Error("expected prefill.ts to still reject dateOfDeath+yearOfDeath together");

console.log("OK: web intake prefill contract holds for the vendored package function");
