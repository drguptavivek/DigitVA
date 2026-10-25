/**
 * Web entry point for hosts that deliberately preload the built-in instrument.
 *
 * Unlike the legacy web entry, this module has no dynamic instrument import.
 * Hosts can therefore load one canonical namespace for both the core and web
 * APIs while keeping the instrument placement explicit in their bundle.
 */
import type { LoadedWhoVaLanguage } from "./i18n.js";
import { whoVa2022Instrument } from "./instrument.js";
import { createWhoVaWebForm } from "./web-platform.js";

export * from "./web-platform.js";
export * from "./instrument.js";
export { WHO_VA_2022_LANGUAGES } from "./instrument-language.js";

const instrumentPromise = Promise.resolve(whoVa2022Instrument);

/** Returns the already-loaded built-in instrument without a second import. */
export function loadWhoVa2022Instrument() {
  return instrumentPromise;
}

/** Returns the unmodified English source instrument for the built-in selector. */
export async function loadWhoVa2022Language(_locale: string): Promise<LoadedWhoVaLanguage> {
  return { locale: "en", instrument: whoVa2022Instrument, uiTranslations: {} };
}

export const WhoVaForm = createWhoVaWebForm(loadWhoVa2022Instrument);
