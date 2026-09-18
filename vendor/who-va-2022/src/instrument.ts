/**
 * Runtime instrument assembled from the generated WHO contract plus the custom
 * medical-certificate attachment question required by this implementation.
 */
import generatedInstrument from "./generated/who-va-2022.instrument.json";

import { createDigitVaExtension } from "./digitva-extension.js";

import type { InstrumentDefinition, InstrumentQuestion } from "./types.js";

const generated = generatedInstrument as InstrumentDefinition;
const medicalCertificateAnchorIndex = generated.questions.findIndex(
  (question) => question.name === "Id10473"
);

if (medicalCertificateAnchorIndex < 0) {
  throw new Error("Cannot add the medical-certificate upload because Id10473 is missing");
}

const medicalCertificateAnchor = generated.questions[medicalCertificateAnchorIndex]!;
const medicalCertificateUpload: InstrumentQuestion = {
  name: "custom_medical_certificate_upload",
  order: medicalCertificateAnchor.order + 1,
  sourceRow: 0,
  sourceType: "custom-attachment",
  dataType: "attachment",
  control: "file",
  label: { en: "Upload medical certificate (image or PDF)" },
  hint: { en: "Choose a JPEG or PNG image, or a PDF document." },
  guidance: {},
  required: false,
  readOnly: false,
  appearance: "image-or-pdf",
  constraintMessage: {},
  sectionPath: [...medicalCertificateAnchor.sectionPath],
  ...(medicalCertificateAnchor.ageGroup ? { ageGroup: medicalCertificateAnchor.ageGroup } : {}),
  ...(medicalCertificateAnchor.relevant ? { relevant: medicalCertificateAnchor.relevant } : {})
};

const withCertificate: InstrumentQuestion[] = [
  ...generated.questions.slice(0, medicalCertificateAnchorIndex + 1),
  medicalCertificateUpload,
  ...generated.questions.slice(medicalCertificateAnchorIndex + 1)
];

// DigitVA extension (vendored copy, see src/digitva-extension.ts): the
// narration language and narrative image follow the narrative text (Id10476);
// the document images form a new section after the medical certificate.
const narrativeAnchorIndex = withCertificate.findIndex((question) => question.name === "Id10476");
if (narrativeAnchorIndex < 0) {
  throw new Error("Cannot add the DigitVA narration fields because Id10476 is missing");
}
const narrativeAnchor = withCertificate[narrativeAnchorIndex]!;
const lastSection = generated.sections[generated.sections.length - 1]!;
const maxOrder = Math.max(...withCertificate.map((question) => question.order), ...generated.sections.map((s) => s.order));
// ABHA identifiers follow the deceased's surname (Id10018).
const deceasedAnchorIndex = withCertificate.findIndex((question) => question.name === "Id10018");
if (deceasedAnchorIndex < 0) {
  throw new Error("Cannot add the DigitVA ABHA fields because Id10018 is missing");
}
const deceasedAnchor = withCertificate[deceasedAnchorIndex]!;
const digitva = createDigitVaExtension(
  maxOrder,
  narrativeAnchor.sectionPath,
  lastSection.parent ?? lastSection.name,
  deceasedAnchor.sectionPath
);

const withDeceased: InstrumentQuestion[] = [
  ...withCertificate.slice(0, deceasedAnchorIndex + 1),
  ...digitva.deceasedQuestions,
  ...withCertificate.slice(deceasedAnchorIndex + 1)
];
const narrativeIndex = withDeceased.findIndex((question) => question.name === "Id10476");

export const whoVa2022Instrument: InstrumentDefinition = {
  ...generated,
  sections: [...generated.sections, ...digitva.sections],
  questions: [
    ...withDeceased.slice(0, narrativeIndex + 1),
    ...digitva.narrativeQuestions,
    ...withDeceased.slice(narrativeIndex + 1),
    ...digitva.documentQuestions
  ]
};
