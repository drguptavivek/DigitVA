import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Text, View } from "react-native";

import { useAppState } from "../AppState";
import { DEFAULT_PERIOD, type AreaProject, type AreaSummary, type StageCountsReply } from "../area/api";
import { ClientApiError } from "../client/api";
import { dataRouteForLink } from "../data/query";
import { t } from "../i18n";
import { spacing, typography, useTheme } from "../theme";
import type { JsonRequester } from "../workspace/api";
import { createWebWorkspaceTransport } from "../workspace/transport.web";
import { Button } from "../ui";
import { browserErrorText, WebShell } from "./common";
import { caseViewPath, dataAccess, openServerPage } from "./roleHome";
import { CaseTableTab } from "./stats/CaseTableTab";
import { FilterBar, type FilterSelect } from "./stats/FilterBar";
import { OverviewTab } from "./stats/OverviewTab";
import { ProjectsTab } from "./stats/ProjectsTab";
import { casesEntry, followStats, peekStats, prefetchStats, readStats, projectsEntry, setStatsScope, stageCountsEntry, summaryEntry, type StatsEntry } from "./stats/cache";
import { soleOpenUnit } from "./stats/pipeline";
import {
  areaOptions, casesQuery, isCaseTab, loadCounts, loadedSummaries, MAX_SUMMARY_REQUESTS, parseView, projectsInView, runLimited, stageCountsQuery, viewParams, withTab,
  type CaseTab, type ProjectLoad, type Source, type StatsView,
} from "./stats/view";

/** Height held while the first summary loads, so the page does not jump. */
const LOADING_MIN_HEIGHT = 240;
/** Every query key `viewParams` may write, unset: a view change replaces the whole query. */
const CLEARED_VIEW = { tab: undefined, project: undefined, period: undefined, unit: undefined, site: undefined, status: undefined, overdue: undefined, source: undefined };

type RawParams = Partial<Record<"tab" | "project" | "period" | "unit" | "site" | "status" | "overdue" | "source", string | string[]>>;

/**
 * Statistics: operational dashboards over /api/v1/area/* (counts) and /api/v1/cases (read-only case tables). The view
 * is the URL (src/web/stats/view.ts): every choice pushes a history entry, so reload and Back restore it. The URL is
 * untrusted: parseView checks it against the server's project list and the server scopes every number and row anyway.
 * The screen loads the projects, one stage-counts request for the projects in view (every project on the Projects
 * tab: the stage and overdue numbers, each a case tab's total) and one summary per project (the area detail: medians,
 * causes, stations, staff, freshness, CSV), then hands them to the tab. Every read goes through the in-memory cache
 * (src/web/stats/cache.ts), and once the visible tab has loaded the first page of the other tabs is prefetched, so
 * switching tabs within a minute shows data at once.
 */
