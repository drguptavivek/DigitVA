/**
 * App UI strings: one JSON dictionary per language and a tiny t().
 * The questionnaire has its own language picker; during a browser interview,
 * the app chrome follows that selected form language as well.
 *
 * REVIEW NEEDED: strings/hi.json was written by a non-native author and must
 * be reviewed by a native Hindi speaker before field use (same process as
 * digitva-fb5 for the questionnaire translations).
 */
import baseEn from "./strings/en.json";
import baseHi from "./strings/hi.json";
// The Petrol theme screens' strings live in their own files (merged here) so the main dictionaries stay one owner's.
import themeEn from "./strings/theme-en.json";
import themeHi from "./strings/theme-hi.json";

const en: Record<AnyKey, string> = { ...baseEn, ...themeEn };
const hi: Partial<Record<AnyKey, string>> = { ...baseHi, ...themeHi };

/** A key of the main dictionary (src/strings/en.json); callers that index that file by key rely on this. */
export type StringKey = keyof typeof baseEn;
/** A key of the theme screens' dictionary (src/strings/theme-en.json); t() takes either. */
export type ThemeStringKey = keyof typeof themeEn;
type AnyKey = StringKey | ThemeStringKey;

const DICTIONARIES: Record<string, Partial<Record<AnyKey, string>>> = { en, hi };
/**
 * The bundled languages, for screens that predate the list. `language`: the BCP 47 tag each name is
 * written in, so a screen reader pronounces "हिन्दी" on an English screen. New code reads
 * useUiLanguages() (src/uiPacks.ts) instead.
 */
export const UI_LOCALES = [
  { code: "en", label: "English", language: "en" },
  { code: "hi", label: "हिन्दी", language: "hi-IN" }
 ] as const;

/**
 * One UI language the app may offer (digitva-s028): the bundled ones plus, once the phone is enrolled
 * (or in a browser), the server's published list. `label` is the name in its own script, `language`
 * the BCP 47 tag for formatting and screen readers, `reviewed` the share a native speaker has
 * reviewed (unknown for a bundled language the server does not list).
 */
export interface UiLanguage {
  code: string;
  label: string;
  language: string;
  direction: "ltr" | "rtl";
  reviewed?: number;
  bundled: boolean;
  version?: string;
}

/** Right-to-left is not offered until it is checked on a phone (docs/policy/expo-client.md). */
const RTL_READY = false;

const BUNDLED_LANGUAGES: UiLanguage[] = [
  // English formats dates the Indian way ("6 Nov 2026"), as the screens always have.
  { code: "en", label: "English", language: "en-IN", direction: "ltr", reviewed: 1, bundled: true },
  { code: "hi", label: "हिन्दी", language: "hi-IN", direction: "ltr", bundled: true },
];

let current = "en";
/** The language last asked for, kept so a pack or list that arrives later can still switch to it. */
let requested: string | null | undefined = "en";
let serverEnabled = false;
let serverLanguages: UiLanguage[] = [];
/** Validated server packs per language, laid over the bundled dictionary in t(). */
const packs: Record<string, Partial<Record<AnyKey, string>>> = {};
let languages: UiLanguage[] = BUNDLED_LANGUAGES;
const listeners = new Set<() => void>();

function rebuildLanguages(): void {
  const served = serverEnabled ? serverLanguages.filter((entry) => RTL_READY || entry.direction === "ltr") : [];
  const bundled = BUNDLED_LANGUAGES.map((entry) => {
    const server = served.find((item) => item.code === entry.code);
    return server ? { ...entry, reviewed: server.reviewed, version: server.version } : entry;
  });
  languages = [...bundled, ...served.filter((item) => !BUNDLED_LANGUAGES.some((entry) => entry.code === item.code))];
  current = normalizeLocale(requested);
  for (const listener of listeners) listener();
}

/** Every UI language this phone may offer now; a stable array until the list changes. */
export const uiLanguages = (): UiLanguage[] => languages;

