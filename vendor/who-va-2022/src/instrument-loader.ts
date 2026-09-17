import type { LoadedWhoVaLanguage } from "./i18n.js";
import type { InstrumentDefinition } from "./types.js";

let instrumentPromise: Promise<InstrumentDefinition> | undefined;

export const WHO_VA_2022_LANGUAGES = [{ locale: "en", label: "English" }] as const;

/** Loads the built-in offline instrument once, when an interview first needs it. */
export function loadWhoVa2022Instrument(): Promise<InstrumentDefinition> {
  instrumentPromise ??= import("./instrument.js").then(({ whoVa2022Instrument }) => whoVa2022Instrument);
  return instrumentPromise;
}

/** Returns the unmodified English source instrument for the built-in language selector. */
export async function loadWhoVa2022Language(_locale: string): Promise<LoadedWhoVaLanguage> {
  const instrument = await loadWhoVa2022Instrument();
  return { locale: "en", instrument, uiTranslations: {} };
}
