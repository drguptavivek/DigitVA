// The worklist chips map to the API query (state set and order) and Recent is
// the union of the status chips. Run: node tests/js/intake_worklist_chips_check.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../../app/static/js/intake/intake_worklist.js", import.meta.url), "utf8");
const start = source.indexOf("// ---- Chips: filter chip -> API query");
const end = source.indexOf("// ---- end chips ----");
assert.ok(start !== -1 && end > start, "chip mapping block is present in intake_worklist.js");
const { chipQuery, CHIP_STATES } = new Function(`${source.slice(start, end)}; return { chipQuery: chipQuery, CHIP_STATES: CHIP_STATES };`)();

assert.deepEqual(chipQuery("visit", false), { states: ["registered", "scheduled", "not_reachable", "paused"], sort: "next_visit", mine: false });
assert.deepEqual(chipQuery("progress", true), { states: ["in_progress", "draft_identity"], sort: "next_visit", mine: true });
assert.deepEqual(chipQuery("done", false).states, ["submitted", "refused", "duplicate", "cancelled"]);

const recent = chipQuery("recent", false);
assert.equal(recent.sort, "reported", "Recent is newest reported first");
assert.equal(recent.states.length, 10, "Recent covers every state the worklist serves");
assert.deepEqual([...recent.states].sort(), [...CHIP_STATES.visit, ...CHIP_STATES.progress, ...CHIP_STATES.done].sort());

assert.equal(chipQuery("nonsense", false).sort, "reported", "an unknown chip falls back to Recent");
assert.equal(chipQuery("constructor", false).states, CHIP_STATES.recent, "inherited object keys do not select a chip");
assert.equal(chipQuery("visit", undefined).mine, false, "Mine is strictly true or false");

console.log("OK: worklist chips map to the expected states and order");
