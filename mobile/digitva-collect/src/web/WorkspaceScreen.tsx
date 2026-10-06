import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { Text, TextInput, View } from "react-native";

import { useAppState } from "../AppState";
import { loadBrowserSession } from "../client/session";
import { t } from "../i18n";
import { Button, useUiStyles } from "../ui";
import { createWorkspaceApi, type JsonRequester, type WorkspaceApi } from "../workspace/api";
import { CaseWorkspaceScreen } from "../workspace/CaseWorkspaceScreen";
import { QueueScreen } from "../workspace/QueueScreen";
import { createWebWorkspaceTransport } from "../workspace/transport.web";
import type { WorkspaceIdentity, WorkspaceMode } from "../workspace/contracts";
import { DorisPanel } from "../workspace/doris/DorisPanel";
import { AttachmentMedia } from "../workspace/media/AttachmentMedia.web";
import { browserErrorText, LoginLanding, WebShell } from "./common";

type RouteParams = { vaSid?: string | string[]; mode?: string | string[] };
type SessionCheck = { key: string; bootstrap: NonNullable<ReturnType<typeof useAppState>["bootstrap"]> };

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function hasWorkspaceRole(roles: string[], mode: WorkspaceMode): boolean {
  if (mode === "coding") return roles.some((role) => role === "coder" || role === "coding_tester");
  if (mode === "reviewing") return roles.includes("reviewer");
  return true;
}

function currentPathMode(forcedMode: WorkspaceMode | undefined, routeMode: string | undefined): WorkspaceMode | "home" {
  if (forcedMode) return forcedMode;
  if (routeMode === "coding" || routeMode === "reviewing" || routeMode === "view") return routeMode;
  return "home";
}

