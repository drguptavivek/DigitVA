/**
 * "Your languages" and "Forms pending coding" on the coding home screen, and the training queues' "X of Y"
 * (docs/policy/training-session-types.md). Read from `/coding/stats`, whose keys are additive: an older server
 * sends none of them and these helpers then answer nothing, so the screen looks as it did.
 */
import { t } from "../i18n";
import type { CodingStats } from "./contracts";

type Count = { coded: number; total: number };

function record(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

function isCount(value: unknown): value is Count {
  const item = record(value);
  return Boolean(item) && Number.isInteger(item!.coded) && Number.isInteger(item!.total);
}

/** A language code as a name: "hindi" -> "Hindi"; the server's `unrecorded` bucket in the UI language. */
export function languageLabel(code: string): string {
  if (code === "unrecorded") return t("languageUnrecorded");
  return code ? code.charAt(0).toUpperCase() + code.slice(1) : code;
}

/**
 * The two lines, or undefined without a `languages` key. `mine` is "none set" for an empty list; `pending` is
 * undefined when no language has forms (only non-zero buckets are shown).
 */
export function codingLanguageLines(stats: CodingStats | undefined): { mine: string; pending?: string } | undefined {
  const languages = record(stats?.languages);
  if (!languages || !Array.isArray(languages.mine)) return undefined;
  const mine = languages.mine.filter((code): code is string => typeof code === "string");
  const pending = (Array.isArray(languages.pending) ? languages.pending : [])
    .map(record)
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item!.language === "string" && Number.isInteger(item!.count) && (item!.count as number) > 0)
    .map((item) => `${languageLabel(item.language as string)} ${item.count}`);
  return {
    mine: t("queueYourLanguages", { languages: mine.length ? mine.map(languageLabel).join(", ") : t("queueLanguagesNone") }),
    ...(pending.length ? { pending: t("queuePendingByLanguage", { counts: pending.join(" · ") }) } : {}),
  };
}

/**
 * The training queues from `training_queues`: `standard` always, `own` only in a self-coding session (the server
 * sends null otherwise). Undefined off the training side or from an older server.
 */
export function trainingQueueCounts(stats: CodingStats | undefined): { standard: Count; own?: Count } | undefined {
  const queues = record(stats?.training_queues);
  if (!queues || !isCount(queues.standard)) return undefined;
  return { standard: queues.standard, ...(isCount(queues.own) ? { own: queues.own } : {}) };
}
