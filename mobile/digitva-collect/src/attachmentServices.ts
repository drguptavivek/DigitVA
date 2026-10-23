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
}

export function useAttachmentServices(_context: AttachmentServicesContext): WhoVaPlatformServices {
  return {};
}
