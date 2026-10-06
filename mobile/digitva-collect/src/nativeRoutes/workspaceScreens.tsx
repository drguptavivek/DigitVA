import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useMemo, useRef, useState } from "react";
import { Alert, Text, View } from "react-native";

import { useAppState } from "../AppState";
import { refreshAccessSummaryForAction, signOut } from "../auth";
import { t } from "../i18n";
import { isUnlocked } from "../interviewerDb";
import { createNativeWorkspaceTransport } from "../workspace/transport.native";
import { createWorkspaceApi, type WorkspaceApi } from "../workspace/api";
import { QueueScreen } from "../workspace/QueueScreen";
import { CaseWorkspaceScreen } from "../workspace/CaseWorkspaceScreen";
import type { WorkspaceIdentity, WorkspaceMode } from "../workspace/contracts";
import { DorisPanel } from "../workspace/doris/DorisPanel";
import { AttachmentMedia } from "../workspace/media/AttachmentMedia";
import { Button, errorText, Screen, useUiStyles } from "../ui";

type RouteParams = { userId?: string | string[]; vaSid?: string | string[]; mode?: string | string[] };
type AccessResult = { userId: string; roles: string[] };
type BoundMode = WorkspaceMode | "home";

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function hasWorkspaceRole(roles: string[], mode: BoundMode): boolean {
  if (mode === "coding") return roles.some((role) => role === "coder" || role === "coding_tester");
  if (mode === "reviewing") return roles.includes("reviewer");
  return true;
}

function useCurrentAccess(userId?: string) {
  const { reload } = useAppState();
  const [result, setResult] = useState<AccessResult>();
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const generation = useRef(0);

  useFocusEffect(useCallback(() => {
    const request = ++generation.current;
    let active = true;
    setResult(undefined);
    setError("");
    if (userId) {
      void refreshAccessSummaryForAction(userId).then((access) => {
        if (active && generation.current === request && access.user.user_id === userId) {
          setResult({ userId, roles: access.roles });
        }
      }).catch((loadError) => {
        if (active && generation.current === request) setError(errorText(loadError));
      }).finally(() => {
        if (active && generation.current === request) void reload();
      });
    }
    return () => {
      active = false;
      generation.current += 1;
    };
  }, [reload, retry, userId]));

  return {
    roles: result && result.userId === userId ? result.roles : undefined,
    error,
    retry: () => setRetry((value) => value + 1),
  };
}

