import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { Pressable, Text, TextInput, View, useWindowDimensions } from "react-native";

import type { AccessProject, HomeBlocks, HomeSummary } from "../api";
import { useAppState } from "../AppState";
import { loadBrowserSession } from "../client/session";
import { t } from "../i18n";
import { controls, spacing, typography } from "../theme";
import { Button, useUiStyles } from "../ui";
import { createWorkspaceApi, type JsonRequester, type WorkspaceApi } from "../workspace/api";
import { CaseWorkspaceScreen } from "../workspace/CaseWorkspaceScreen";
import { QueueScreen } from "../workspace/QueueScreen";
import { hasQueueParams, ownsQueueParams, parseQueueParams, serializeQueueParams } from "../workspace/viewState";
import { createWebWorkspaceTransport } from "../workspace/transport.web";
import type { WorkspaceIdentity, WorkspaceMode } from "../workspace/contracts";
import { DorisPanel } from "../workspace/doris/DorisPanel";
import { AttachmentMedia } from "../workspace/media/AttachmentMedia.web";
import { browserErrorText, LoginLanding, WebShell } from "./common";
import { Chevron, FoldButton } from "./Chevron";
import { ContextualHelpBanner } from "./ContextualHelp";
import { KpiStrip } from "./KpiStrip";
import { hasAnyRoleOrProject, openServerPage } from "./roleHome";

type RouteParams = { vaSid?: string | string[]; mode?: string | string[]; section?: string | string[]; project?: string | string[]; tab?: string | string[]; offset?: string | string[] };
type SessionCheck = { key: string; bootstrap: NonNullable<ReturnType<typeof useAppState>["bootstrap"]> };

const HOME_API = "/api/v1/me/home";
/** More projects than this in one role: the block names their count, not each project. */
export const MANY_PROJECTS = 3;
/** Width from which Home lays its role blocks out in two columns and in full. */
const WIDE_MIN_WIDTH = 768;
/** Grant roles whose projects a block's subline names. */
const BLOCK_GRANT_ROLES: Record<keyof HomeBlocks, string[]> = {
  death_reporter: ["death_reporter"],
  interviewer: ["interviewer"],
  interview_supervisor: ["interview_supervisor"],
  coder: ["coder", "coding_tester"],
  reviewer: ["reviewer"],
  data_manager: ["data_manager"],
  progress: ["project_pi", "site_pi", "collaborator", "collaborator_pii"],
};

type HomeMetric = { label: string; value: number };
/** One role's Home block: at most three numbers, the actionable backlog first, and one primary action. */
type RoleBlock = { key: keyof HomeBlocks; title: string; metrics: HomeMetric[]; backlog: number; cta: string; onPress: () => void };

/** The projects where *roles* hold an active grant: their names, or their count above MANY_PROJECTS. */
export function projectSubline(projects: AccessProject[], roles: string[]): string {
  const names = projects
    .filter((project) => (project.grants ?? []).some((grant) => grant.active && roles.includes(grant.role)))
    .map((project) => project.project_name);
  return names.length > MANY_PROJECTS ? t("homeProjectsCount", { count: names.length }) : names.join(" · ");
}

