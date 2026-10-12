import { useEffect, useState } from "react";
import { Text, View } from "react-native";

import type { ClientCsrf } from "../api";
import { getHomeKpis, type ProjectKpi } from "../kpis/api";
import { t } from "../i18n";
import { useUiStyles } from "../ui";
import { createWebWorkspaceTransport } from "../workspace/transport.web";

/** Shown where a percentage has no deaths reported to divide by. */
const NO_VALUE = "—";

/** Pages that show the strip: the home and the five role screens. Exact paths, so case and form pages beneath them do not. */
export const KPI_SCREENS = ["/", "/workspace", "/coding", "/reviewing", "/collection", "/death-registration", "/supervision"];

/** Space held while the call runs, about one project line, so the page below does not jump when the counts arrive. */
const LOADING_MIN_HEIGHT = 56;

function percent(value: number | null): string {
  return value === null ? NO_VALUE : `${value}%`;
}

/** Compact counts above a signed-in page, one line per project. Hidden when the list is empty or the call fails: the page never waits on it. */
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
    <View style={styles.card}>
      {projects.map((project) => (
        <View key={project.project_id}>
          {showName ? <Text style={styles.text}>{project.project_name}</Text> : null}
          <Text style={styles.muted}>
            {t("kpiLine", {
              deaths: project.deaths_reported,
              interviews: project.interviews_done,
              interviewsPct: percent(project.interviews_pct),
              coded: project.coded,
              codedPct: percent(project.coded_pct),
            })}
          </Text>
        </View>
      ))}
    </View>
  );
}
