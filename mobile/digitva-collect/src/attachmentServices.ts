/**
 * Web build: the browser form has its own attachment buffer (vendor web adapters), so the phone's native
 * services are absent here. The native implementation is attachmentServices.native.ts.
 */
import type { WhoVaPlatformServices } from "@drguptavivek/who-2022-va";

import type { Db } from "./drafts";

export interface AttachmentServicesContext {
  db: Db | undefined;
  draftId: string | undefined;
  projectId: string | null;
  /** The interview is on a case the server knows, so its files can be sent ahead of it (decision 4). */
  canAttach: boolean;
}

export function useAttachmentServices(_context: AttachmentServicesContext): WhoVaPlatformServices {
  return {};
}
