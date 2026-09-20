// Emit vendor/who-va-2022/src/generated/expression-conformance-corpus.json:
// every unique XLSForm expression the composed instrument (WHO base plus
// every DigitVA extension) actually carries in `relevant`, `constraint` or
// `calculation`, evaluated by the real TypeScript engine
// (vendor/who-va-2022/src/engine/expression.ts) against a set of answer
// fixtures designed to exercise real branches. The golden results this
// writes are what app/services/xform_expression_evaluator.py's Python port
// is graded against (tests/services/test_xform_expression_evaluator.py) --
// see beads digitva-cal.1 and docs/policy/xform-expression-evaluator.md.
//
//   cd tooling/who-va-2022 && npm run build:expression-corpus
//
// `today()` depends on wall-clock date, so the corpus fixes both an
// explicit `now` and the IANA zone it is read in (TZ is pinned before any
// Date is touched) rather than using the real current time -- otherwise
// regenerating the corpus tomorrow, or on a host in a different timezone,
// would not reproduce today's file. Asia/Kolkata matches this application's
// primary deployment timezone.
//
// Determinism follows build-layer-reference.mjs's pattern: no timestamp, no
// build id, sorted keys, sorted entries, so re-running this on an unmodified
// tree reproduces the committed file byte for byte (pinned by
// tests/build-expression-corpus.test.mjs).
process.env.TZ = "Asia/Kolkata";

import { build } from "esbuild";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";

import { stableStringify } from "./build-layer-reference.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "..", "..");
const vendorSrc = path.join(repo, "vendor", "who-va-2022", "src");
const outPath = path.join(
  repo,
  "vendor",
  "who-va-2022",
  "src",
  "generated",
  "expression-conformance-corpus.json"
);
const vendorPackage = JSON.parse(readFileSync(path.join(repo, "vendor", "who-va-2022", "package.json"), "utf8"));

// The instant every corpus case's today()/date arithmetic is evaluated
// against. No offset ("Z") on purpose: parsed as wall-clock time in the
// process's TZ, the same way expression.ts's own `formatLocalDate` reads a
// Date's local getters -- pinning TZ above is what makes that
// reproducible across hosts.
const NOW_ISO = "2024-06-15T09:00:00";
const TIMEZONE = "Asia/Kolkata";

// A digit string in Devanagari, the divergence case from beads digitva-cal.1:
// Python's `re` matches \d against Unicode digits by default; JavaScript's
// RegExp does not. "१२३" reads as 123.
const DEVANAGARI_123 = "१२३";

async function loadEngineModule() {
  const tmpDir = mkdtempSync(path.join(tmpdir(), "whova-expression-corpus-"));
  const entryPath = path.join(tmpDir, "entry.mjs");
  const outfile = path.join(tmpDir, "bundle.mjs");
  writeFileSync(
    entryPath,
    [
      `export { createWhoVa2022Instrument } from ${JSON.stringify(path.join(vendorSrc, "instrument.js"))};`,
      `export { ALL_DIGITVA_EXTENSIONS } from ${JSON.stringify(path.join(vendorSrc, "digitva-extension.js"))};`,
      `export { parseExpression, evaluateExpression } from ${JSON.stringify(
        path.join(vendorSrc, "engine", "expression.js")
      )};`
    ].join("\n")
  );
  try {
    await build({
      entryPoints: [entryPath],
      bundle: true,
      format: "esm",
      platform: "node",
      outfile,
      logLevel: "warning",
      nodePaths: [path.join(here, "node_modules")]
    });
    return await import(pathToFileURL(outfile).href);
  } finally {
    rmSync(tmpDir, { recursive: true, force: true });
  }
}

/** Every `${name}` reference an AST touches, plus whether it reads `.` (the current node). */
export function collectReferences(node, into = { names: new Set(), usesCurrent: false }) {
  if (!node || typeof node !== "object") return into;
  if (node.type === "reference") into.names.add(node.name);
  if (node.type === "current") into.usesCurrent = true;
  if (node.type === "unary") collectReferences(node.operand, into);
  if (node.type === "binary") {
    collectReferences(node.left, into);
    collectReferences(node.right, into);
  }
  if (node.type === "call") for (const argument of node.arguments) collectReferences(argument, into);
  return into;
}

