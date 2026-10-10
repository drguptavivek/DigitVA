// Reloading a saved draft must open its saved questionnaire section directly.
// Run: node tests/js/web_intake_reload_restore_check.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const template = readFileSync(new URL("../../app/templates/va_frontpages/va_intake_form.html", import.meta.url), "utf8");
const match = template.match(/if \(([^\n]+extensions\.includes\("intake_screen"\)[^\n]*)\) \{/);
assert.ok(match, "welcome screen condition exists in the intake form");
const shouldShowWelcome = new Function("DRAFT", "extensions", "options", `return ${match[1]};`);

const extensions = ["intake_screen"];
const options = { intake_note: "Read this before starting." };
assert.equal(Boolean(shouldShowWelcome({}, extensions, options)), true, "new draft shows the welcome screen");
assert.equal(Boolean(shouldShowWelcome({ current_section: "info_on_deceased" }, extensions, options)), false,
  "reloaded draft skips the welcome screen and restores its saved section");
assert.equal(Boolean(shouldShowWelcome({}, [], options)), false, "projects without intake_screen skip the welcome screen");
assert.equal(Boolean(shouldShowWelcome({}, extensions, { intake_note: "" })), false, "empty welcome note skips the screen");

console.log("OK: web intake reload restores the saved questionnaire section");
