// Functional check of the engine's answer data types.
//
//   cd tooling/who-va-2022 && npm run check:types
//
// The vendored engine has no node_modules here, so its own vitest suite cannot
// run in this repo. This exercises the same code through the built validator
// bundle instead: it compiles a synthetic instrument (which runs the
// control -> dataType allow-list in engine/instrument-model.ts) and validates
// answers against it (engine/validation.ts). Covers the types DigitVA added on
// top of the WHO set: decimal, time, datetime, barcode, range and geopoint.
import { validateSubmission } from "./dist-node/validator-bundle.mjs";

const q = (name, control, dataType) => ({
  name, order: 0, sourceRow: 1, sourceType: control, dataType, control,
  label: { en: name }, hint: {}, guidance: {}, required: false, readOnly: false,
  constraintMessage: {}, validation: { required: false, dataType, constraintMessage: {} },
  sectionPath: ["s"], ageGroup: "ALL"
});
const instrument = {
  id: "t", title: "T", version: "1", defaultLanguage: "en", sourceFile: "t.xlsx",
  sections: [{ name: "s", sourceRow: 1, order: 0, label: { en: "S" }, ageGroup: "ALL" }],
  questions: [
    q("d", "decimal", "decimal"),
    q("i", "integer", "number"),
    q("t", "time", "time"),
    q("dt", "datetime", "dateTime"),
    q("b", "barcode", "string"),
    q("r", "range", "number"),
    q("g", "geopoint", "geopoint")
  ]
};
const check = (label, data, expectValid) => {
  const r = validateSubmission(instrument, data);
  const ok = r.valid === expectValid;
  console.log(`${ok ? "PASS" : "FAIL"}  ${label} -> valid=${r.valid}` +
    (ok ? "" : ` issues=${JSON.stringify(r.issues)}`));
  return ok;
};
let all = true;
all &= check("decimal accepts 1.5", { d: 1.5 }, true);
all &= check("decimal accepts whole 2", { d: 2 }, true);
all &= check("decimal rejects text", { d: "1.5" }, false);
all &= check("integer still rejects 1.5", { i: 1.5 }, false);
all &= check("integer accepts 3", { i: 3 }, true);
all &= check("time accepts 14:30", { t: "14:30" }, true);
all &= check("time accepts 14:30:05", { t: "14:30:05" }, true);
all &= check("time rejects 25:00", { t: "25:00" }, false);
all &= check("time rejects 2pm", { t: "2pm" }, false);
all &= check("datetime accepts ISO", { dt: "2026-09-18T14:30:00Z" }, true);
all &= check("datetime rejects nonsense", { dt: "not-a-time" }, false);
all &= check("barcode accepts a string", { b: "ABC-123" }, true);
all &= check("range accepts an integer", { r: 4 }, true);
all &= check("range rejects a string", { r: "4" }, false);
all &= check("geopoint accepts lat lon", { g: "28.6139 77.2090" }, true);
all &= check("geopoint accepts lat lon alt acc", { g: "28.6139 77.2090 216 5" }, true);
all &= check("geopoint rejects impossible latitude", { g: "91.0 77.2090" }, false);
all &= check("geopoint rejects one number", { g: "28.6139" }, false);
all &= check("geopoint rejects text", { g: "Delhi" }, false);
process.exit(all ? 0 : 1);