/** Reduce a question's control/dataType to one of the fixture families below. */
function fixtureKind(info) {
  if (!info) return "unknown";
  if (["singleChoice", "multipleChoice", "integer", "date", "confirm", "text"].includes(info.control)) {
    return info.control;
  }
  // "calculated" and anything else: fall back to the declared data type.
  if (info.dataType === "number") return "integer";
  if (info.dataType === "string[]") return "multipleChoice";
  if (info.dataType === "date") return "date";
  if (info.dataType === "boolean") return "confirm";
  return "text";
}

/**
 * Four candidate values per field, chosen to land on both sides of the
 * comparisons the instrument actually makes (an empty answer, a real choice
 * value so `selected()` can go true, a value outside any choice list so it
 * can go false, numbers/dates either side of the boundaries the instrument
 * checks). A 5th candidate -- a Devanagari-digit string -- is appended only
 * for fields a `\d`-bearing regex touches, so that divergence has its own
 * case per field rather than only the one hardcoded expression.
 */
function candidatesForField(info, hasBackslashD) {
  const kind = fixtureKind(info);
  let base;
  if (hasBackslashD && kind !== "multipleChoice") {
    // Tailored so the regex actually swings both ways: "007" is 1-3 digits
    // not all zero (true), "000" is all zero (false, the lookahead this
    // pattern exists for), "notdigits" has no digits at all (false). The
    // Devanagari candidate appended below is the real point: JavaScript's
    // \d is ASCII-only, so it reads as false there, and must read the same
    // in Python (re.ASCII), not true (default Python \d is Unicode-aware).
    base = ["", "007", "000", "notdigits"];
  } else if (kind === "singleChoice") {
    const values = info.choices.length ? info.choices : ["only_choice"];
    base = ["", values[0], values[1] ?? values[0], "not_a_real_choice"];
  } else if (kind === "multipleChoice") {
    const values = info?.choices?.length ? info.choices : ["only_choice"];
    base = [[], [values[0]], [values[0], values[1] ?? values[0]], ["not_a_real_choice"]];
  } else if (kind === "integer") {
    base = ["", 0, -3, "12"];
  } else if (kind === "date") {
    base = ["", "1915-01-01", "2020-06-15", "2099-01-01"]; // brackets NOW_ISO (2024-06-15)
  } else if (kind === "confirm") {
    base = ["", true, false, "0"];
  } else if (kind === "unknown") {
    base = ["", "generic-text", 7, "2020-06-15"];
  } else {
    base = ["", "hello world", "0", "  "];
  }
  if (!hasBackslashD) return base;
  const digitCandidate = kind === "multipleChoice" ? [DEVANAGARI_123] : DEVANAGARI_123;
  return [...base, digitCandidate];
}

function buildScenarios({ refs, usesCurrent, refCandidates, currentCandidates }) {
  const scenarios = [];
  scenarios.push({ name: "missing", data: {}, currentValue: undefined });

  // Usually 4 (every base candidate list is length 4); a field the
  // Devanagari-digit divergence case touches carries a 5th candidate, and
  // this makes sure index 4 actually gets exercised instead of being
  // truncated away.
  const indexCount = Math.max(4, ...refs.map((r) => refCandidates[r].length), usesCurrent ? currentCandidates.length : 0);
  for (let i = 0; i < indexCount; i += 1) {
    const data = {};
    for (const ref of refs) data[ref] = refCandidates[ref][i % refCandidates[ref].length];
    const currentValue = usesCurrent ? currentCandidates[i % currentCandidates.length] : undefined;
    scenarios.push({ name: `candidate_${i}`, data, currentValue });
  }

  // A constraint invocation always supplies `.`; a relevant/calculation
  // invocation never does (see vendor/who-va-2022/src/engine/validation.ts).
  // The corpus is keyed by expression text, not by which field it is used
  // in, so both invocation shapes get a case whenever `.` appears at all.
  if (usesCurrent) {
    const data = {};
    for (const ref of refs) data[ref] = refCandidates[ref][1 % refCandidates[ref].length];
    scenarios.push({ name: "current_value_omitted", data, currentValue: undefined });
  }

  // A second variable shifted relative to the first exercises expressions
  // that compare two references to each other, which same-index scenarios
  // never can.
  const variableCount = refs.length + (usesCurrent ? 1 : 0);
  if (variableCount >= 2) {
    const data = {};
    refs.forEach((ref, position) => {
      const candidates = refCandidates[ref];
      data[ref] = candidates[(position + 1) % candidates.length];
    });
    const currentValue = usesCurrent ? currentCandidates[(refs.length + 1) % currentCandidates.length] : undefined;
    scenarios.push({ name: "shifted", data, currentValue });
  }

  return scenarios;
}

