import { useEffect, useState } from "react";
import { Text, View, type TextStyle } from "react-native";

import type { ClientCsrf } from "../api";
import { getHomeKpis, type ProjectKpi } from "../kpis/api";
import { t } from "../i18n";
import { useUiStyles } from "../ui";
import { createWebWorkspaceTransport } from "../workspace/transport.web";

/**
 * Pages whose shell mounts the strip: none. Home renders it inside its opened "Project progress" block
 * (WorkspaceScreen), so queue and role screens stay free of project-wide counts.
 */
export const KPI_SCREENS: string[] = [];

/** Space held while the call runs, about one project line, so the page below does not jump when the counts arrive. */
const LOADING_MIN_HEIGHT = 56;

/** " (n%)" after a count, or nothing when the server sent no percentage (its rule: a covering denominator of at least 20). */
function percent(value: number | null): string {
  return value === null ? "" : ` (${value}%)`;
}

/** One project's counts in *countStyle*, each percentage beside its count as muted secondary text (omitted when null). */
function KpiLine({ counts, countStyle, mutedStyle }: { counts: ProjectKpi; countStyle: TextStyle; mutedStyle: TextStyle }) {
  const interviewsPct = percent(counts.interviews_pct);
  const codedPct = percent(counts.coded_pct);
  return (
    <Text style={countStyle}>
      {t("kpiDeathsCount", { count: counts.deaths_reported })}
      {" · "}
      {t("kpiInterviewsCount", { count: counts.interviews_done })}
      {interviewsPct ? <Text style={mutedStyle}>{interviewsPct}</Text> : null}
      {" · "}
      {t("kpiCodedCount", { count: counts.coded })}
      {codedPct ? <Text style={mutedStyle}>{codedPct}</Text> : null}
    </Text>
  );
}

/**
 * Project progress, one line per project in the user's area (named when there are several). Never summed across
 * projects. Hidden when the list is empty or the call fails: the page never waits on it.
 */
export function KpiStrip({ csrf }: { csrf: ClientCsrf }) {
  const styles = useUiStyles();
  const [projects, setProjects] = useState<ProjectKpi[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    getHomeKpis(createWebWorkspaceTransport(csrf))
      .then((rows) => {
        if (active) setProjects(rows);
      })
      .catch(() => undefined)
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [csrf]);

  if (loading) return <View style={{ minHeight: LOADING_MIN_HEIGHT }} />;
  if (!projects.length) return null;

  const showName = projects.length > 1;
  return (
    <View style={{ gap: 4 }}>
      {projects.map((project) => (
        <View key={project.project_id}>
          {showName ? <Text style={styles.text}>{project.project_name}</Text> : null}
          <KpiLine counts={project} countStyle={styles.text} mutedStyle={styles.muted} />
        </View>
      ))}
    </View>
  );
}
