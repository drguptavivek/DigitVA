/** Platform-neutral APIs that do not import the built-in WHO instrument JSON. */
export { evaluateExpression, parseExpression } from "./engine/expression.js";
export {
  applyCalculations,
  getQuestion,
  isQuestionRelevant,
  validateAnswer,
  validateSubmission
} from "./engine/validation.js";
export { createWhoVaSession } from "./engine/session.js";
export { WHO_VA_FORM_VERSION } from "./version.js";
export { compileInstrumentDefinition } from "./engine/instrument-model.js";
export type { CompiledInstrumentDefinition, InstrumentRuntimeIndex } from "./engine/instrument-model.js";
export {
  ENGLISH_UI_MESSAGES,
  ENGLISH_UI_MESSAGE_TEMPLATES,
  createWhoVaLanguageLoader,
  localeCandidates,
  localeFromLanguageName,
  localizeText,
  resolveUiMessages,
  withInstrumentTranslation,
  withInstrumentTranslations
} from "./i18n.js";
export type {
  InstrumentTranslation,
  InstrumentTranslations,
  LoadedWhoVaLanguage,
  QuestionTranslation,
  WhoVaLanguageFile,
  WhoVaLanguageImport,
  WhoVaLanguageImports,
  WhoVaLanguageLoaderOptions,
  WhoVaUiMessages,
  WhoVaUiMessageTemplates,
  WhoVaUiTranslations
} from "./i18n.js";
export {
  WHO_VA_DRAFT_KEY_PREFIX,
  WHO_VA_DRAFT_SCHEMA_VERSION,
  createDraftId,
  createLocalStorageDraftStore,
  decodeWhoVaDraft
} from "./draft.js";
export { createWhoVaInitialDataFromPrefill } from "./prefill.js";
export type {
  WhoVaDeceasedPrefill,
  WhoVaHostPrefill,
  WhoVaInterviewerPrefill,
  WhoVaCitizenship,
  WhoVaLocationPrefill,
  WhoVaKnownLanguage,
  WhoVaKnownSex,
  WhoVaMortalityLevel,
  WhoVaPresetPrefill
} from "./prefill.js";
export type { WhoVaDraftController, WhoVaFormProps, WhoVaPlatformServices } from "./ui/create-who-va-form.js";
export {
  AttachmentProcessingError,
  WHO_VA_ATTACHMENT_POLICY,
  inspectRasterImage,
  isProcessedImageAttachment,
  isRetainedPdfAttachment,
  processImageAttachment,
  processInspectedImageAttachment
} from "./attachments.js";
export type * from "./types.js";
export type * from "./attachments.js";
