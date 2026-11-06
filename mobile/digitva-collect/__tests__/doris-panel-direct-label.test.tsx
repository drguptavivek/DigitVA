/** The DorisPanel save button: standalone coding is one direct step ("Save cause of death"); enrolled keeps "Save Step 1". */
import { readFileSync } from "node:fs";
import { join } from "node:path";

const source = readFileSync(join(__dirname, "../src/workspace/doris/DorisPanel.tsx"), "utf8");
const en = JSON.parse(readFileSync(join(__dirname, "../src/strings/en.json"), "utf8")) as Record<string, string>;

describe("DorisPanel direct label", () => {
  it("shows the direct string for direct and keeps Save Step 1 otherwise", () => {
    expect(en.dorisSaveCauseOfDeath).toBe("Save cause of death");
    expect(source).toContain('label={direct ? tr("dorisSaveCauseOfDeath") : isInitial ? "Save Step 1" : "Save final COD"}');
  });
});
