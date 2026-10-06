// Emit resource/xlsform_extensions/<extension>.json: the XLSForm rows each
// DigitVA extension adds to the WHO VA 2022 ODK form, read from the web
// form's own definition (vendor/who-va-2022/src/digitva-extension.ts), so
// web and ODK collect the same field names, types, relevance and constraints
// (bead digitva-aek). The server (app/services/xlsform_service.py) splices
// these blocks into the WHO reference workbook.
//
//   cd tooling/who-va-2022 && npm run build:odk-extension-rows
//
// Same block schema as the DORIS rows (build-odk-doris-rows.mjs ->
// vendor/who-va-2022/src/generated/odk-doris-support-rows.json), which the
// server reads as the `doris_support_whova_2022` spec: a block names where it
// goes (`odk.after` / `odk.before` a WHO row, or `odk.afterGroupEnd` a WHO
// group), and carries `survey` rows (XLSForm column names; `label`, `hint`,
// `constraint_message` and `guidance_hint` are English) and `choices`.
//
// Not generated here, because they depend on the project, not on the
// definition: `geography` (one cascading org_<level>_code select per level),
// `intake_screen` (the project's welcome note) and the choice lists `site`,
// `language`, `narr_language` (see xlsform_service.py).
//
// Deliberately not carried to ODK: the visit note (identity-less refusals
// only; it depends on the death register's prefill) and `interview_outcome`
// (set by the server on submit), both web-only digitva_core questions.
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { mkdirSync, mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { build } from "esbuild";

import { stableStringify } from "./build-layer-reference.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "..", "..");
const vendorSrc = path.join(repo, "vendor", "who-va-2022", "src");
const outDir = path.join(repo, "resource", "xlsform_extensions");

async function loadExtensionModule() {
  const tmpDir = mkdtempSync(path.join(tmpdir(), "whova-odk-extension-rows-"));
  const entryPath = path.join(tmpDir, "entry.mjs");
  const outfile = path.join(tmpDir, "bundle.mjs");
  writeFileSync(
    entryPath,
    `export { createDigitVaExtension, createConsentModeQuestion } from ${JSON.stringify(
      path.join(vendorSrc, "digitva-extension.js"),
    )};\n`,
  );
  try {
    await build({
      entryPoints: [entryPath],
      bundle: true,
      format: "esm",
      platform: "node",
      outfile,
      logLevel: "warning",
      nodePaths: [path.join(here, "node_modules")],
    });
    return await import(pathToFileURL(outfile).href);
  } finally {
    rmSync(tmpDir, { recursive: true, force: true });
  }
}

/** The XLSForm `type` of one extension question. */
export function xlsformType(question) {
  switch (question.sourceType) {
    case "digitva-extension":
      if (question.control !== "text") {
        throw new Error(`${question.name}: no XLSForm type for control ${question.control}`);
      }
      return "text";
    // The web's document upload (image or PDF); ODK's closest control.
    case "custom-attachment":
      return "file";
    default:
      return question.sourceType;
  }
}

/** One survey row. Empty cells are left out; the server treats absent as blank. */
export function surveyRow(question) {
  const row = {
    type: xlsformType(question),
    name: question.name,
    agegroup: question.ageGroup || "ALL",
    label: question.label?.en ?? "",
    hint: question.hint?.en ?? "",
    required: question.required ? "yes" : "",
    appearance: question.appearance ?? "",
    relevant: question.relevant?.source ?? "",
    constraint: question.constraint?.source ?? "",
    constraint_message: question.constraintMessage?.en ?? "",
    // ODK-only: caps the image size sent from the phone, as the deployed forms do.
    parameters: question.sourceType === "image" ? "max-pixels=1024" : "",
  };
  return Object.fromEntries(Object.entries(row).filter(([, v]) => v !== ""));
}

/** Choice rows of the lists these questions use, each list once. */
export function choiceRows(questions, skipLists = []) {
  const listed = new Set(skipLists);
  const rows = [];
  for (const question of questions) {
    if (!question.listName || listed.has(question.listName)) continue;
    listed.add(question.listName);
    for (const choice of question.choices ?? []) {
      rows.push({
        list_name: question.listName,
        name: choice.value,
        label: choice.label?.en ?? "",
      });
    }
  }
  return rows;
}

/**
 * A group, its questions (those whose section path ends in the group) and its
 * child groups, as survey rows. Leaf groups use `field-list` like the deployed
 * forms (ND01's socialautopsy and md_records).
 */
export function groupRows(sections, questions, name, extra = {}) {
  const section = sections.find((s) => s.name === name);
  const children = sections.filter((s) => s.parent === name);
  const own = questions.filter((q) => q.sectionPath.at(-1) === name);
  const rows = [
    {
      type: "begin group",
      name,
      agegroup: "ALL",
      label: section.label.en,
      ...(section.relevant ? { relevant: section.relevant.source } : {}),
      ...(children.length ? {} : { appearance: "field-list" }),
      ...extra,
    },
    ...own.map(surveyRow),
  ];
  for (const child of children) rows.push(...groupRows(sections, questions, child.name));
  rows.push({ type: "end group" });
  return rows;
}

const ANCHOR_PATH = ["digitva_anchor", "narrat"];

async function main() {
  const { createDigitVaExtension, createConsentModeQuestion } = await loadExtensionModule();
  const only = (extension) =>
    createDigitVaExtension(0, ANCHOR_PATH, "digitva_parent", ["digitva_anchor", "deceased"], [extension]);

  const specs = {};

  // digitva_core: the consent mode, plus the three rows ODK needs that the web
  // server injects (Site, unique_id) or accepts as an upload.
  const consentMode = createConsentModeQuestion(0, []);
  specs.digitva_core = [
    {
      id: "core_site",
      title: "Study site of the interviewer",
      odk: { before: "Id10010" },
      survey: [
        {
          type: "select_one site",
          name: "Site",
          agegroup: "ALL",
          label: "Study site of the VA interviewer",
          required: "yes",
        },
      ],
      choices: [],
      change: [],
    },
    {
      id: "core_unique_id",
      title: "Unique id of the deceased",
      odk: {
        before: "Id10017",
        note: "DigitVA's sync reads unique_id; the web server builds it from the site and the start time.",
      },
      survey: [
        {
          type: "calculate",
          name: "unique_id",
          agegroup: "ALL",
          label: "Unique ID of the deceased.",
          calculation: 'concat(${Site}, "_", format-date-time(${Id10011}, "%H%M%S%3"))',
        },
      ],
      choices: [],
      change: [],
    },
    {
      id: "core_consent_mode",
      title: "Mode of consent",
      odk: { after: "Id10013" },
      survey: [surveyRow(consentMode)],
      choices: choiceRows([consentMode]),
      change: [],
    },
    {
      id: "core_medical_certificate_upload",
      title: "Medical certificate upload",
      odk: { after: "Id10473" },
      survey: [
        {
          type: "file",
          name: "custom_medical_certificate_upload",
          agegroup: "ALL",
          label: "Upload medical certificate (image or PDF)",
          hint: "Choose a JPEG or PNG image, or a PDF document.",
          appearance: "image-or-pdf",
          relevant: "selected(${Id10463}, 'yes')",
        },
      ],
      choices: [],
      change: [],
    },
  ];

  const abha = only("abha");
  specs.abha = [
    {
      id: "abha",
      title: "ABHA identifiers",
      odk: { after: "Id10018" },
      survey: abha.deceasedQuestions.map(surveyRow),
      choices: [],
      change: [],
    },
  ];

  const narration = only("narration_language");
  specs.narration_language = [
    {
      id: "narration_language",
      title: "Narration language and narrative image",
      // ND01 puts these before the narrative text; the web puts them after.
      odk: { after: "noteon", note: "Choice list narr_language comes from the project's narration languages." },
      // The WHO `language` list is the interview language; narration gets its own.
      survey: narration.narrativeQuestions.map((q) => {
        const row = surveyRow(q);
        return row.type === "select_one language" ? { ...row, type: "select_one narr_language" } : row;
      }),
      choices: [],
      change: [],
    },
  ];

  const social = only("social_autopsy");
  specs.social_autopsy = [
    {
      id: "social_autopsy",
      title: "Social autopsy questionnaire",
      odk: { afterGroupEnd: "narrat" },
      survey: groupRows(social.sections, social.socialAutopsyQuestions, "socialautopsy"),
      choices: choiceRows(social.socialAutopsyQuestions),
      change: [],
    },
  ];

  const documents = (extension, prefix, groupName, label) => {
    const doc = only(extension);
    const questions = doc.documentQuestions.filter((q) => q.name.startsWith(prefix));
    return {
      id: extension,
      title: label,
      questions,
      survey: [
        { type: "begin group", name: groupName, agegroup: "ALL", label, appearance: "field-list" },
        ...questions.map(surveyRow),
        { type: "end group" },
      ],
      choices: choiceRows(questions),
    };
  };
  const death = documents("death_summary", "ds_", "death_summary", "Death Certificate (Images)");
  specs.death_summary = [
    { id: death.id, title: death.title, odk: { afterGroupEnd: "deathcert" }, survey: death.survey, choices: death.choices, change: [] },
  ];
  const medical = documents("medical_records", "md_", "md_records", "Medical Records");
  specs.medical_records = [
    { id: medical.id, title: medical.title, odk: { after: "comment" }, survey: medical.survey, choices: medical.choices, change: [] },
  ];

  mkdirSync(outDir, { recursive: true });
  for (const [extension, blocks] of Object.entries(specs)) {
    const doc = {
      schemaVersion: 1,
      source: {
        generatedBy: "tooling/who-va-2022/build-odk-extension-rows.mjs",
        definition: "vendor/who-va-2022/src/digitva-extension.ts",
        extension,
      },
      blocks,
    };
    writeFileSync(path.join(outDir, `${extension}.json`), `${stableStringify(doc)}\n`, "utf8");
  }
  console.log(`wrote ${Object.keys(specs).length} specs to ${path.relative(repo, outDir)}`);
}

const isMainModule =
  process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url;
if (isMainModule) {
  main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}