function BoundScreen({
  userId,
  mode,
  vaSid,
}: {
  userId: string;
  mode: BoundMode;
  vaSid?: string;
}) {
  const router = useRouter();
  const styles = useUiStyles();
  const appState = useAppState();
  const { accounts } = appState;
  const account = accounts.find((item) => item.user_id === userId);
  const canBindWorkspace = Boolean(account && !account.needs_sign_in && !account.terms_required
    && !account.access_blocked && isUnlocked(userId));
  const { roles, error, retry } = useCurrentAccess(canBindWorkspace ? userId : undefined);
  const requester = useMemo(
    () => canBindWorkspace ? createNativeWorkspaceTransport(userId) : undefined,
    [canBindWorkspace, userId],
  );
  const api: WorkspaceApi | undefined = useMemo(
    () => requester ? createWorkspaceApi(requester) : undefined,
    [requester],
  );
  const currentUser = useRef(userId);
  currentUser.current = userId;

  if (!account || account.needs_sign_in || account.terms_required || account.access_blocked || !isUnlocked(userId)) {
    return <Screen title={account?.name ?? t("accountsTitle")}>
      <Text style={styles.error}>{t("loginRequiredAction")}</Text>
      <Button kind="secondary" label={t("accounts")} onPress={() => router.replace("/")} />
    </Screen>;
  }

  if (!roles) return <Screen title={mode === "coding" ? t("navCoding") : mode === "reviewing" ? t("navReview") : t("workspaceTitle")}>
    {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : <Text style={styles.muted}>{t("loading")}</Text>}
    {error ? <Button label={t("retryAccess")} onPress={retry} /> : null}
  </Screen>;

  if (!hasWorkspaceRole(roles, mode)) return <Screen title={t("workspaceTitle")}>
    <Text accessibilityRole="alert" style={styles.error}>{t("serverForbidden")}</Text>
    <Button kind="secondary" label={t("home")} onPress={() => router.replace("/")} />
  </Screen>;

  const identity: WorkspaceIdentity | undefined = vaSid && mode !== "home" ? { vaSid, mode } : undefined;
  const backToQueue = () => router.replace({ pathname: mode === "reviewing" ? "/reviewing" : "/coding", params: { userId } });
  if (identity && api && requester) return <CaseWorkspaceScreen
    identity={identity}
    api={api}
    onExit={mode === "view" ? () => router.replace({ pathname: "/workspace", params: { userId } }) : backToQueue}
    renderDoris={(workspace, onSaved, onDone) => <DorisPanel
      workspace={workspace}
      api={api}
      identity={identity}
      request={requester}
      onSaved={onSaved}
      onDone={onDone}
    />}
    renderMedia={(attachmentPath) => <AttachmentMedia identity={identity} attachmentPath={attachmentPath} userId={userId} />}
  />;

  if (mode === "view") return <Screen title={t("workspaceTitle")}>
    <Text style={styles.text}>{t("caseIdRequired")}</Text>
    <Button kind="secondary" label={t("home")} onPress={() => router.replace("/")} />
  </Screen>;

  if ((mode === "coding" || mode === "reviewing") && api) return <QueueScreen
    api={api}
    mode={mode}
    onExit={() => router.replace({ pathname: "/workspace", params: { userId } })}
    onOpen={(next) => {
      if (currentUser.current !== userId) return;
      router.push({ pathname: "/workspace", params: { userId, vaSid: next.vaSid, mode: next.mode } });
    }}
  />;

  async function doSignOut() {
    try {
      await signOut(userId);
      await appState.reload();
      router.replace("/");
    } catch {
      Alert.alert(t("signOut"), t("errGeneric"));
    }
  }

  function confirmSignOut() {
    Alert.alert(t("signOut"), t("pendingSignOutConfirm"), [
      { text: t("cancel"), style: "cancel" },
      { text: t("signOutConfirm"), style: "destructive", onPress: () => void doSignOut() },
    ]);
  }

  return <Screen title={account.name}>
    {account.collection_access || account.registration_access ? <Button label={t("navCollection")} onPress={() => router.push({ pathname: "/worklist", params: { userId } })} /> : null}
    {account.coding_access ? <Button label={t("navCoding")} onPress={() => router.push({ pathname: "/coding", params: { userId } })} /> : null}
    {account.reviewing_access ? <Button label={t("navReview")} onPress={() => router.push({ pathname: "/reviewing", params: { userId } })} /> : null}
    <View style={{ gap: 8 }}>
      <Button kind="secondary" label={t("settings")} onPress={() => router.push("/settings")} />
      <Button kind="secondary" label={t("lockNow")} onPress={() => void appState.lockNow()} />
      <Button kind="danger" label={t("signOut")} onPress={confirmSignOut} />
    </View>
  </Screen>;
}

export function WorkspaceScreen() {
  const params = useLocalSearchParams<RouteParams>();
  const userId = first(params.userId);
  const rawMode = first(params.mode);
  const mode: BoundMode = rawMode === "coding" || rawMode === "reviewing" || rawMode === "view" ? rawMode : "home";
  const vaSid = first(params.vaSid);
  if (!userId) return <Screen title={t("workspaceTitle")}><Text>{t("accountsEmpty")}</Text></Screen>;
  return <BoundScreen userId={userId} mode={mode} vaSid={vaSid} />;
}

export function CodingScreen() {
  const userId = first(useLocalSearchParams<RouteParams>().userId);
  return userId ? <BoundScreen userId={userId} mode="coding" /> : <Screen title={t("workspaceTitle")}><Text>{t("accountsEmpty")}</Text></Screen>;
}

export function ReviewingScreen() {
  const userId = first(useLocalSearchParams<RouteParams>().userId);
  return userId ? <BoundScreen userId={userId} mode="reviewing" /> : <Screen title={t("workspaceTitle")}><Text>{t("accountsEmpty")}</Text></Screen>;
}