function WorkspaceScreen({ forcedMode }: { forcedMode?: WorkspaceMode } = {}) {
  const router = useRouter();
  const params = useLocalSearchParams<RouteParams>();
  const vaSid = first(params.vaSid)?.trim();
  const mode = currentPathMode(forcedMode, first(params.mode));
  const { bootstrap, loginUrl, reload, logout } = useAppState();
  const styles = useUiStyles();
  const [sessionCheck, setSessionCheck] = useState<SessionCheck>();
  const [sessionError, setSessionError] = useState("");
  const [viewVaSid, setViewVaSid] = useState("");
  const requestGeneration = useRef(0);
  const userId = bootstrap?.user.user_id;
  const checkKey = `${userId ?? ""}:${mode}`;

  useEffect(() => {
    const request = ++requestGeneration.current;
    let active = true;
    setSessionCheck(undefined);
    setSessionError("");
    void loadBrowserSession().then(async (result) => {
      if (!active || requestGeneration.current !== request) return;
      if (!result.authenticated) {
        setSessionError(t("serverUnauthorized"));
        return;
      }
      if (userId && result.bootstrap.user.user_id !== userId) {
        await reload();
        if (active && requestGeneration.current === request) setSessionError(t("serverUnauthorized"));
        return;
      }
      setSessionCheck({ key: checkKey, bootstrap: result.bootstrap });
      await reload();
    }).catch((error) => {
      if (active && requestGeneration.current === request) setSessionError(browserErrorText(error));
    });
    return () => {
      active = false;
      requestGeneration.current += 1;
    };
  }, [checkKey, reload, userId]);

  const activeBootstrap = sessionCheck?.key === checkKey ? sessionCheck.bootstrap : undefined;
  const requester: JsonRequester | undefined = useMemo(
    () => activeBootstrap ? createWebWorkspaceTransport(activeBootstrap.csrf) : undefined,
    [activeBootstrap],
  );
  const api: WorkspaceApi | undefined = useMemo(
    () => requester ? createWorkspaceApi(requester) : undefined,
    [requester],
  );

  if (loginUrl && !bootstrap) return <LoginLanding />;
  if (!activeBootstrap) return <WebShell title={t("workspaceTitle")}>
    {sessionError ? <Text role="alert" style={styles.error}>{sessionError}</Text> : <Text style={styles.muted}>{t("loading")}</Text>}
  </WebShell>;

  if (mode !== "home" && !hasWorkspaceRole(activeBootstrap.access.roles, mode)) {
    return <WebShell title={t("workspaceTitle")}>
      <Text role="alert" style={styles.error}>{t("serverForbidden")}</Text>
      <Button kind="secondary" label={t("home")} onPress={() => router.replace("/workspace")} />
    </WebShell>;
  }

  if (vaSid && mode !== "home" && api && requester) {
    const identity: WorkspaceIdentity = { vaSid, mode };
    return <CaseWorkspaceScreen
      identity={identity}
      api={api}
      onExit={() => mode === "view" ? router.replace("/workspace") : router.replace(mode === "reviewing" ? "/reviewing" : "/coding")}
      renderDoris={(workspace, onSaved, onDone) => <DorisPanel
        workspace={workspace}
        api={api}
        identity={identity}
        request={requester}
        onSaved={onSaved}
        onDone={onDone}
      />}
      renderMedia={(attachmentPath) => <AttachmentMedia identity={identity} attachmentPath={attachmentPath} />}
    />;
  }

  if ((mode === "coding" || mode === "reviewing") && api) return <QueueScreen
    api={api}
    mode={mode}
    onExit={() => router.replace("/workspace")}
    onOpen={(identity) => router.push({ pathname: "/workspace", params: { vaSid: identity.vaSid, mode: identity.mode } })}
  />;

  async function openView() {
    const candidate = viewVaSid.trim();
    if (!candidate || candidate.length > 128) return;
    router.push({ pathname: "/workspace", params: { vaSid: candidate, mode: "view" } });
  }

  return <WebShell title={t("workspaceTitle")}>
    <Text style={styles.text}>{t("loginSuccess")}: {activeBootstrap.user.name}</Text>
    {activeBootstrap.capabilities.intake ? <Button label={t("navCollection")} onPress={() => router.push("/collection")} /> : null}
    {activeBootstrap.capabilities.registerDeath ? <Button label={t("registerDeath")} onPress={() => router.push("/death-registration")} /> : null}
    {activeBootstrap.capabilities.registeredDeaths ? <Button label={t("myRegisteredDeaths")} onPress={() => router.push({ pathname: "/death-registration", params: { view: "mine" } })} /> : null}
    {activeBootstrap.access.roles.some((role) => role === "coder" || role === "coding_tester") ? <Button label={t("navCoding")} onPress={() => router.push("/coding")} /> : null}
    {activeBootstrap.access.roles.includes("reviewer") ? <Button label={t("navReview")} onPress={() => router.push("/reviewing")} /> : null}
    {!activeBootstrap.capabilities.intake && !activeBootstrap.access.roles.some((role) => ["coder", "coding_tester", "reviewer"].includes(role)) ? <Text style={styles.muted}>{t("codingReviewPending")}</Text> : null}
    <View style={styles.card}>
      <Text style={styles.headline}>{t("viewCase")}</Text>
      <TextInput
        accessibilityLabel={t("caseIdentifier")}
        placeholder={t("caseIdentifier")}
        value={viewVaSid}
        onChangeText={setViewVaSid}
        maxLength={128}
        autoCapitalize="none"
      />
      <Button label={t("viewCase")} disabled={!viewVaSid.trim() || viewVaSid.trim().length > 128} onPress={() => void openView()} />
    </View>
    {logout ? <Button kind="danger" label={t("signOut")} onPress={() => void logout()} /> : null}
    {sessionError ? <Text role="alert" style={styles.error}>{sessionError}</Text> : null}
  </WebShell>;
}

export function CodingScreen() {
  return <WorkspaceScreen forcedMode="coding" />;
}

export function ReviewingScreen() {
  return <WorkspaceScreen forcedMode="reviewing" />;
}

export default WorkspaceScreen;