/** Work blocks for the roles held, most actionable backlog first (stable for ties). Progress is not one of them. */
export function roleBlocks(blocks: HomeBlocks, go: (key: keyof HomeBlocks) => void): RoleBlock[] {
  const list: RoleBlock[] = [];
  const { death_reporter: reporter, interviewer, interview_supervisor: supervisor, coder, reviewer, data_manager: dm } = blocks;
  if (interviewer) list.push({
    key: "interviewer",
    title: t("homeBlockInterviewer"),
    metrics: [
      { label: t("homeDraftsInProgress"), value: interviewer.drafts_in_progress },
      { label: t("homeMetricNeedingVisit"), value: interviewer.needing_visit },
    ],
    backlog: interviewer.drafts_in_progress + interviewer.needing_visit,
    cta: t(interviewer.drafts_in_progress > 0 ? "homeCtaResumeDraft" : "homeCtaStartInterview"),
    onPress: () => go("interviewer"),
  });
  if (supervisor) list.push({
    key: "interview_supervisor",
    title: t("homeBlockSupervisor"),
    metrics: [
      { label: t("homeMetricNeedsDecision"), value: supervisor.needs_decision },
      { label: t("homeMetricFlagged"), value: supervisor.flagged },
      { label: t("homeMetricOpenCases"), value: supervisor.open },
      { label: t("homeMetricSubmitted"), value: supervisor.submitted },
    ],
    backlog: supervisor.needs_decision,
    cta: t("homeCtaNeedsDecision"),
    onPress: () => go("interview_supervisor"),
  });
  if (coder) list.push(coder.practice ? {
    key: "coder",
    title: t("homeBlockPracticeCoding"),
    metrics: [{ label: t("homeMetricReadyForPractice"), value: coder.ready }],
    // Practice is never a backlog.
    backlog: 0,
    cta: t("homeCtaPracticeNext"),
    onPress: () => go("coder"),
  } : {
    key: "coder",
    title: t("homeBlockCoder"),
    metrics: [
      { label: t("homeMetricReadyForMe"), value: coder.ready },
      { label: t("homeMetricCompleted"), value: coder.completed ?? 0 },
      { label: t("homeMetricRecodeable"), value: coder.recodeable ?? 0 },
    ],
    backlog: coder.ready,
    cta: t("homeCtaCodeNext"),
    onPress: () => go("coder"),
  });
  if (reviewer) list.push({
    key: "reviewer",
    title: t("homeBlockReviewer"),
    metrics: [
      { label: t("homeMetricReadyToReview"), value: reviewer.available },
      { label: t("homeMetricCompleted"), value: reviewer.completed },
    ],
    backlog: reviewer.available,
    cta: t("homeCtaReviewNext"),
    onPress: () => go("reviewer"),
  });
  if (dm) list.push({
    key: "data_manager",
    title: t("homeBlockDataManager"),
    metrics: [
      { label: t("homeMetricScreeningPending"), value: dm.screening_pending },
      { label: t("homeMetricReadyForCoding"), value: dm.ready_for_coding },
      { label: t("homeMetricNotCodeable"), value: dm.not_codeable },
    ],
    backlog: dm.screening_pending,
    cta: t("homeCtaDataManagement"),
    onPress: () => go("data_manager"),
  });
  if (reporter) list.push({
    key: "death_reporter",
    title: t("homeBlockDeathReporter"),
    metrics: [
      { label: t("homeMetricDeathsIRegistered"), value: reporter.registered },
      { label: t("homeMetricAwaitingInterview"), value: reporter.awaiting_interview },
    ],
    // Awaiting interview is someone else's work: a reporter's next step is always the next death.
    backlog: 0,
    cta: t("registerDeath"),
    onPress: () => go("death_reporter"),
  });
  return list.sort((a, b) => b.backlog - a.backlog);
}

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
  const { bootstrap, loginUrl, reload } = useAppState();
  const styles = useUiStyles();
  const [sessionCheck, setSessionCheck] = useState<SessionCheck>();
  const [sessionError, setSessionError] = useState("");
  const [viewVaSid, setViewVaSid] = useState("");
  // undefined while loading, null when the call failed.
  const [home, setHome] = useState<HomeSummary | null>();
  const [progressOpen, setProgressOpen] = useState(false);
  const [caseLookupOpen, setCaseLookupOpen] = useState(false);
  const wide = useWindowDimensions().width >= WIDE_MIN_WIDTH;
  const requestGeneration = useRef(0);
  const userId = bootstrap?.user.user_id;
  const checkKey = `${userId ?? ""}:${mode}`;

  // Queue params belong to the queue routes only; drop any that a case URL inherited.
  const caseWithQueueParams = Boolean(vaSid) && mode !== "home" && hasQueueParams(params);
  const section = first(params.section);
  useEffect(() => {
    // replace, not setParams: setParams keeps keys it is not given a value for.
    if (caseWithQueueParams) router.replace({ pathname: "/workspace", params: { vaSid, mode, ...(section ? { section } : {}) } });
  }, [caseWithQueueParams, router, vaSid, mode, section]);

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

  useEffect(() => {
    if (mode !== "home" || !requester) return;
    let mounted = true;
    setHome(undefined);
    void requester(HOME_API)
      .then((summary) => {
        if (mounted) setHome(summary as HomeSummary);
      })
      .catch(() => {
        if (mounted) setHome(null);
      });
    return () => {
      mounted = false;
    };
  }, [mode, requester]);

  if (loginUrl && !bootstrap) return <LoginLanding />;
  if (!activeBootstrap) return <WebShell title={t("workspaceTitle")}>
    {sessionError ? <Text role="alert" style={styles.error}>{sessionError}</Text> : <Text style={styles.muted}>{t("loading")}</Text>}
  </WebShell>;

  const roles = activeBootstrap.access?.roles ?? [];
  const projects = activeBootstrap.access?.projects ?? [];
  const isAdmin = Boolean(activeBootstrap.access?.is_admin);

  if (mode !== "home" && !hasWorkspaceRole(roles, mode)) {
    return <WebShell title={t("workspaceTitle")}>
      <ContextualHelpBanner screen={mode === "reviewing" ? "reviewing" : "coding"} />
      <View style={styles.card}>
        <Text role="alert" style={styles.error}>{t("serverForbidden")}</Text>
        <Text style={styles.muted}>{t("codingReviewPending")}</Text>
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.xs }}>
          <Button kind="secondary" size="sm" label={t("home")} onPress={() => router.replace("/workspace")} />
          <Button
            kind="secondary"
            size="sm"
            label={t("homeOpenHelp")}
            onPress={() => openServerPage(activeBootstrap.user.user_id, "/help/coding-workflow")}
          />
          {activeBootstrap.access?.demo_coding?.available ? (
            <Button
              size="sm"
              label={t("homePracticeDemoCoding")}
              onPress={() => openServerPage(activeBootstrap.user.user_id, "/help/demo-coding")}
            />
          ) : null}
        </View>
      </View>
    </WebShell>;
  }

  if (vaSid && mode !== "home" && api && requester) {
    const identity: WorkspaceIdentity = { vaSid, mode };
    return <CaseWorkspaceScreen
      identity={identity}
      api={api}
      section={first(params.section)}
      onSectionChange={(code) => router.setParams({ section: code })}
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
    Shell={WebShell}
    initialView={parseQueueParams(params)}
    onViewChange={(view) => { if (ownsQueueParams(window.location.search)) router.setParams(serializeQueueParams(view)); }}
    onOpen={(identity) => router.push({ pathname: "/workspace", params: { vaSid: identity.vaSid, mode: identity.mode } })}
  />;

  async function openView() {
    const candidate = viewVaSid.trim();
    if (!candidate || candidate.length > 128) return;
    router.push({ pathname: "/workspace", params: { vaSid: candidate, mode: "view" } });
  }

  function go(key: keyof HomeBlocks) {
    if (!activeBootstrap) return;
    if (key === "data_manager") openServerPage(activeBootstrap.user.user_id, "/data-management/");
    else if (key === "progress") openServerPage(activeBootstrap.user.user_id, "/area/");
    else if (key === "interviewer") router.push("/collection");
    else if (key === "interview_supervisor") router.push({ pathname: "/death-registration", params: { view: "mine", preset: "supervision" } });
    else if (key === "coder") router.push("/coding");
    else if (key === "reviewer") router.push("/reviewing");
    else router.push("/death-registration");
  }

  const hasRolesOrProjects = hasAnyRoleOrProject(activeBootstrap);
  // Pages neither a role block nor the sidebar (web/common.tsx NavigationMenu) offers.
  const quickActionItems: Array<{ key: string; label: string; onPress: () => void }> = [];
  if (
    !roles.includes("data_manager") &&
    (roles.includes("project_pi") || roles.includes("collaborator") || roles.includes("collaborator_pii"))
  ) {
    quickActionItems.push({
      key: "dataManagement",
      label: t("navDataManagement"),
      onPress: () => openServerPage(activeBootstrap.user.user_id, "/data-management/"),
    });
  }
  if (roles.includes("site_pi")) {
    quickActionItems.push({
      key: "sitePi",
      label: t("homeSitePiDashboard"),
      onPress: () => openServerPage(activeBootstrap.user.user_id, "/sitepi/"),
    });
  }
  if (isAdmin || roles.includes("admin")) {
    quickActionItems.push({
      key: "admin",
      label: t("homeAdminConsole"),
      onPress: () => openServerPage(activeBootstrap.user.user_id, "/admin/"),
    });
  }
  const sidebarHasMentoring = Boolean(
    activeBootstrap.capabilities?.mentoring ||
    activeBootstrap.access?.account?.mentor?.member ||
    (activeBootstrap.access?.account?.mentor?.admin_of?.length ?? 0) > 0,
  );
  if (isAdmin && !sidebarHasMentoring) {
    quickActionItems.push({ key: "mentoring", label: t("navMentoring"), onPress: () => router.push("/mentoring") });
  }
  if (projects.length > 0 || isAdmin) {
    quickActionItems.push({
      key: "peopleAndRoles",
      label: t("homePeopleAndRoles"),
      onPress: () => openServerPage(activeBootstrap.user.user_id, "/people-roles"),
    });
  }
  const showPendingNotice =
    !activeBootstrap.capabilities?.intake &&
    !roles.some((role) => ["coder", "coding_tester", "reviewer"].includes(role));
  const canViewCase =
    isAdmin ||
    roles.some((role) =>
      [
        "coder",
        "coding_tester",
        "reviewer",
        "data_manager",
        "project_pi",
        "site_pi",
        "collaborator",
        "collaborator_pii",
      ].includes(role),
    );

  const blocks = home ? roleBlocks(home.blocks, go) : [];
  const progress = home?.blocks.progress;
  const row = { flexDirection: "row" as const, flexWrap: "wrap" as const, gap: spacing.xs, alignItems: "center" as const };
  const bigNumber = [styles.text, typography.largeTitle];

  function fullBlock(block: RoleBlock) {
    const subline = projectSubline(projects, BLOCK_GRANT_ROLES[block.key]);
    return (
      <View key={block.key} style={[styles.card, wide ? { flexGrow: 1, flexBasis: "45%" as const, minWidth: 280 } : null]}>
        <Text style={styles.headline}>{block.title}</Text>
        {subline ? <Text style={styles.muted} numberOfLines={1}>{subline}</Text> : null}
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.md }}>
          {block.metrics.map((metric) => (
            <View key={metric.label} style={{ minWidth: 96, flexShrink: 1 }}>
              <Text style={bigNumber}>{metric.value}</Text>
              <Text style={styles.muted}>{metric.label}</Text>
            </View>
          ))}
        </View>
        <View style={row}>
          <Button size="sm" label={block.cta} onPress={block.onPress} />
        </View>
      </View>
    );
  }

  /** Phone: every block after the first is one line, its first number, opening the block's action. */
  function compactBlock(block: RoleBlock) {
    const lead = block.metrics[0];
    return (
      <Pressable
        key={block.key}
        accessibilityRole="button"
        accessibilityLabel={`${block.title}: ${lead.value} ${lead.label}. ${block.cta}`}
        onPress={block.onPress}
        style={[styles.card, { flexDirection: "row", alignItems: "center", gap: spacing.xs }]}
      >
        <Text style={[styles.text, { flex: 1 }]} numberOfLines={1}>{block.title}</Text>
        <Text style={styles.headline}>{lead.value}</Text>
        <Text style={styles.muted} numberOfLines={1}>{lead.label} ›</Text>
      </Pressable>
    );
  }

  return <WebShell title={t("workspaceTitle")}>
    <ContextualHelpBanner screen="home" />
    <Text style={styles.headline}>{t("homeWelcomeTitle", { name: activeBootstrap.user.name })}</Text>

    {!hasRolesOrProjects ? (
      <View style={styles.card}>
        <Text style={styles.headline}>{t("homeNoRolesTitle")}</Text>
        <Text style={styles.text}>{t("homeNoRolesDescription")}</Text>
        <Text style={styles.muted}>{t("codingReviewPending")}</Text>
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.xs }}>
          <Button size="sm" label={t("navSettings")} onPress={() => router.push("/settings")} />
          <Button
            kind="secondary"
            size="sm"
            label={t("homeOpenHelp")}
            onPress={() => openServerPage(activeBootstrap.user.user_id, "/help")}
          />
          {activeBootstrap.access?.demo_coding?.available ? (
            <Button
              kind="secondary"
              size="sm"
              label={t("homePracticeDemoCoding")}
              onPress={() => router.push("/coding")}
            />
          ) : null}
        </View>
      </View>
    ) : (
      <>
        {home === undefined ? <Text style={styles.muted}>{t("loading")}</Text> : null}
        {home === null ? <Text style={styles.muted}>{t("homeCountsUnavailable")}</Text> : null}
        {blocks.length > 0 ? (
          <View style={wide ? { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm } : { gap: spacing.xs }}>
            {blocks.map((block, index) => (wide || index === 0 ? fullBlock(block) : compactBlock(block)))}
          </View>
        ) : null}

        {progress ? (
          <View style={styles.card}>
            <FoldButton
              label={t(progressOpen ? "homeHideProgress" : "homeShowProgress")}
              expanded={progressOpen}
              onPress={() => setProgressOpen((open) => !open)}
              style={{ flexDirection: "row", alignItems: "center", gap: spacing.xs, minHeight: controls.minTouchTarget }}
            >
              <Text style={styles.text}>{t("homeBlockProgress")}</Text>
              <Text style={[styles.muted, { flexShrink: 1 }]} numberOfLines={1}>{projectSubline(projects, BLOCK_GRANT_ROLES.progress)}</Text>
              <Chevron expanded={progressOpen} />
            </FoldButton>
            {progressOpen ? (
              <>
                <KpiStrip csrf={activeBootstrap.csrf} />
                <View style={row}>
                  <Button kind="secondary" size="sm" label={t("navStatistics")} onPress={() => go("progress")} />
                </View>
              </>
            ) : null}
          </View>
        ) : null}

        {quickActionItems.length > 0 || showPendingNotice || canViewCase ? (
          <View style={{ gap: spacing.xs }}>
            {quickActionItems.length > 0 || (canViewCase && !caseLookupOpen) ? (
              <View style={row}>
                {quickActionItems.map((item) => (
                  <Button key={item.key} variant="ghost" size="sm" label={item.label} onPress={item.onPress} />
                ))}
                {canViewCase && !caseLookupOpen ? (
                  <Button variant="ghost" size="sm" label={t("homeOpenCaseById")} onPress={() => setCaseLookupOpen(true)} />
                ) : null}
              </View>
            ) : null}
            {canViewCase && caseLookupOpen ? (
              <View style={row}>
                <TextInput
                  accessibilityLabel={t("caseIdentifier")}
                  placeholder={t("caseIdentifier")}
                  style={[styles.input, { flexGrow: 1, flexBasis: 200 }]}
                  value={viewVaSid}
                  onChangeText={setViewVaSid}
                  maxLength={128}
                  autoCapitalize="none"
                  autoFocus
                />
                <Button
                  size="sm"
                  label={t("viewCase")}
                  disabled={!viewVaSid.trim() || viewVaSid.trim().length > 128}
                  onPress={() => void openView()}
                />
              </View>
            ) : null}
            {showPendingNotice ? (
              <Text style={styles.muted}>{t("codingReviewPending")}</Text>
            ) : null}
          </View>
        ) : null}
      </>
    )}

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
