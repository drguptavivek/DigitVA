import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

// The Rust source lives in the vendor/smartva-analyze submodule, which CI release builds do not check out;
// the generated list is committed, so the sync check runs wherever the submodule is present.
const rustData = path.join(__dirname, "../../../vendor/smartva-analyze/rust/src/data");
const whereSourcePresent = fs.existsSync(path.join(rustData, "adult_tariff_data.rs")) ? it : it.skip;

whereSourcePresent("keeps the safe symptom list in sync with every bundled Rust description", () => {
  expect(() => execFileSync(process.execPath, [path.join(__dirname, "../scripts/generate-smartva-symptoms.cjs"), "--check"])).not.toThrow();
});
