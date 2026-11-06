/**
 * The synthetic project a standalone (Path C) account interviews under. Nothing here comes from a server: the
 * project id is the local account id (never a numeric server id, never null so the store keeps its rows), the form
 * is the instrument bundled in the app, and the extension set is the standalone default.
 */
import { createWhoVa2022Instrument } from "@drguptavivek/who-2022-va";

import { computeUtf8Sha256HexSync } from "../consent";
import { readDefinitionPin, type DefinitionPin, type ResolvedInstrument } from "../formDefinitionRuntime";
import type { ProjectSettings } from "../sync";
import { STANDALONE_DEFAULT_EXTENSIONS } from "./config";
import { STANDALONE_QUESTIONNAIRE_LOCALES, standaloneTranslationVersion } from "./translations";

export const STANDALONE_ID_PREFIX = "standalone-";
export const STANDALONE_SITE_ID = "standalone";

export const standaloneUserId = (deviceUuid: string) => `${STANDALONE_ID_PREFIX}${deviceUuid}`;
/** A standalone account's project id is its own id: records are marked standalone by it. */
export const standaloneProjectId = (userId: string) => userId;
export const isStandaloneId = (id: string | null | undefined) => typeof id === "string" && id.startsWith(STANDALONE_ID_PREFIX);

export function standaloneProject(projectId: string): ProjectSettings {
  return {
    project_id: projectId,
    project_name: "Standalone",
    web_intake_mode: "direct",
    sites: [{ project_id: projectId, site_id: STANDALONE_SITE_ID }],
    form_options: {
      enabled_extensions: [...STANDALONE_DEFAULT_EXTENSIONS],
      form_types: [{ instrument_code: "WHO_2022_VA", is_default: true }],
      available_locales: STANDALONE_QUESTIONNAIRE_LOCALES,
      default_locale: "en",
      translation_versions: { hi: standaloneTranslationVersion("hi") ?? 0 },
    },
    prefill_policy: {} as ProjectSettings["prefill_policy"],
  };
}

// One hash per extension set per app start: the bundled definition cannot change while the app runs.
const bundledPins = new Map<string, DefinitionPin>();

/**
 * The bundled instrument with the given extensions, pinned (digitva-5bzf.12) like an enrolled draft: the pin is the
 * instrument version, the SHA-256 of the instrument's JSON as compiled for those extensions, and the sorted extensions.
 */
export function standaloneDefinition(extensions: readonly string[]): ResolvedInstrument {
  const sorted = [...new Set(extensions)].sort();
  const instrument = createWhoVa2022Instrument(sorted);
  const key = sorted.join(",");
  let pin = bundledPins.get(key);
  if (!pin) {
    pin = Object.freeze({
      instrumentVersion: instrument.version,
      definitionSha256: computeUtf8Sha256HexSync(JSON.stringify(instrument)),
      definitionExtensions: Object.freeze(sorted),
    });
    bundledPins.set(key, pin);
  }
  return { instrument, provenance: "bundled-original", pin };
}

/**
 * True when a stored standalone draft was made on a different questionnaire than the bundled one. Only the
 * recorded instrument version is compared; a draft saved before pins existed has only its version string.
 * An unreadable pin counts as a mismatch. Never alters the draft.
 */
export function standaloneDraftMismatch(envelope: unknown, bundled: ResolvedInstrument): boolean {
  const record = (envelope ?? {}) as Record<string, unknown>;
  try {
    // Version only (owner decision 2026-11-06): the hash and extensions stay recorded but are not compared.
    const stored = readDefinitionPin(record);
    if (stored) return stored.instrumentVersion !== bundled.instrument.version;
  } catch {
    return true;
  }
  return typeof record.instrumentVersion === "string" && record.instrumentVersion !== bundled.instrument.version;
}
