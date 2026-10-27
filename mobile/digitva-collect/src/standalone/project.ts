/**
 * The synthetic project a standalone (Path C) account interviews under. Nothing here comes from a server: the
 * project id is the local account id (never a numeric server id, never null so the store keeps its rows), the form
 * is the instrument bundled in the app, and the extension set is the standalone default.
 */
import { createWhoVa2022Instrument } from "@drguptavivek/who-2022-va";

import type { ResolvedInstrument } from "../formDefinitionRuntime";
import type { ProjectSettings } from "../sync";
import { STANDALONE_DEFAULT_EXTENSIONS } from "./config";

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
      available_locales: [{ code: "en", label: "English" }],
      default_locale: "en",
    },
    prefill_policy: {} as ProjectSettings["prefill_policy"],
  };
}

/** The bundled instrument with the given extensions: the same definition the offline coding path ships. */
export function standaloneDefinition(extensions: readonly string[]): ResolvedInstrument {
  return { instrument: createWhoVa2022Instrument([...extensions]), provenance: "bundled-original", pin: null };
}
