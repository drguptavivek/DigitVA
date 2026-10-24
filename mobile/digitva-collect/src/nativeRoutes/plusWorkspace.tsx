/**
 * Collect Plus only (APP_VARIANT=plus, src/appVariant.ts): the coding queue, the review queue and the case workspace
 * on the phone, the same QueueScreen and CaseWorkspaceScreen the web app renders, over the signed-in account's
 * bearer session. The plain build keeps CodingOnWeb for these routes (src/nativeRouteScreens.native.tsx).
 * DORIS still goes to the server here; the offline engine is wired in by phase B.
 */
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { useMemo } from "react";
import { Text } from "react-native";

import { useAppState } from "../AppState";
import { isUnlocked } from "../interviewerDb";
import { t } from "../i18n";
import { Button, Screen, useUiStyles } from "../ui";
import { createWorkspaceApi } from "../workspace/api";
import { CaseWorkspaceScreen } from "../workspace/CaseWorkspaceScreen";
import type { WorkspaceIdentity, WorkspaceMode } from "../workspace/contracts";
import { DorisPanel } from "../workspace/doris/DorisPanel";
import { AttachmentMedia } from "../workspace/media/AttachmentMedia.native";
import { createNativeWorkspaceTransport } from "../workspace/transport.native";
import { QueueScreen } from "../workspace/QueueScreen";

type Params = { userId?: string | string[]; vaSid?: string | string[]; mode?: string | string[] };

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function isMode(value: string | undefined): value is WorkspaceMode {
  return value === "coding" || value === "reviewing" || value === "view";
}

/** The account whose session the workspace uses: the route's `userId`, else the only account that may code or review. */
function usePlusUserId(mode: WorkspaceMode): string | undefined {
  const { userId } = useLocalSearchParams<Params>();
  const { accounts } = useAppState();
  const wanted = first(userId);
  if (wanted) return accounts.some((account) => account.user_id === wanted) ? wanted : undefined;
  const eligible = accounts.filter((account) => (mode === "reviewing" ? account.reviewing_access : account.coding_access));
  return eligible.length === 1 ? eligible[0].user_id : accounts.length === 1 ? accounts[0].user_id : undefined;
}

function Workspace({ mode, vaSid }: { mode: WorkspaceMode; vaSid?: string }) {
  const router = useRouter();
  const styles = useUiStyles();
  const userId = usePlusUserId(mode);
  const { accounts } = useAppState();
  const account = accounts.find((item) => item.user_id === userId);
  const request = useMemo(() => (userId ? createNativeWorkspaceTransport(userId) : undefined), [userId]);
  const api = useMemo(() => (request ? createWorkspaceApi(request) : undefined), [request]);

  if (!userId || !account || !request || !api) return <Redirect href="/" />;
  if (!isUnlocked(userId)) return <Redirect href={{ pathname: "/unlock", params: { userId } }} />;
  const allowed = mode === "view" || (mode === "reviewing" ? account.reviewing_access : account.coding_access);
  if (!allowed) {
    return <Screen title={t("workspaceTitle")}>
      <Text accessibilityRole="alert" style={styles.text}>{t("serverForbidden")}</Text>
      <Button kind="secondary" label={t("home")} onPress={() => router.replace("/")} />
    </Screen>;
  }

  if (vaSid) {
    const identity: WorkspaceIdentity = { vaSid, mode };
    return <CaseWorkspaceScreen
      identity={identity}
      api={api}
      onExit={() => router.replace({ pathname: mode === "reviewing" ? "/reviewing" : "/coding", params: { userId } })}
      renderDoris={(workspace, onSaved, onDone) => <DorisPanel
        workspace={workspace}
        api={api}
        identity={identity}
        request={request}
        onSaved={onSaved}
        onDone={onDone}
      />}
      renderMedia={(attachmentPath) => <AttachmentMedia identity={identity} attachmentPath={attachmentPath} />}
    />;
  }
  if (mode === "view") return <Redirect href="/" />;
  return <QueueScreen
    api={api}
    mode={mode}
    onOpen={(identity) => router.push({ pathname: "/workspace", params: { userId, vaSid: identity.vaSid, mode: identity.mode } })}
    onExit={() => router.replace("/")}
  />;
}

export function PlusCoding() {
  return <Workspace mode="coding" />;
}

export function PlusReviewing() {
  return <Workspace mode="reviewing" />;
}

/** `/workspace?vaSid&mode` opens a case; without a case it is the coding queue. */
export function PlusWorkspace() {
  const params = useLocalSearchParams<Params>();
  const vaSid = first(params.vaSid)?.trim();
  const mode = first(params.mode);
  return <Workspace mode={isMode(mode) ? mode : "coding"} vaSid={vaSid || undefined} />;
}
