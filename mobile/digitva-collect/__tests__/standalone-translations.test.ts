import bundle from "../assets/standalone-questionnaire-translations.json";

import { applyTranslations } from "../src/translations";
import {
  standaloneTranslationsForDraft,
  STANDALONE_QUESTIONNAIRE_LOCALES,
  standaloneTranslationVersion,
} from "../src/standalone/translations";
import type { Db } from "../src/drafts";

function memoryDb(): Db {
  const values = new Map<string, string>();
  return {
    execAsync: async () => undefined,
    runAsync: async (_sql, params) => {
      values.set(String(params[0]), String(params[1]));
      return { changes: 1, lastInsertRowId: 1 } as never;
    },
    getAllAsync: async () => [],
    getFirstAsync: async <T,>(_sql: string, params: Array<string | number | null>) => {
      const value = values.get(String(params[0]));
      return (value ? { value } : null) as T | null;
    },
    closeAsync: async () => undefined,
  };
}

describe("standalone questionnaire translations", () => {
  it("offers English and the bundled Hindi questionnaire with its source review state", () => {
    expect(STANDALONE_QUESTIONNAIRE_LOCALES).toEqual([
      { code: "en", label: "English" },
      { code: "hi", label: "हिन्दी" },
    ]);
    expect(standaloneTranslationVersion("hi")).toBe(6);
    expect(bundle.locales.hi.lifecycle_state).toBe("in_review");
    expect(bundle.locales.hi.complete).toBe(false);
  });

  it("applies real Hindi question text, pins it in local metadata, and never fetches", async () => {
    const db = memoryDb();
    const projectId = "standalone-device";
    const fetchSpy = jest.spyOn(global, "fetch");
    const loaded = await standaloneTranslationsForDraft(db, projectId, "WHO_2022_VA", "hi", undefined);
    const entry = Object.entries(loaded.translations?.questions ?? {}).find(([, value]) => value.label);
    expect(entry).toBeDefined();
    expect(loaded.partial).toBe(true);

    const [questionName, translation] = entry!;
    const instrument = {
      id: "WHO_2022_VA",
      version: "1",
      sections: [],
      questions: [{ name: questionName, label: { en: "English question" } }],
    } as unknown as Parameters<typeof applyTranslations>[0];
    const translated = applyTranslations(instrument, loaded.translations, "hi");
    expect(translated.questions[0]?.label).toMatchObject({ hi: translation.label });

    const pinned = await standaloneTranslationsForDraft(db, projectId, "WHO_2022_VA", "hi", 6);
    expect(pinned.translations).toEqual(loaded.translations);
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("restores an old pinned pack from local metadata and falls back to English when absent", async () => {
    const db = memoryDb();
    const projectId = "standalone-device";
    await db.runAsync(
      "INSERT INTO meta (key, value) VALUES (?, ?)",
      ["project:standalone-device:translations:WHO_2022_VA:hi:5", JSON.stringify({ questions: { Q1: { label: "saved Hindi" } } })],
    );

    const restored = await standaloneTranslationsForDraft(db, projectId, "WHO_2022_VA", "hi", 5);
    expect(restored.translations).toEqual({ questions: { Q1: { label: "saved Hindi" } } });
    expect(restored.partial).toBe(true);

    const unavailable = await standaloneTranslationsForDraft(db, projectId, "WHO_2022_VA", "hi", 4);
    expect(unavailable.translations).toBeNull();
    expect(unavailable.partial).toBe(true);
  });
});
