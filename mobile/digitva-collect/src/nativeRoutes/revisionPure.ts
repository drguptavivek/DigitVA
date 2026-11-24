/**
 * The pure helpers of the revision screen (revision.tsx), moved out unchanged: the reason choices, the saved
 * revision's form configuration against its project, and the envelope check that fills a submitted draft's
 * missing instrument fields. revision.tsx re-exports the helpers the supervisor revision screen imports.
 */
import { WHO_VA_FORM_VERSION, type InstrumentDefinition } from "@drguptavivek/who-2022-va";

import type { Prefill } from "../cases";
import type { DeviceTimedDraft } from "../drafts";
import { isLocaleCode, questionnaireDefault } from "../i18n";
import type { RevisionReason, RevisionRow } from "../revisions";
import type { ProjectSettings } from "../sync";

export const REASONS: Array<{ code: RevisionReason; label: string; message: string }> = [
  {
    code: "interviewer_correction",
    label: "revisionReasonInterviewerCorrection",
    message: "revisionReasonMessageInterviewerCorrection",
  },
  {
    code: "respondent_correction",
    label: "revisionReasonRespondentCorrection",
    message: "revisionReasonMessageRespondentCorrection",
  },
  {
    code: "more_information",
    label: "revisionReasonMoreInformation",
    message: "revisionReasonMessageMoreInformation",
  },
  {
    code: "finish_partial",
    label: "revisionReasonFinishPartial",
    message: "revisionReasonMessageFinishPartial",
  },
];

export interface RevisionConfig {
  projectId: string;
  locale: string;
  translationVersion?: number;
  enabledExtensions: string[];
  instrumentCode: string;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isPrefill(value: Record<string, unknown>): value is Record<string, unknown> & Prefill {
  return (
    (value.interviewer === undefined || isRecord(value.interviewer)) &&
    (value.deceased === undefined || isRecord(value.deceased)) &&
    (value.answers === undefined || isRecord(value.answers)) &&
    (value.lockedQuestionNames === undefined ||
      (Array.isArray(value.lockedQuestionNames) &&
        value.lockedQuestionNames.every((name) => typeof name === "string")))
  );
}

export function configForRevision(row: RevisionRow, project: ProjectSettings): RevisionConfig {
  if (row.config?.projectId && row.config.projectId !== project.project_id) {
    throw new Error("revision_project_mismatch");
  }
  const options = project.form_options;
  const instrumentCode =
    row.config?.instrumentCode ??
    options?.form_types?.find((formType) => formType.is_default)?.instrument_code ??
    "WHO_2022_VA";
  const enabledExtensions = [
    ...(row.config?.enabledExtensions ?? options?.enabled_extensions ?? []),
  ];
  const savedLocale = row.envelope.locale || row.config?.locale;
  const locale = savedLocale ??
    questionnaireDefault(options?.available_locales, options?.default_locale);
  if (!isLocaleCode(locale)) {
    throw new Error("revision_locale_unavailable");
  }
  const translationVersion =
    row.envelope.translation_version ??
    row.config?.translationVersion ??
    options?.translation_versions?.[locale];
  return {
    projectId: project.project_id,
    locale,
    ...(translationVersion === undefined ? {} : { translationVersion }),
    enabledExtensions,
    instrumentCode,
  };
}

export function normalizeEnvelope(
  envelope: DeviceTimedDraft,
  instrument: InstrumentDefinition,
): DeviceTimedDraft {
  if (
    (envelope.formVersion && envelope.formVersion !== WHO_VA_FORM_VERSION) ||
    (envelope.instrumentId && envelope.instrumentId !== instrument.id) ||
    (envelope.instrumentVersion && envelope.instrumentVersion !== instrument.version)
  ) {
    throw new Error("revision_instrument_mismatch");
  }
  return {
    ...envelope,
    formVersion: envelope.formVersion || WHO_VA_FORM_VERSION,
    instrumentId: envelope.instrumentId || instrument.id,
    instrumentVersion: envelope.instrumentVersion || instrument.version,
    // A submitted draft usually has no current section; the form refuses an
    // empty one and would then open blank, so it starts at the first section.
    currentSection: envelope.currentSection || instrument.sections[0]?.name || "_root",
  };
}

