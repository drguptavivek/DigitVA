/**
 * Collect Plus only (APP_VARIANT=plus, src/appVariant.ts): the coding queue, the review queue and the case workspace
 * on the phone, the same QueueScreen and CaseWorkspaceScreen the web app renders, over the signed-in account's
 * bearer session. The plain build keeps CodingOnWeb for these routes (src/nativeRouteScreens.native.tsx).
 * DORIS still goes to the server here; the offline engine is wired in by phase B.
 */
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { Text } from "react-native";

import { useAppState } from "../AppState";
import { isUnlocked, openInterviewerDb } from "../interviewerDb";
import { loadActiveSlot, loadDevice } from "../auth";
import { t } from "../i18n";
import { Button, Screen, useUiStyles } from "../ui";
import { getBundledVaDefinition } from "../coding/bundledVaDefinitions";
import { createWorkspaceApi } from "../workspace/api";
import { CaseWorkspaceScreen } from "../workspace/CaseWorkspaceScreen";
import type { WorkspaceIdentity, WorkspaceMode } from "../workspace/contracts";
import { DorisPanel } from "../workspace/doris/DorisPanel";
import { AttachmentMedia } from "../workspace/media/AttachmentMedia.native";
import { createNativeWorkspaceTransport } from "../workspace/transport.native";
import { QueueScreen } from "../workspace/QueueScreen";
import { createNativeCodingHistoryCache } from "../codingHistoryCache.native";
import type { CodingHistoryCache, CodingHistoryIdentity } from "../codingHistoryCache";
import { isIcd11DorisEnabled, useIcd11DorisPreference } from "../icd11DorisPreference";

type Params = { userId?: string | string[]; vaSid?: string | string[]; mode?: string | string[]; initialHistory?: string | string[] };

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
  const { initialHistory } = useLocalSearchParams<Params>();
  const styles = useUiStyles();
  const icd11Preference = useIcd11DorisPreference();
  const userId = usePlusUserId(mode);
  const { accounts } = useAppState();
  const account = accounts.find((item) => item.user_id === userId);
  const [historyContext, setHistoryContext] = useState<{ identity: CodingHistoryIdentity; cache: CodingHistoryCache }>();
  const historyCacheRef = useRef<CodingHistoryCache | undefined>(undefined);
  historyCacheRef.current = historyContext?.cache;
  const request = useMemo(() => (userId ? createNativeWorkspaceTransport(userId) : undefined), [userId]);
  const api = useMemo(() => {
    if (!request) return undefined;
    const base = createWorkspaceApi(request);
    const invalidate = (vaSid: string) => {
      const cache = historyCacheRef.current;
      if (cache && historyContext?.identity) void cache.invalidateCase(historyContext.identity, vaSid).catch(() => undefined);
    };
    return {
      ...base,
      // The VA cause bucket comes from the pack bundled in the app, as offline: no network call, same answer in every mode.
      // A "/" cluster needs WHO's causing condition, which only the server (online) or the engine (offline editor) knows;
      // the server applies the same rule, and the pack's first stem is the fallback when it cannot be reached.
      getVaDefinitionForIcd: (code: string) => code.includes("/")
        ? base.getVaDefinitionForIcd(code).catch(() => getBundledVaDefinition(code))
        : getBundledVaDefinition(code),
      async saveInitial(...args: Parameters<typeof base.saveInitial>) {
        const reply = await base.saveInitial(...args);
        invalidate(args[0]);
        return reply;
      },
      async saveFinal(...args: Parameters<typeof base.saveFinal>) {
        const reply = await base.saveFinal(...args);
        invalidate(args[0]);
        return reply;
      },
      async saveNotCodeable(...args: Parameters<typeof base.saveNotCodeable>) {
        const reply = await base.saveNotCodeable(...args);
        invalidate(args[0]);
        return reply;
      },
      async recode(...args: Parameters<typeof base.recode>) {
        const reply = await base.recode(...args);
        invalidate(args[0]);
        return reply;
      },
    };
  }, [historyContext?.identity, request]);

  useEffect(() => {
    let active = true;
    setHistoryContext(undefined);
    if (!userId || mode !== "coding" || !account || account.standalone || account.coding_access !== true ||
        account.signed_out || account.needs_sign_in || account.access_removed || account.terms_required || account.access_blocked ||
        !account.server || !/^[a-f0-9]{64}$/i.test(account.coding_history_access ?? "")) return () => { active = false; };
    void (async () => {
      const slot = await loadActiveSlot();
      const device = await loadDevice(slot);
      if (!device || new URL(device.server).origin !== new URL(account.server!).origin) return;
      const identity: CodingHistoryIdentity = {
        mode: slot === "demo" ? "demo" : "enrolled",
        serverOrigin: new URL(device.server).origin,
        userId,
      };
      const db = await openInterviewerDb(userId);
      const cache = await createNativeCodingHistoryCache(db, identity, account.coding_history_access);
      if (active) setHistoryContext({ identity, cache });
    })().catch(() => {
      if (active) setHistoryContext(undefined);
    });
    return () => { active = false; };
  }, [account?.access_blocked, account?.access_removed, account?.coding_access, account?.coding_history_access, account?.needs_sign_in, account?.server,
    account?.signed_out, account?.standalone, account?.terms_required, mode, userId]);

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
      icd11DorisEnabled={icd11Preference.enabled}
      onIcd11DorisOpenSettings={() => router.push({ pathname: "/settings", params: { userId } })}
      assertIcd11DorisEnabled={async () => {
        if (!await isIcd11DorisEnabled()) throw new Error("icd11_doris_disabled");
      }}
      onExit={() => router.replace({ pathname: mode === "reviewing" ? "/reviewing" : "/coding", params: { userId } })}
      renderDoris={(workspace, onSaved, onDone, guardedApi) => <DorisPanel
        workspace={workspace}
        api={guardedApi}
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
    initialView={first(initialHistory) === "1" ? { allProjects: false, showHistory: true, offset: 0 } : undefined}
    historyCache={historyContext?.cache}
    historyIdentity={historyContext?.identity}
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
