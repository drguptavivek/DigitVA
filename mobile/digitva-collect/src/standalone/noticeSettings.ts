import * as SecureStore from "expo-secure-store";

import bundled from "../../assets/standalone-consent-notice.json";
import { computeUtf8Sha256HexSync } from "../consent";
import { fillPlaceholders, type StandaloneNoticeContext } from "../standaloneConsent";
import { standaloneConsentConfig } from "./consent";

export const MAX_STANDALONE_NOTICE_LENGTH = 20_000;
export const STANDALONE_NOTICE_LANGUAGES = ["en", "hi"] as const;
export type StandaloneNoticeLanguage = (typeof STANDALONE_NOTICE_LANGUAGES)[number];
export type StandaloneNoticeSettings = Record<StandaloneNoticeLanguage, string>;

const KEY = "digitva.standalone-consent-notices.v1";
const DEFAULTS = bundled.text as StandaloneNoticeSettings;

export function defaultStandaloneNoticeSettings(): StandaloneNoticeSettings {
  return { en: DEFAULTS.en, hi: DEFAULTS.hi };
}

export function validStandaloneNoticeText(text: string): boolean {
  return text.trim().length > 0 && text.length <= MAX_STANDALONE_NOTICE_LENGTH;
}

function parseSettings(raw: string | null): StandaloneNoticeSettings {
  const defaults = defaultStandaloneNoticeSettings();
  if (!raw) return defaults;
  try {
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== "object" || (value as { schema?: unknown }).schema !== 1) return defaults;
    const notices = (value as { notices?: unknown }).notices;
    if (!notices || typeof notices !== "object") return defaults;
    const saved = notices as Record<string, unknown>;
    return {
      en: typeof saved.en === "string" && validStandaloneNoticeText(saved.en) ? saved.en : defaults.en,
      hi: typeof saved.hi === "string" && validStandaloneNoticeText(saved.hi) ? saved.hi : defaults.hi,
    };
  } catch {
    return defaults;
  }
}

export async function loadStandaloneNoticeSettings(): Promise<StandaloneNoticeSettings> {
  return parseSettings(await SecureStore.getItemAsync(KEY));
}

export async function saveStandaloneNoticeSettings(notices: StandaloneNoticeSettings): Promise<void> {
  if (!STANDALONE_NOTICE_LANGUAGES.every((language) => validStandaloneNoticeText(notices[language]))) {
    throw new Error("standalone_notice_invalid");
  }
  await SecureStore.setItemAsync(KEY, JSON.stringify({ schema: 1, notices }));
}

/** Uses current app-local wording while keeping seed purposes and all other standalone config defaults. */
export async function standaloneConsentConfigWithSavedNotice(
  projectId: string,
  language: string,
  context: StandaloneNoticeContext = {},
) {
  const config = standaloneConsentConfig(projectId, language, context);
  if (!config) return null;
  const notice = config.notice_versions[0];
  const settings = await loadStandaloneNoticeSettings();
  const text = fillPlaceholders(settings[notice.language as StandaloneNoticeLanguage], notice.language, context);
  const sha256 = computeUtf8Sha256HexSync(text);
  return {
    ...config,
    notice_versions: [{
      ...notice,
      notice_version_id: `standalone-${sha256}`,
      text,
      text_sha256: sha256,
    }],
  };
}
