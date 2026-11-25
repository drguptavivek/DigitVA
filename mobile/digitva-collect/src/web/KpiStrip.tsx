import { useEffect, useState } from "react";
import { StyleSheet, Text, View, type TextStyle } from "react-native";

import type { ClientCsrf } from "../api";
import { getHomeKpis, type ProjectKpi } from "../kpis/api";
import { t } from "../i18n";
import { useTheme } from "../theme";
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

/** The row read aloud as one sentence, the same words the old one-line layout showed. */
function rowLabel(counts: ProjectKpi): string {
  const line = [
    t("kpiDeathsCount", { count: counts.deaths_reported }),
    t("kpiInterviewsCount", { count: counts.interviews_done }) + percent(counts.interviews_pct),
    t("kpiCodedCount", { count: counts.coded }) + percent(counts.coded_pct),
  ].join(" · ");
  return `${counts.project_name}: ${line}`;
}

/** A right-aligned count with its percentage (when the server sent one) as muted text below. */
function Count({
  value,
  pct,
  countStyle,
  mutedStyle,
}: {
  value: number;
  pct: number | null;
  countStyle: TextStyle;
  mutedStyle: TextStyle;
}) {
  return (
    <View style={{ flex: 1, alignItems: "flex-end" }}>
      <Text style={[countStyle, { fontVariant: ["tabular-nums"] }]}>{value}</Text>
      {pct === null ? null : <Text style={mutedStyle}>{`${pct}%`}</Text>}
    </View>
  );
}

/**
 * Project progress as a table: per project in the user's area, its name on its own line (long names stay readable on
 * a phone) over Deaths reported, Interviews done and Coded in three aligned columns. Never summed across projects. Hidden when the
 * list is empty or the call fails: the page never waits on it.
 */
export function KpiStrip({ csrf }: { csrf: ClientCsrf }) {
  const styles = useUiStyles();
  const { ui } = useTheme();
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

  const columns = { flexDirection: "row" as const, gap: 8 };
  const divider = {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: ui.border,
    paddingVertical: 8,
    gap: 2,
  };
  return (
    <View>
      <View
        style={[columns, { paddingBottom: 6 }]}
        importantForAccessibility="no-hide-descendants"
        accessibilityElementsHidden
      >
        {(["kpiColDeaths", "kpiColInterviews", "kpiColCoded"] as const).map((key) => (
          <Text key={key} style={[styles.muted, { flex: 1, textAlign: "right" }]}>
            {t(key)}
          </Text>
        ))}
      </View>
      {projects.map((project) => (
        <View key={project.project_id} accessible accessibilityLabel={rowLabel(project)} style={divider}>
          <Text style={[styles.text, { fontWeight: "600" }]} numberOfLines={2}>
            {project.project_name}
          </Text>
          <View style={columns}>
            <Count value={project.deaths_reported} pct={null} countStyle={styles.text} mutedStyle={styles.muted} />
            <Count
              value={project.interviews_done}
              pct={project.interviews_pct}
              countStyle={styles.text}
              mutedStyle={styles.muted}
            />
            <Count value={project.coded} pct={project.coded_pct} countStyle={styles.text} mutedStyle={styles.muted} />
          </View>
        </View>
      ))}
    </View>
  );
}
