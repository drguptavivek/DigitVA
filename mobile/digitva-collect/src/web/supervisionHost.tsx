import { useMemo } from "react";
import { useRouter } from "expo-router";

import { SUPERVISION_ROLES } from "../api";
import { useAppState } from "../AppState";
import type { SupervisionHost } from "../supervision/host";
import { trainingRequester } from "../training";
import type { JsonRequester } from "../workspace/api";
import { createWebWorkspaceTransport } from "../workspace/transport.web";
import { AddIdentifierAction } from "./CaseIdentifiers";
import { browserErrorText } from "./common";

/** The browser's supervision host: the session's requester (training scope in the Training screens) and the web routes. */
export function useWebSupervisionHost(): SupervisionHost | undefined {
  const { bootstrap } = useAppState();
  const router = useRouter();
  const request: JsonRequester | undefined = useMemo(() => {
    if (!bootstrap) return undefined;
    const transport = createWebWorkspaceTransport(bootstrap.csrf);
    return bootstrap.scope === "training" ? trainingRequester(transport) : transport;
  }, [bootstrap]);
  return useMemo(() => request && {
    request,
    errorText: browserErrorText,
    openDeathEdit: (deathId) => router.push({ pathname: "/death-registration", params: { deathId, from: "supervisor" } } as never),
    openInterviewEdit: (edit) => router.push({
      pathname: "/interview",
      params: {
        revisionDraftId: edit.draft_id,
        revisionProjectId: edit.project_id,
        revisionSiteId: edit.site_id,
        revisionVaSid: edit.va_sid,
        revisionBy: "supervisor",
      },
    } as never),
    consentWithdrawal: true,
    identifierAction: (row, onChanged) => <AddIdentifierAction row={row} onChanged={onChanged} />,
  }, [request, router]);
}

/** Whether the session may open the supervision list (the server re-checks every case). */
export function useCanSupervise(): boolean {
  const { bootstrap } = useAppState();
  return bootstrap?.access.roles.some((role) => SUPERVISION_ROLES.includes(role)) === true;
}
