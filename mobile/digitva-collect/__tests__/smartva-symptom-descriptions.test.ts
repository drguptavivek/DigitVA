import { execFileSync } from "node:child_process";
import path from "node:path";

it("keeps the safe symptom list in sync with every bundled Rust description", () => {
  expect(() => execFileSync(process.execPath, [path.join(__dirname, "../scripts/generate-smartva-symptoms.cjs"), "--check"])).not.toThrow();
});
