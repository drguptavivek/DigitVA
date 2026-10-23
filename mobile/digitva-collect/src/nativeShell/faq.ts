/**
 * "Common questions" of the phone Help sheet (digitva-zgl2): bundled in the string dictionaries (faq_<id>_q / _a, English
 * and Hindi), so they work offline. An item may carry a button that opens the screen its answer names.
 */
import { t, type StringKey } from "../i18n";

export type FaqTarget = "account" | "sent" | "drafts" | "sync" | "settings";

export const FAQ: ReadonlyArray<{ id: string; target?: FaqTarget }> = [
  { id: "language", target: "account" },
  { id: "qlanguage" },
  { id: "sent", target: "sent" },
  { id: "resume", target: "drafts" },
  { id: "errors", target: "sync" },
  { id: "exporterrors", target: "settings" },
  { id: "otherperson" },
  { id: "unsent", target: "sync" },
  { id: "revise", target: "sent" },
  { id: "media" },
  { id: "clock" },
];

const GO_LABEL: Record<FaqTarget, StringKey> = {
  account: "faqGoAccount",
  sent: "faqGoSent",
  drafts: "faqGoDrafts",
  sync: "faqGoSync",
  settings: "faqGoSettings",
};

export interface FaqEntry { id: string; question: string; answer: string; target?: FaqTarget; goLabel?: string }

/** The entries in the current language whose question or answer contains every word of `query` (case-insensitive). */
export function faqEntries(query = ""): FaqEntry[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  return FAQ.map(({ id, target }) => ({
    id,
    question: t(`faq_${id}_q` as StringKey),
    answer: t(`faq_${id}_a` as StringKey),
    target,
    goLabel: target ? t(GO_LABEL[target]) : undefined,
  })).filter((entry) => {
    const text = `${entry.question} ${entry.answer}`.toLowerCase();
    return words.every((word) => text.includes(word));
  });
}
