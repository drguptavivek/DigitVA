// Browser entry: registers <who-va-2022-form> and re-exports the headless
// helpers DigitVA's intake page uses (prefill, drafts, attachments).
export * from "@digitva/who-va-2022/web-component.tsx";
export { createWhoVaInitialDataFromPrefill } from "@digitva/who-va-2022/prefill.ts";
export { createDraftId, decodeWhoVaDraft } from "@digitva/who-va-2022/draft.ts";
export { DIGITVA_NARRATION_LANGUAGES, DIGITVA_MEDICAL_IMAGE_SLOTS, DIGITVA_DEATH_IMAGE_SLOTS } from "@digitva/who-va-2022/digitva-extension.ts";
import { defineWhoVaElement } from "@digitva/who-va-2022/web-component.tsx";
defineWhoVaElement();
