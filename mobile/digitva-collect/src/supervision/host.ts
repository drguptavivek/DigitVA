import type { ReactNode } from "react";

import type { JsonRequester } from "../workspace/api";
import type { SupervisedCase, SupervisedCaseDetail } from "./api";

/**
 * What the supervision screens need from the platform that shows them (the browser or the phone):
 * how to call the server, how to word an error, where "Edit" goes, and which actions this platform offers.
 */
export interface SupervisionHost {
  request: JsonRequester;
  errorText: (error: unknown) => string;
  /** Open the death report of this case for correction. */
  openDeathEdit: (deathId: string) => void;
  /** Absent: this platform does not offer "Edit interview". */
  openInterviewEdit?: (edit: NonNullable<SupervisedCaseDetail["edit_interview"]>) => void;
  /** Recording a consent withdrawal is browser-only (docs/policy/mobile-sign-in.md). */
  consentWithdrawal: boolean;
  /** The per-case "Add registration number" action; absent where the platform has none. */
  identifierAction?: (row: SupervisedCase, onChanged: () => void) => ReactNode;
}
