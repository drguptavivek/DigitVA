// tooling/who-va-2022/build-odk-doris-rows.mjs writes the committed
// vendor/who-va-2022/src/generated/odk-doris-support-rows.json from the
// doris_support_whova_2022 extension's own blocks (digitva-hln). This pins
// reproducibility and the question -> XLSForm row conversion.
//
// Run: npm run test:web (from tooling/who-va-2022).

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  buildBlocks,
  changedCells,
  surveyRow,
  xlsformType,
} from "../build-odk-doris-rows.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const toolingDir = path.resolve(here, "..");
const repo = path.resolve(toolingDir, "..", "..");
const generatorPath = path.join(toolingDir, "build-odk-doris-rows.mjs");
const artifactPath = path.join(
  repo,
  "vendor/who-va-2022/src/generated/odk-doris-support-rows.json",
);

test("regenerating on an unmodified tree reproduces the committed artifact byte for byte", () => {
  const before = readFileSync(artifactPath, "utf8");
  execFileSync(process.execPath, [generatorPath], { cwd: toolingDir });
  assert.equal(readFileSync(artifactPath, "utf8"), before);
});

test("a question becomes one XLSForm row, expressions passed through as written", () => {
  const row = surveyRow({
    name: "doris_injury_date",
    sourceType: "date",
    control: "date",
    label: { en: "On what date?" },
    ageGroup: "ALL",
    hint: {},
    required: false,
    appearance: "no-calendar",
    relevant: { source: "selected(${doris_injury_date_known}, 'full')" },
    constraint: { source: ". <= today()" },
    constraintMessage: { en: "Cannot be after the death" },
  });
  assert.deepEqual(row, {
    type: "date",
    name: "doris_injury_date",
    agegroup: "ALL",
    label: "On what date?",
    hint: "",
    required: "",
    appearance: "no-calendar",
    relevant: "selected(${doris_injury_date_known}, 'full')",
    constraint: ". <= today()",
    constraint_message: "Cannot be after the death",
  });
});

test("the extension's own text questions are XLSForm text; anything else unmapped fails", () => {
  assert.equal(
    xlsformType({
      name: "t",
      sourceType: "digitva-extension",
      control: "text",
    }),
    "text",
  );
  assert.equal(
    xlsformType({
      name: "s",
      sourceType: "select_one legal_war",
      control: "singleChoice",
    }),
    "select_one legal_war",
  );
  assert.throws(
    () =>
      xlsformType({
        name: "x",
        sourceType: "digitva-extension",
        control: "image",
      }),
    /no XLSForm type/,
  );
});

test("a question without an age group is refused", () => {
  assert.throws(
    () =>
      surveyRow({
        name: "q",
        sourceType: "integer",
        control: "integer",
        label: { en: "q" },
      }),
    /no ageGroup/,
  );
});

test("a WHO change becomes the XLSForm cells it replaces", () => {
  assert.deepEqual(changedCells({ required: true }), { required: "yes" });
  assert.deepEqual(
    changedCells({ constraint: ". >= 100", constraintMessage: "grammes" }),
    {
      constraint: ". >= 100",
      constraint_message: "grammes",
    },
  );
});

test("a block with questions but no ND01 position is refused; a shared list is emitted once", () => {
  const question = (name) => ({
    name,
    sourceType: "select_one YES_NO_DK_REF",
    control: "singleChoice",
    label: { en: name },
    listName: "YES_NO_DK_REF",
    choices: [{ value: "yes", label: { en: "Yes" } }],
    ageGroup: "ALL",
  });
  assert.throws(
    () =>
      buildBlocks([
        {
          id: "A0",
          title: "t",
          status: "proposed",
          questions: [question("a")],
          whoChanges: {},
          odk: {},
        },
      ]),
    /no ND01 position/,
  );
  const [first, second] = buildBlocks([
    {
      id: "A1",
      title: "t",
      status: "proposed",
      questions: [question("a")],
      whoChanges: {},
      odk: { after: "x" },
    },
    {
      id: "A2",
      title: "t",
      status: "proposed",
      questions: [question("b")],
      whoChanges: {},
      odk: { after: "y" },
    },
  ]);
  assert.equal(first.choices.length, 1);
  assert.equal(second.choices.length, 0);
});

test("the committed rows carry all of Annex A from the extension", () => {
  const doc = JSON.parse(readFileSync(artifactPath, "utf8"));
  assert.equal(doc.source.extension, "doris_support_whova_2022");
  assert.deepEqual(
    doc.blocks.map((block) => block.id),
    ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10"],
  );
  const added = doc.blocks.flatMap((block) => block.survey);
  assert.equal(added.length, 19);
  assert.deepEqual(
    Object.fromEntries(
      added
        .filter((row) => row.agegroup !== "ALL")
        .map((row) => [row.name, row.agegroup]),
    ),
    {
      Id10366_confirm: "N_C",
      doris_hours_survived: "N",
      doris_pregnancy_weeks: "N_C",
      doris_mother_age: "N_C",
    },
  );
  const a7 = doc.blocks.find((block) => block.id === "A7");
  assert.equal(a7.odk.afterGroupEnd, "health_service_utilization");
  assert.deepEqual(
    a7.survey.map((row) => row.type),
    [
      "select_one YES_NO_DK_REF",
      "integer",
      "select_one time_unit",
      "text",
      "text",
    ],
  );
});
