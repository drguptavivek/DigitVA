/**
 * Runtime instrument assembled from the generated WHO contract plus the custom
 * medical-certificate attachment question required by this implementation.
 */
import generatedInstrument from "./generated/who-va-2022.instrument.json";

import { ALL_DIGITVA_EXTENSIONS, createConsentModeQuestion, createDigitVaExtension } from "./digitva-extension.js";

import type { InstrumentDefinition, InstrumentQuestion } from "./types.js";

const generated = generatedInstrument as InstrumentDefinition;

/**
 * Compose the WHO VA 2022 instrument plus DigitVA's own additions, gating
 * each layer's questions on the extension names a project has enabled (see
 * docs/policy/va-form-project-configuration.md). `digitva_core` content —
 * the medical-certificate upload and the consent-mode question — is always
 * included: it does not depend on `enabledExtensions`.
 */
export function createWhoVa2022Instrument(enabledExtensions: ReadonlySet<string> | ReadonlyArray<string>): InstrumentDefinition {
  const enabled = enabledExtensions instanceof Set ? enabledExtensions : new Set(enabledExtensions);

  const medicalCertificateAnchorIndex = generated.questions.findIndex((question) => question.name === "Id10473");
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

  // Every DigitVA-added question from here on is numbered out of this same
  // high range, past every WHO question's and section's own order, so it can
  // never collide with one of them. `anchor.order + 1` (as used just above
  // for the medical-certificate upload) only works where the generated
  // instrument happens to leave a gap after the anchor; Id10013 has none
  // (Id10011 already sits at Id10013.order + 1), so the consent-mode question
  // and everything createDigitVaExtension adds is numbered from here instead.
  // Array position, not `.order`, is what the UI and this file's own splicing
  // use to place a question, so this renumbering does not move anything.
  const maxOrder = Math.max(...withCertificate.map((question) => question.order), ...generated.sections.map((s) => s.order));

  // digitva_core: the consent-mode question follows the consent question
  // itself (Id10013) and is relevant only once consent was given.
  const consentAnchorIndex = withCertificate.findIndex((question) => question.name === "Id10013");
  if (consentAnchorIndex < 0) {
    throw new Error("Cannot add the DigitVA consent-mode question because Id10013 is missing");
  }
  const consentModeOrder = maxOrder + 1;
  const consentAnchor = withCertificate[consentAnchorIndex]!;
  const consentModeQuestion = createConsentModeQuestion(consentModeOrder, [...consentAnchor.sectionPath]);
  const withConsentMode: InstrumentQuestion[] = [
    ...withCertificate.slice(0, consentAnchorIndex + 1),
    consentModeQuestion,
    ...withCertificate.slice(consentAnchorIndex + 1)
  ];

  // DigitVA extension (vendored copy, see src/digitva-extension.ts): the
  // narration language and narrative image follow the narrative text (Id10476);
  // the document images form a new section after the medical certificate.
  const narrativeAnchorIndex = withConsentMode.findIndex((question) => question.name === "Id10476");
  if (narrativeAnchorIndex < 0) {
    throw new Error("Cannot add the DigitVA narration fields because Id10476 is missing");
  }
  const narrativeAnchor = withConsentMode[narrativeAnchorIndex]!;
  const lastSection = generated.sections[generated.sections.length - 1]!;
  // ABHA identifiers follow the deceased's surname (Id10018).
  const deceasedAnchorIndex = withConsentMode.findIndex((question) => question.name === "Id10018");
  if (deceasedAnchorIndex < 0) {
    throw new Error("Cannot add the DigitVA ABHA fields because Id10018 is missing");
  }
  const deceasedAnchor = withConsentMode[deceasedAnchorIndex]!;
  // Numbered starting after consent_mode's own order (consentModeOrder), not
  // maxOrder itself, so createDigitVaExtension's first question does not
  // reuse consent_mode's number.
  const digitva = createDigitVaExtension(
    consentModeOrder,
    narrativeAnchor.sectionPath,
    lastSection.parent ?? lastSection.name,
    deceasedAnchor.sectionPath,
    enabled
  );

  const withDeceased: InstrumentQuestion[] = [
    ...withConsentMode.slice(0, deceasedAnchorIndex + 1),
    ...digitva.deceasedQuestions,
    ...withConsentMode.slice(deceasedAnchorIndex + 1)
  ];
  const narrativeIndex = withDeceased.findIndex((question) => question.name === "Id10476");

  return {
    ...generated,
    sections: [...generated.sections, ...digitva.sections],
    questions: [
      ...withDeceased.slice(0, narrativeIndex + 1),
      ...digitva.narrativeQuestions,
      ...withDeceased.slice(narrativeIndex + 1),
      ...digitva.documentQuestions
    ]
  };
}

/**
 * Backward-compatible default: every DigitVA layer on. Existing importers
 * (the web component, the instrument loader, the whole vendor test suite)
 * depend on this all-on shape and keep working unchanged.
 */
export const whoVa2022Instrument: InstrumentDefinition = createWhoVa2022Instrument(ALL_DIGITVA_EXTENSIONS);
