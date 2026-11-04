import { Text, View } from "react-native";

import type { AreaProject } from "../../area/api";
import { t } from "../../i18n";
import { fontSize, radius, spacing, typography, useTheme } from "../../theme";
import { Button } from "../../ui";
import { StatPressable } from "./controls";
import { Freshness, Medians, StageLine } from "./OverviewTab";
import { hasDeathRegister } from "./pipeline";
import { sumCounts, type ProjectLoad } from "./view";

/**
 * One card per project the user can see: its stage counts, the two overdue counts (warning text when above zero) and
 * freshness. A card opens that project's Overview. *loads* holds each project's top level as it arrives: a card shows
 * its name while loading and an error line with Retry if its summary failed, so one slow project blocks no other.
 */
export function ProjectsTab({ projects, loads, onOpen, onRetry }: {
  projects: AreaProject[];
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
        const counts = summary ? sumCounts([summary.card.counts]) : null;
        const thresholds = summary?.thresholds;
        const overdue = counts && thresholds ? [
          t("statsOverdueInterviews", { count: counts.overdue_interview, days: thresholds.interview_days }),
          t("statsOverdueCodings", { count: counts.overdue_coding, days: thresholds.coding_days }),
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
                <StageLine counts={counts} showReported={hasDeathRegister([summary.card.counts, ...summary.rows.map((row) => row.counts)])} />
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
