/**
 * Localizing a questionnaire's user-facing text.
 *
 * Two forms, and the choice between them is not stylistic:
 *
 * - `localized` flattens ODK's inline markup to plain text. Use it where only
 *   a string will do — accessibility labels, the answer preview, comparisons.
 * - `localizedRich` keeps the markup for text that is rendered through
 *   `RichText`, which turns it into styled spans.
 *
 * Reaching for `localized` on text that is about to be rendered silently drops
 * every distinction the form author drew, which is how 337 WHO guidance fields
 * lost their colour before this was separated.
 */
import { localeCandidates, localizeText } from "../i18n.js";

/**
 * ODK's inline markup, removed. `<br>` becomes a newline; the handful of
 * entities the questionnaires use are decoded.
 */
export function plainText(value: string | undefined): string {
  if (!value) return "";
  return value
    .replace(/<br\s*\/?\s*>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .trim();
}

/** The localized text with markup flattened away. */
export function localized(
  text: Record<string, string | undefined>,
  locale: string,
  fallback: string
): string {
  return plainText(localizeText(text, locale, fallback));
}

/** The localized text with its markup intact, for rendering through `RichText`. */
export function localizedRich(
  text: Record<string, string | undefined>,
  locale: string,
  fallback: string
): string {
  return localizeText(text, locale, fallback);
}

/**
 * The English to show beside a translated string (`show-english`), markup
 * intact for `RichText`. Empty when the display locale is English, when the
 * text has no English, or when the English is what is already displayed (an
 * untranslated string falls back to it).
 */
export function englishAlongside(text: Record<string, string | undefined>, locale: string): string {
  const english = text.en ?? "";
  if (!english || localeCandidates(locale)[0]?.split("-")[0] === "en") return "";
  return english === localizeText(text, locale) ? "" : english;
}
