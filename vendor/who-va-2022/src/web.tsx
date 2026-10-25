/**
 * React web package entry point with the built-in instrument's lazy loader.
 *
 * The browser bindings live in `web-platform.tsx` so consumers that need an
 * eager/preloaded instrument can use the same UI without importing this
 * legacy loader boundary.
 */
import { createWhoVaWebForm } from "./web-platform.js";
import {
  WHO_VA_2022_LANGUAGES,
  loadWhoVa2022Instrument,
  loadWhoVa2022Language
} from "./instrument-loader.js";

export * from "./core.js";
export { WHO_VA_2022_LANGUAGES, loadWhoVa2022Instrument, loadWhoVa2022Language };
export type { WhoVaFormProps, WhoVaPlatformServices } from "./ui/create-who-va-form.js";

export {
  WebAudioPlayer,
  loadWhoVaWebAttachmentBlob,
  cleanupWhoVaWebAttachments,
  InsecureWhoVaBrowserDefaults,
  createInsecureWhoVaBrowserDefaults,
  WhoVaQuestionControls
} from "./web-platform.js";
export {
  cleanupOrphanedWebAttachments,
  createBrowserImageTranscoder,
  createIndexedDbWebAttachmentStore,
  processWebImageAttachment,
  storeWebPdfAttachment,
  loadWebAttachmentBlob,
  resolveWebAttachmentUri
} from "./web-attachments.js";
export { startWebAudioRecording } from "./web-audio.js";
export type * from "./web-audio.js";
export type { WhoVaQuestionControlProps } from "./ui/question-controls.js";

export const WhoVaForm = createWhoVaWebForm(loadWhoVa2022Instrument);
