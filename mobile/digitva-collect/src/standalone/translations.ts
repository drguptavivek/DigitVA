/** Questionnaire translations shipped inside the standalone APK. */
import bundle from "../../assets/standalone-questionnaire-translations.json";

import { getMeta, setMeta, type Db } from "../drafts";
import type { Translations } from "../translations";

const INSTRUMENT = "WHO_2022_VA";

type LocalePack = {
  label: string;
  version: number;
  lifecycle_state: "in_review" | "approved";
  active: boolean;
  source_document: string;
  complete: boolean;
  translations: Translations;
};

const packs = bundle.locales as Record<string, LocalePack>;

export const STANDALONE_QUESTIONNAIRE_LOCALES = [
  { code: "en", label: "English" },
  ...Object.entries(packs).map(([code, pack]) => ({ code, label: pack.label })),
];

export function standaloneTranslationVersion(locale: string): number | undefined {
  return packs[locale]?.version;
}

/**
 * Use the package version pinned to this draft, restoring prior versions from
 * its local cache. This path reads SQLite and the APK only; it has no network
 * fallback in standalone mode.
 */
export async function standaloneTranslationsForDraft(
  db: Db,
  projectId: string,
  code: string,
  locale: string,
  draftVersion: number | undefined,
): Promise<{ translations: Translations | null; partial: boolean }> {
  const pack = code === INSTRUMENT ? packs[locale] : undefined;
  if (!pack) return { translations: null, partial: locale !== "en" };

  const version = draftVersion ?? pack.version;
  const key = `translations:${code}:${locale}:${version}`;
  if (version !== pack.version) {
    return {
      translations: (await getMeta<Translations>(db, key, projectId)) ?? null,
      partial: !pack.complete,
    };
  }
  await setMeta(db, key, pack.translations, projectId);
  return { translations: pack.translations, partial: !pack.complete };
}
