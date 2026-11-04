import { Text, View } from "react-native";

import type { AreaProject, StageCountsReply } from "../../area/api";
import { t } from "../../i18n";
import { fontSize, radius, spacing, typography, useTheme } from "../../theme";
import { Button } from "../../ui";
import { StatPressable } from "./controls";
import { Freshness, Medians, StageLine } from "./OverviewTab";
import { countKey } from "./pipeline";
import { projectStages, type ProjectLoad } from "./view";

/**
 * One card per project the user can see: its stage counts and the two overdue counts (warning text when above zero),
 * from *stages* (one stage-counts request for every project, the case tabs' totals), then medians and freshness from
 * its summary. A card opens that project's Overview. *loads* holds each project's top level as it arrives: a card shows
 * its name while loading and an error line with Retry if its summary failed, so one slow project blocks no other.
 */
export function ProjectsTab({ projects, stages, loads, onOpen, onRetry }: {
  projects: AreaProject[];
  stages: StageCountsReply | null;
  loads: Record<string, ProjectLoad | undefined>;
  onOpen: (projectId: string) => void;
  onRetry: (projectId: string) => void;
}) {
  const { ui } = useTheme();
  return (
    <View style={{ gap: spacing.sm }}>
      {projects.map((project) => {
        const load = loads[project.project_id];
        const summary = load?.summary ?? null;
        const cardStyle = { padding: spacing.md, gap: spacing.xs, borderWidth: 1, borderColor: ui.border, borderRadius: radius.md, backgroundColor: ui.background } as const;
        if (!summary && load?.error) {
          return (
            <View key={project.project_id} style={cardStyle}>
              <Text style={{ ...typography.headline, color: ui.foreground }}>{project.project_name}</Text>
              <Text accessibilityRole="alert" style={{ ...typography.subhead, color: ui.destructiveText }}>{`${t("statsLoadFailed")}\n${load.error}`}</Text>
              <Button label={t("statsRetry")} kind="secondary" size="sm" onPress={() => onRetry(project.project_id)} style={{ alignSelf: "flex-start" }} />
            </View>
          );
        }
        const counts = summary && stages ? projectStages(stages, project.project_id) : null;
        const thresholds = stages?.thresholds;
        const overdue = counts && thresholds ? [
          t(countKey("statsOverdueInterviews", counts.overdue_interview), { count: counts.overdue_interview, days: thresholds.interview_days }),
          t(countKey("statsOverdueCodings", counts.overdue_coding), { count: counts.overdue_coding, days: thresholds.coding_days }),
        ].map((text, index) => ({ text, warn: (index === 0 ? counts.overdue_interview : counts.overdue_coding) > 0 })) : [];
        return (
          <StatPressable
            key={project.project_id}
            label={t("statsProjectCardOpen", { name: project.project_name })}
            onPress={() => onOpen(project.project_id)}
            style={cardStyle}
          >
            <Text style={{ ...typography.headline, color: ui.foreground }}>{project.project_name}</Text>
            {summary && counts ? (
              <>
                <StageLine counts={counts} />
                {overdue.map((line) => (
                  <Text key={line.text} style={{ fontSize: fontSize.body, color: line.warn ? ui.warningText : ui.mutedForeground }}>{line.text}</Text>
                ))}
                <Medians summary={summary} fallback={false} />
                <Freshness freshness={summary.freshness} />
              </>
            ) : <Text style={{ ...typography.subhead, color: ui.mutedForeground }}>{t("loading")}</Text>}
          </StatPressable>
        );
      })}
    </View>
  );
}