export default function StatisticsScreen() {
  const { bootstrap } = useAppState();
  const { ui } = useTheme();
  // Cached replies belong to one user and access; signing out or a changed grant drops them (before any read below).
  const scope = bootstrap ? JSON.stringify([bootstrap.user.user_id, bootstrap.access, bootstrap.capabilities, bootstrap.scope]) : "";
  setStatsScope(scope);
  const request: JsonRequester | undefined = useMemo(
    () => (bootstrap ? createWebWorkspaceTransport(bootstrap.csrf) : undefined),
    [bootstrap],
  );
  const router = useRouter();
  const params = useLocalSearchParams<RawParams>();
  // A remount (each tab switch pushes a history entry) starts from the cached list, so the page does not flash Loading.
  const [projects, setProjects] = useState<AreaProject[] | null>(() => (request ? peekStats(projectsEntry(request)) ?? null : null));
  const [loaded, setLoaded] = useState<{ key: string; byId: Record<string, ProjectLoad> } | null>(null);
  const [error, setError] = useState("");
  const [soleRoot, setSoleRoot] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [stages, setStages] = useState<{ key: string; reply: StageCountsReply } | null>(null);

  const view = useMemo(() => (projects ? parseView(params, projects) : null), [projects, params]);
  const inView = useMemo(() => (view && projects ? projectsInView(view, projects) : []), [view, projects]);
  const sole = inView.length === 1 ? inView[0] : null;
  const onProjectsTab = view?.tab === "projects";
  // The Projects tab shows every project at its top level; the other tabs the projects in view, at the area for one.
  const loadIds = onProjectsTab ? (projects ?? []).map((row) => row.project_id) : inView;
  const loadKey = loadIds.join(",");
  const unit = !onProjectsTab && sole ? view?.unit ?? null : null;
  const site = !onProjectsTab && sole ? view?.site ?? null : null;
  const period = view?.period;
  // The redirects below rewrite the current view; the summaries themselves depend only on projects, area and period.
  const viewRef = useRef(view);
  viewRef.current = view;
  // Re-requests the given projects of the current load (set by the effect below; stale ones are ignored by its guard).
  const retryRef = useRef<(ids: string[]) => void>(() => undefined);

  useEffect(() => {
    if (!request) return undefined;
    let active = true;
    setError("");
    followStats(projectsEntry(request), (rows) => {
      if (active) setProjects(rows);
    }, (caught) => {
      if (active) setError(browserErrorText(caught));
    });
    return () => {
      active = false;
    };
  }, [request, retry]);

  // One request for every project in view (Overview and Projects only); numbers of another key are never shown.
  const stagesWanted = view ? !isCaseTab(view.tab) : false;
  const stagesKey = JSON.stringify([loadKey, unit, site, period]);
  const stagesSource = useMemo(
    () => (request && loadKey && period ? stageCountsEntry(request, stageCountsQuery(loadKey.split(","), { unit, site }, period, new Date())) : null),
    [request, loadKey, unit, site, period],
  );
  useEffect(() => {
    if (!stagesSource || !stagesWanted) return undefined;
    let active = true;
    followStats(stagesSource, (reply) => {
      if (active) setStages({ key: stagesKey, reply });
    }, (caught) => {
      if (active) setError(browserErrorText(caught));
    });
    return () => {
      active = false;
    };
  }, [stagesSource, stagesKey, stagesWanted, retry]);

  /** Show *next* in place: push stacked a new Statistics screen per tab or filter change (every one kept mounted).
   * setParams keeps keys it is not given a value for, so every view key is cleared first. */
  const go = useCallback((next: StatsView) => router.setParams({ ...CLEARED_VIEW, ...viewParams(next) }), [router]);

  useEffect(() => {
    if (!request || !loadKey || !period) return undefined;
    let active = true;
    const ids = loadKey.split(",");
    const one = ids.length === 1 && !onProjectsTab;
    const readSummary = (project: string) => readStats(summaryEntry(request, { project, unit: one ? unit : null, site: one ? site : null, period }));
    // Each project's state lands on its own; a new project set starts empty, the same set keeps its numbers (dimmed).
    const patch = (id: string, next: Partial<ProjectLoad>) => setLoaded((prev) => {
      const base = prev && prev.key === loadKey ? prev.byId : {};
      return { key: loadKey, byId: { ...base, [id]: { ...(base[id] ?? { summary: null, error: "", fetching: false }), ...next } } };
    });
    const run = (todo: string[]) => {
      setError("");
      todo.forEach((id) => patch(id, { error: "", fetching: true }));
      void runLimited(todo, MAX_SUMMARY_REQUESTS, async (project) => {
        const landed = (reply: AreaSummary) => {
          if (!active) return;
          // A district-level user's one root opens at once, so the first level is the units below it.
          const first = one ? soleOpenUnit(reply, { unit, site }) : null;
          if (first) {
            // Its "All areas" choice would only reopen the same root, so the path starts at the root.
            setSoleRoot(first);
            patch(project, { fetching: false });
            if (viewRef.current) router.replace({ pathname: "/statistics", params: viewParams({ ...viewRef.current, unit: first, site: null }) });
            return;
          }
          if (one && !unit && !site) setSoleRoot(null);
          patch(project, { summary: reply, error: "", fetching: false });
        };
        // A cached summary shows at once; a stale one is refreshed behind it, and a failed refresh leaves it shown.
        const { cached, next } = readSummary(project);
        if (cached) landed(cached);
        if (!next) return;
        try {
          landed(await next);
        } catch (caught) {
          if (!active || cached) return;
          // A unit or site the server does not know (a stale link): back to the project's top level, not an error page.
          if (one && (unit || site) && caught instanceof ClientApiError && caught.status === 404) {
            patch(project, { fetching: false });
            if (viewRef.current) router.replace({ pathname: "/statistics", params: viewParams({ ...viewRef.current, unit: null, site: null }) });
            return;
          }
          const text = browserErrorText(caught);
          patch(project, { summary: null, error: text, fetching: false });
          // One project fails the whole page; several fail only their own card or the Overview's retry note.
          if (one) setError(text);
        }
      });
    };
    retryRef.current = run;
    run(ids);
    return () => {
      active = false;
    };
  }, [request, loadKey, onProjectsTab, unit, site, period, retry, router]);

  // After the visible tab's requests settle, the first page of every other tab for the same filters, one at a time.
  // A filter change cancels what has not started; a request under way is stored under its own filters' key only.
  const viewKey = JSON.stringify(view);
  useEffect(() => {
    const current = viewRef.current;
    if (!request || !current || !projects) return undefined;
    const now = new Date();
    const ids = projectsInView(current, projects);
    const all = projects.map((row) => row.project_id);
    const area = { unit: current.unit, site: current.site };
    const one = ids.length === 1;
    const caseTabs = (["deaths", "interviews", "codings"] as const).filter((tab) => tab !== current.tab);
    const list: StatsEntry<unknown>[] = [
      ...caseTabs.map((tab) => casesEntry(request, casesQuery({ ...withTab(current, tab), tab }, ids, now, null))),
      stageCountsEntry(request, stageCountsQuery(ids, area, current.period, now)),
      ...ids.map((project) => summaryEntry(request, { project, unit: one ? area.unit : null, site: one ? area.site : null, period: current.period })),
      stageCountsEntry(request, stageCountsQuery(all, { unit: null, site: null }, current.period, now)),
      ...all.map((project) => summaryEntry(request, { project, unit: null, site: null, period: current.period })),
    ];
    return prefetchStats(list);
    // viewKey stands for the view: its object is rebuilt on renders that change nothing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request, projects, viewKey, scope]);

  if (!bootstrap) return <WebShell title={t("statsTitle")}>{null}</WebShell>;

  const muted = { ...typography.subhead, color: ui.mutedForeground } as const;
  const failed = error ? (
    <View style={{ gap: spacing.xs }}>
      <Text accessibilityRole="alert" style={{ ...typography.subhead, color: ui.destructiveText }}>{`${t("statsLoadFailed")}\n${error}`}</Text>
      <Button label={t("statsRetry")} kind="secondary" size="sm" onPress={() => setRetry((count) => count + 1)} />
    </View>
  ) : null;

  if (projects && projects.length === 0 && !error) {
    return <WebShell title={t("statsTitle")}><Text style={muted}>{t("statsNoProjects")}</Text></WebShell>;
  }
  if (!projects || !view) return <WebShell title={t("statsTitle")}>{failed}<View style={{ minHeight: LOADING_MIN_HEIGHT }}><Text style={muted}>{t("loading")}</Text></View></WebShell>;

  // Numbers of another project set are never shown under this one's filters; the same set's stay (dimmed) while the area loads.
  // A remount or a switch to another project set starts from the cached summaries, so they show without a Loading line.
  const one = loadIds.length === 1 && !onProjectsTab;
  const byId = loaded && loaded.key === loadKey ? loaded.byId : request ? Object.fromEntries(loadIds.flatMap((id) => {
    const summary = peekStats(summaryEntry(request, { project: id, unit: one ? unit : null, site: one ? site : null, period: view.period }));
    return summary ? [[id, { summary, error: "", fetching: false }]] : [];
  })) as Record<string, ProjectLoad> : null;
  const summaries = loadedSummaries(loadIds, byId ?? {});
  const soleSummary = sole && !onProjectsTab && byId ? byId[sole]?.summary ?? null : null;
  const stageReply = stages && stages.key === stagesKey ? stages.reply : stagesWanted && stagesSource ? peekStats(stagesSource) ?? null : null;
  const busy = loadIds.some((id) => byId?.[id]?.fetching);
  // Several projects answer one by one; the Overview says how many are still out or failed.
  const { pending, failedIds } = loadIds.length > 1 ? loadCounts(loadIds, byId ?? {}) : { pending: 0, failedIds: [] as string[] };
  // A link to the retired Flask data page opens the Data screen with the same filters.
  const openLink = (url: string) => {
    const data = dataRouteForLink(url);
    if (data) router.push({ pathname: "/data", params: data });
    else openServerPage(bootstrap.user.user_id, url);
  };

  const access = dataAccess(bootstrap);
  const selects: FilterSelect[] = [];
  if (soleSummary) {
    const units = isCaseTab(view.tab) ? bootstrap.access?.projects.find((project) => project.project_id === sole)?.units : undefined;
    const options = areaOptions(soleSummary, soleRoot, units);
    selects.push({
      key: "area",
      label: t("statsArea"),
      options: options.map((option) => ({ value: option.value, label: option.kind === "all" ? t("statsAllAreas") : `${"  ".repeat(option.depth)}${option.name}` })),
      value: view.unit ?? view.site ?? "",
      onChange: (next) => {
        const kind = options.find((option) => option.value === next)?.kind ?? "all";
        go({ ...view, unit: kind === "unit" ? next : null, site: kind === "site" ? next : null });
      },
    });
  }
  if (view.tab === "deaths") {
    selects.push({
      key: "source",
      label: t("statsSource"),
      options: [{ value: "", label: t("statsSourceAll") }, { value: "reported", label: t("statsSourceReported") }, { value: "direct", label: t("statsSourceDirect") }],
      value: view.source ?? "",
      onChange: (next) => go({ ...view, source: (next || null) as Source | null }),
    });
  }
  if (isCaseTab(view.tab)) {
    selects.push({
      key: "overdue",
      label: t("statsOverdue"),
      options: [{ value: "", label: t("statsOverdueAll") }, { value: "1", label: t("statsOverdueOnly") }],
      value: view.overdue ? "1" : "",
      onChange: (next) => go({ ...view, overdue: next === "1" }),
    });
  }

  const caseView = isCaseTab(view.tab) ? (view as StatsView & { tab: CaseTab }) : null;
  return (
    <WebShell title={t("statsTitle")} wide={caseView !== null}>
      <FilterBar
        projects={projects}
        chosen={view.projects}
        onProjects={(next) => go({ ...view, projects: next, unit: null, site: null })}
        period={view.period}
        onPeriod={(next) => go({ ...view, period: next })}
        selects={selects}
        tab={view.tab}
        onTab={(next) => go(withTab(view, next))}
        onClearAll={() => go({ ...view, period: DEFAULT_PERIOD, unit: null, site: null, source: null, overdue: false })}
      />
      {failed}
      {request && caseView ? (
        <CaseTableTab
          view={caseView}
          projectIds={inView}
          request={request}
          causes={soleSummary?.card.causes ?? null}
          onStatus={(status) => go({ ...view, status })}
          onOpen={access.allowed ? (sid) => openServerPage(bootstrap.user.user_id, caseViewPath(access, sid)) : undefined}
        />
      ) : null}
      {request && view.tab === "overview" ? (
        summaries.length || stageReply || error || failedIds.length ? (
          <OverviewTab
            stages={stageReply}
            summaries={summaries}
            sole={soleSummary}
            unit={unit}
            site={site}
            soleRoot={soleRoot}
            busy={busy}
            pending={pending}
            failedCount={failedIds.length}
            onRetryFailed={() => retryRef.current(failedIds)}
            request={request}
            onDrill={(next) => go({ ...view, unit: next.unit ?? null, site: next.site ?? null })}
            onAttention={(tab) => go({ ...withTab(view, tab), overdue: true })}
            onOpenLink={openLink}
          />
        ) : <View style={{ minHeight: LOADING_MIN_HEIGHT }}><Text style={muted}>{t("loading")}</Text></View>
      ) : null}
      {view.tab === "projects" ? (
        <ProjectsTab
          projects={projects}
          stages={stageReply}
          loads={byId ?? {}}
          onRetry={(projectId) => retryRef.current([projectId])}
          onOpen={(projectId) => go({ ...withTab(view, "overview"), projects: [projectId], unit: null, site: null })}
        />
      ) : null}
    </WebShell>
  );
}
