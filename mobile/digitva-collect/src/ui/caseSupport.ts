/**
 * Pure helpers for the phone case cards' copy icon: the "Case 000274" label and the support text a user
 * sends to the central team. No React, no I/O.
 */
import { APP_VERSION } from "../appVersion";
import { t } from "../i18n";
import { shortCaseNumber } from "../workspace/caseLabel";

/**
 * "Case 000274" for a masked id like PHC01-000274_172313647 or a register id like SC01-000274; any other shape is
 * shown as given. Display only: the copy text keeps the full id, which tells sites apart.
 */
export function caseNumberLabel(uniqueId: string): string {
  const number = shortCaseNumber(uniqueId) ?? /^[A-Za-z0-9]+-(\d{4,})$/.exec(uniqueId)?.[1];
  return number ? t("queueCaseNumber", { number }) : uniqueId;
}

export interface CaseSupportFields {
  caseId?: string | null;
  projectId?: string | null;
  unit?: string | null;
  ageYears?: number | null;
  sex?: string | null;
  status?: string | null;
}

/**
 * A card's details as plain text for its copy icon. Never the deceased's name, phone number, address or GPS:
 * the text leaves the app (WhatsApp, email), so it carries only what support needs to find the case.
 */
export function caseSupportText(f: CaseSupportFields): string {
  const lines = [
    f.caseId ? (/^Case /.test(f.caseId) ? f.caseId : `Case ${f.caseId}`) : null,
    [f.projectId, f.unit].filter(Boolean).join(" · "),
    [f.ageYears != null ? `Age: ${f.ageYears}` : null, f.sex ? `Sex: ${f.sex}` : null].filter(Boolean).join(" · "),
    f.status ? `Status: ${f.status}` : null,
    `App ${APP_VERSION}`,
  ];
  return lines.filter(Boolean).join("\n");
}
