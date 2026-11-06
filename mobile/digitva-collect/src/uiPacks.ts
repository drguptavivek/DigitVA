/**
 * Server-delivered UI language packs (digitva-dt1e, digitva-s028; docs/policy/ui-strings.md).
 *
 * The server lists its published UI languages at GET /api/v1/ui-strings and serves each one's full
 * pack at /api/v1/ui-strings/<locale>: `strings` (the app's text) and `form` (the WHO form's own
 * labels). The app fetches the list and the pack it needs when it can reach its server (start,
 * language switch, sync), keeps the last list and pack per language on the device, and lays the
 * pack over the bundled dictionary. Offline it uses the stored pack, else the bundled text, else
 * English. Every key is checked here before use and a bad one is dropped (see validPackStrings).
 *
 * Packs are reference text with no personal data, so they live outside the encrypted stores
 * (src/uiPackStore.ts: localStorage in a browser, a file on a phone).
 */
import { useSyncExternalStore } from "react";
import { ENGLISH_UI_MESSAGE_TEMPLATES, type WhoVaUiTranslations } from "@drguptavivek/who-2022-va";
import { requestRaw } from "./api";
import { readStoredPack, writeStoredPack } from "./uiPackStore";
import {
  dropUiPack,
  normalizeLocale,
  setServerUiLanguages,
  setUiPack,
  subscribeUiLanguages,
  uiLanguages,
  validPackStrings,
  type UiLanguage,
} from "./i18n";

export const UI_STRINGS_API = "/api/v1/ui-strings";

const LOCALE_RE = /^[a-z]{2,3}$/;
const TAG_RE = /^[a-z]{2,3}(-[A-Za-z0-9]{2,8}){0,3}$/;
const VERSION_RE = /^[0-9a-f]{64}$/;
const FORM_REFERENCE = ENGLISH_UI_MESSAGE_TEMPLATES as unknown as Record<string, string>;

interface StoredPack {
  version: string;
  strings: Record<string, string>;
  form: Record<string, string>;
}

/** Validated WHO form labels per language; read by formUiTranslations(). */
const formPacks: Record<string, Record<string, string>> = {};
let formRevision = 0;

// --- storage ---------------------------------------------------------------

const slugFor = (server: string) => (server ? server.toLowerCase().replace(/[^a-z0-9]+/g, "_") : "same_origin");

// --- parsing ---------------------------------------------------------------

/** The server's list, entry by entry; an entry that fails a check is left out. */
export function parseUiLanguageList(value: unknown): UiLanguage[] {
  const list = value && typeof value === "object" ? (value as { languages?: unknown }).languages : undefined;
  if (!Array.isArray(list)) return [];
  return list.flatMap((item): UiLanguage[] => {
    if (!item || typeof item !== "object") return [];
    const { locale, native_name: name, bcp47_tag: tag, direction, version, reviewed } = item as Record<string, unknown>;
    if (typeof locale !== "string" || !LOCALE_RE.test(locale) || locale === "en") return [];
    if (typeof name !== "string" || !name.trim() || name.length > 64 || /[<>]/.test(name)) return [];
    if (typeof tag !== "string" || !TAG_RE.test(tag) || (direction !== "ltr" && direction !== "rtl")) return [];
    if (typeof version !== "string" || !VERSION_RE.test(version)) return [];
    const share = typeof reviewed === "number" && reviewed >= 0 && reviewed <= 1 ? reviewed : 0;
    return [{ code: locale, label: name, language: tag, direction, reviewed: share, bundled: false, version }];
  });
}

function parsePack(value: unknown): StoredPack | undefined {
  if (!value || typeof value !== "object") return undefined;
  const { version, strings, form } = value as Record<string, unknown>;
  if (typeof version !== "string" || !VERSION_RE.test(version)) return undefined;
  return {
    version,
    strings: (strings && typeof strings === "object" ? strings : {}) as Record<string, string>,
    form: (form && typeof form === "object" ? form : {}) as Record<string, string>,
  };
}

/** Lay a pack over the bundled text of `code`, app strings and form labels both checked key by key. */
export function applyUiPack(code: string, pack: { strings?: unknown; form?: unknown }): void {
  formPacks[code] = validPackStrings(pack.form, FORM_REFERENCE);
  formRevision += 1;
  setUiPack(code, pack.strings); // notifies subscribers once for both namespaces
}

/** Drop the pack of a language the server no longer publishes, in memory and on the device. */
async function dropServerPack(slug: string, code: string): Promise<void> {
  delete formPacks[code];
  formRevision += 1;
  dropUiPack(code); // notifies subscribers once for both namespaces
  await writeStoredPack(`${slug}-${code}`, {}); // parsePack({}) is undefined: reads as absent
}