/** Called on any change to the list, the packs or the resolved language. */
export function subscribeUiLanguages(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Offer the server's languages (enrolled phone, browser) or only the bundled ones (before enrolment, standalone). */
export function setServerUiLanguages(enabled: boolean, list: UiLanguage[] = serverLanguages): void {
  serverEnabled = enabled;
  serverLanguages = list;
  rebuildLanguages();
}

const PLACEHOLDER = /\{(\w+)\}/g;
// Markup, a link scheme or a control character: none of the app's strings has one.
const UNSAFE = /<[a-z!/?]|javascript:|data:|[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/i;
const MAX_TEXT = 16000;

const placeholderSet = (text: string) => [...new Set([...text.matchAll(PLACEHOLDER)].map((match) => match[1]))].sort().join(",");

/**
 * Keep the strings of a server pack that pass the client's checks, key by key: a known English key,
 * a non-empty string under the cap, the same {placeholder} set as the English, no markup.
 */
export function validPackStrings(
  strings: unknown,
  reference: Readonly<Record<string, string>>,
): Record<string, string> {
  const kept: Record<string, string> = {};
  if (!strings || typeof strings !== "object" || Array.isArray(strings)) return kept;
  for (const [key, text] of Object.entries(strings as Record<string, unknown>)) {
    if (!Object.hasOwn(reference, key) || typeof text !== "string") continue;
    if (!text.trim() || text.length > MAX_TEXT || UNSAFE.test(text)) continue;
    if (placeholderSet(text) !== placeholderSet(reference[key])) continue;
    kept[key] = text;
  }
  return kept;
}

/** Lay a server pack's app strings over the bundled text of `code`; bad keys are dropped. Returns what was kept. */
export function setUiPack(code: string, strings: unknown): Record<string, string> {
  const kept = validPackStrings(strings, en);
  packs[code] = kept;
  rebuildLanguages();
  return kept;
}

/** Forget the server pack of `code` (no longer published): its bundled text, else English, shows again. */
export function dropUiPack(code: string): void {
  delete packs[code];
  rebuildLanguages();
}

/** Resolve an exact locale first, then its base language, then English, among the languages on offer. */
export function normalizeLocale(code: string | null | undefined): string {
  const normalized = (code ?? "").trim().toLowerCase().replace(/_/g, "-");
  const offered = (value: string) => !!value && languages.some((entry) => entry.code === value);
  if (offered(normalized)) return normalized;
  const base = normalized.split("-")[0];
  return offered(base) ? base : "en";
}

/** Use `code` when it is on offer (or its base language), else English. */
export function setUiLocale(code: string | null | undefined): string {
  requested = code;
  current = normalizeLocale(code);
  return current;
}

export const uiLocale = () => current;

/** The language last asked for, before it is resolved against the languages on offer. */
export const requestedUiLocale = () => requested;

/** The current language's list entry; English when nothing else applies. */
export const uiLanguage = (code: string = current): UiLanguage =>
  languages.find((entry) => entry.code === normalizeLocale(code)) ?? BUNDLED_LANGUAGES[0];

/** BCP 47 tag of the current UI language, for toLocaleString and screen-reader language. */
export const uiLanguageTag = (code?: string): string => uiLanguage(code).language;

/** Whether `text` is, word for word, one of the app's own fixed strings (so safe to keep in the error log). */
export function uiTextKnown(text: string): boolean {
  return [...Object.values(DICTIONARIES), ...Object.values(packs)].some((dictionary) => Object.values(dictionary).includes(text));
}

/** The string for `key` in `locale`: its server pack, its bundled text, English, then the key itself. */
export function translate(locale: string, key: StringKey | ThemeStringKey, vars: Record<string, string | number> = {}): string {
  const code = normalizeLocale(locale);
  const text = packs[code]?.[key] ?? DICTIONARIES[code]?.[key] ?? en[key] ?? key;
  return text.replace(PLACEHOLDER, (match, name: string) => (name in vars ? String(vars[name]) : match));
}

/** The string for `key` in the current language (see translate). */
export function t(key: StringKey | ThemeStringKey, vars: Record<string, string | number> = {}): string {
  return translate(current, key, vars);
}

/**
 * Every questionnaire language the project enables, whether or not the app has a UI pack for it
 * (digitva-s028): without one the app's own text stays English.
 */
export function questionnaireLocales<T extends { code: string }>(available: T[] | undefined): T[] {
  return [...(available ?? [])];
}

/** New drafts use the enabled default, then enabled English, then the first enabled language. */
export function questionnaireDefault(available: Array<{ code: string }> | undefined, requested: string | undefined): string {
  if (available === undefined) return "en"; // Legacy settings predate the enabled-language list.
  const locales = questionnaireLocales(available);
  if (!locales.length) throw new Error("questionnaire_language_not_enabled");
  return locales.find((entry) => entry.code === requested)?.code ??
    locales.find((entry) => entry.code === "en")?.code ?? locales[0]?.code ?? "en";
}

/** A well-formed BCP 47-style language code ("hi", "ml", "pt-br"). A draft may be in any project-enabled
 * questionnaire language, with or without a UI pack, so resume checks the shape, not the UI language list. */
export function isLocaleCode(value: unknown): value is string {
  return typeof value === "string" && /^[a-z]{2,3}(-[a-z0-9]{2,8})*$/i.test(value);
}