function stripUndefined(data) {
  const clean = {};
  for (const [key, value] of Object.entries(data)) if (value !== undefined) clean[key] = value;
  return clean;
}

async function main() {
  const { createWhoVa2022Instrument, ALL_DIGITVA_EXTENSIONS, parseExpression, evaluateExpression } =
    await loadEngineModule();
  const composed = createWhoVa2022Instrument(ALL_DIGITVA_EXTENSIONS);

  const questionsByName = new Map(
    composed.questions.map((q) => [
      q.name,
      { control: q.control, dataType: q.dataType, listName: q.listName, choices: (q.choices ?? []).map((c) => c.value) }
    ])
  );

  // Unique expression source -> the set of question infos that use it as a
  // constraint (i.e. read `.`), for typing the current-node candidates.
  const sources = new Map();
  const record = (source, ownerInfo) => {
    if (!sources.has(source)) sources.set(source, { constraintOwners: [] });
    if (ownerInfo) sources.get(source).constraintOwners.push(ownerInfo);
  };
  for (const section of composed.sections) if (section.relevant) record(section.relevant.source, null);
  for (const question of composed.questions) {
    const info = questionsByName.get(question.name);
    if (question.relevant) record(question.relevant.source, null);
    if (question.constraint) record(question.constraint.source, info);
    if (question.calculation) record(question.calculation.source, null);
  }

  const now = new Date(NOW_ISO);
  const entries = [];
  for (const [source, meta] of [...sources.entries()].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))) {
    const hasBackslashD = source.includes("\\d");
    let ast;
    let parseError = null;
    try {
      ast = parseExpression(source);
    } catch (error) {
      parseError = String(error.message ?? error);
    }
    if (parseError) {
      entries.push({ source, parseError, cases: [] });
      continue;
    }

    const { names, usesCurrent } = collectReferences(ast);
    const refs = [...names].sort();
    const refCandidates = Object.fromEntries(
      refs.map((ref) => [ref, candidatesForField(questionsByName.get(ref), hasBackslashD)])
    );
    // Prefer a real owning question's shape for `.`; fall back to a generic
    // pool when the expression using `.` is only ever a relevant/calculation
    // (no owning constraint recorded).
    const currentCandidates = usesCurrent
      ? candidatesForField(meta.constraintOwners[0] ?? null, hasBackslashD)
      : [];

    const scenarios = buildScenarios({ refs, usesCurrent, refCandidates, currentCandidates });
    const cases = scenarios.map((scenario) => {
      let result;
      let error = null;
      let resultIsNaN = false;
      try {
        result = evaluateExpression(ast, stripUndefined(scenario.data), {
          currentValue: scenario.currentValue,
          now
        });
        // JSON has no NaN: JSON.stringify(NaN) silently becomes `null`,
        // which would be indistinguishable from a genuine `undefined`
        // result (e.g. an unmatched `if()` branch). Arithmetic on a
        // missing/blank numeric answer (asNumber("") is NaN, not 0) makes
        // this a real case here, not a hypothetical one -- flag it
        // explicitly instead of losing it to JSON's null.
        resultIsNaN = typeof result === "number" && Number.isNaN(result);
        if (result === undefined) result = null;
      } catch (caught) {
        error = String(caught.message ?? caught);
      }
      return {
        scenario: scenario.name,
        data: stripUndefined(scenario.data),
        currentValue: scenario.currentValue ?? null,
        result: error || resultIsNaN ? null : result,
        resultIsNaN,
        error
      };
    });
    entries.push({ source, parseError: null, cases });
  }

  const doc = {
    schemaVersion: 1,
    source: {
      generatedBy: "tooling/who-va-2022/build-expression-corpus.mjs",
      package: vendorPackage.name,
      vendoredVersion: vendorPackage.version,
      engine: "vendor/who-va-2022/src/engine/expression.ts"
    },
    now: NOW_ISO,
    timezone: TIMEZONE,
    entries
  };

  writeFileSync(outPath, stableStringify(doc) + "\n");
  const caseCount = entries.reduce((total, entry) => total + entry.cases.length, 0);
  console.log(
    `wrote ${path.relative(repo, outPath)}: ${entries.length} unique expressions, ${caseCount} cases`
  );
}

const isMainModule = process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url;
if (isMainModule) await main();