// --- fetching --------------------------------------------------------------

async function getJson(server: string, path: string, etag?: string): Promise<{ status: number; body: unknown }> {
  const response = await requestRaw(server, path, {
    background: true,
    timeoutMs: 15_000,
    ...(etag && VERSION_RE.test(etag) ? { ifNoneMatch: `"${etag}"` } : {}),
  });
  return { status: response.status, body: response.body === null ? undefined : JSON.parse(response.body) };
}

/**
 * Bring the language list and the pack for `locale` up to date for `server` ("" in a browser: same
 * origin). The stored copies are applied first, so an offline phone still shows its last pack; the
 * network step then replaces them when it can. Throws only on a network or server failure, after the
 * stored copies are in place, so callers may ignore the error.
 */
export async function syncUiPacks(server: string, locale: string | null | undefined): Promise<void> {
  const slug = slugFor(server);
  const stored = (await readStoredPack(`${slug}-list`)) as { version?: string; languages?: unknown } | undefined;
  setServerUiLanguages(true, parseUiLanguageList(stored));
  const code = normalizeLocale(locale);
  const listed = () => uiLanguages().find((entry) => entry.code === code && entry.version);
  const storedPack = listed() ? parsePack(await readStoredPack(`${slug}-${code}`)) : undefined;
  if (storedPack) applyUiPack(code, storedPack);

  const list = await getJson(server, UI_STRINGS_API, stored?.version);
  // Only a well-formed list ({languages: [...]}, possibly empty) is authoritative; anything else is
  // neither stored nor used to drop packs.
  const rawLanguages = (list.body as { languages?: unknown } | null | undefined)?.languages;
  if (list.status !== 304 && Array.isArray(rawLanguages)) {
    setServerUiLanguages(true, parseUiLanguageList(list.body));
    await writeStoredPack(`${slug}-list`, list.body);
    // A language the list no longer names was unpublished: a bundled one falls back to its bundled text.
    // An entry that is present but fails the client checks is not "absent": its pack is kept.
    const named = new Set(rawLanguages.map((item) => (item as { locale?: unknown } | null)?.locale));
    for (const stale of Object.keys(formPacks)) {
      if (!named.has(stale)) await dropServerPack(slug, stale);
    }
  }
  // The list may now offer the language asked for even if it was not on offer before.
  const target = normalizeLocale(locale);
  const entry = uiLanguages().find((item) => item.code === target && item.version);
  if (!entry) return;
  const held = target === code ? storedPack : parsePack(await readStoredPack(`${slug}-${target}`));
  if (held && held.version === entry.version) {
    applyUiPack(target, held);
    return;
  }
  const response = await getJson(server, `${UI_STRINGS_API}/${encodeURIComponent(target)}`, held?.version);
  const pack = response.status === 304 ? held : parsePack(response.body);
  if (!pack) return;
  applyUiPack(target, pack);
  if (response.status !== 304) await writeStoredPack(`${slug}-${target}`, pack);
}

/** Only the bundled languages: before enrolment and in standalone mode. */
export function offerBundledUiLanguagesOnly(): void {
  setServerUiLanguages(false, []);
}

// --- consumers -------------------------------------------------------------

/** Bundled plus published languages on offer now, with name, BCP 47 tag, direction and review share. */
export function useUiLanguages(): UiLanguage[] {
  return useSyncExternalStore(subscribeUiLanguages, uiLanguages, uiLanguages);
}

/** Bumps when any pack's form labels change; read it to rebuild formUiTranslations() in a render. */
export function useFormPackRevision(): number {
  return useSyncExternalStore(subscribeUiLanguages, () => formRevision, () => formRevision);
}

let formCache: { base: WhoVaUiTranslations; revision: number; value: WhoVaUiTranslations } | undefined;

/**
 * The WHO form's label packs for its `uiTranslations` prop: `base` (the vendor's built-ins, which
 * that prop replaces) with each server pack's form labels over it. Stable until a pack changes.
 */
export function formUiTranslations(base: WhoVaUiTranslations): WhoVaUiTranslations {
  if (formCache && formCache.base === base && formCache.revision === formRevision) return formCache.value;
  const value: WhoVaUiTranslations = { ...base };
  for (const [code, labels] of Object.entries(formPacks)) {
    if (Object.keys(labels).length) value[code] = { ...base[code], ...labels };
  }
  formCache = { base, revision: formRevision, value };
  return value;
}
