import { Text, View } from "react-native";

import type { AreaCauses } from "../../area/api";
import { t } from "../../i18n";
import { fontSize, radius, spacing, typography, useTheme } from "../../theme";
import { formatPercent } from "./pipeline";

/**
 * Top causes of death with simple share bars. Hidden (fewer than 20 coded) the server sends no rows, so say why
 * instead of drawing nothing. Shares are of all coded deaths; the percentage is written beside every bar.
 */
export function CausesList({ causes }: { causes: AreaCauses }) {
  const { ui } = useTheme();
  return (
    <View style={{ gap: spacing.xs }}>
      <Text accessibilityRole="header" style={{ ...typography.headline, color: ui.foreground }}>{t("statsCausesHeading")}</Text>
      {causes.hidden ? (
        <Text style={{ ...typography.subhead, color: ui.mutedForeground }}>{t("statsCausesHidden", { coded: causes.coded })}</Text>
      ) : (
        <>
          {causes.rows.map((cause) => (
            <View
              key={cause.suppressed ? "suppressed" : cause.label}
              accessible
              accessibilityLabel={t("statsCauseRow", { label: cause.suppressed ? t("statsOtherCauses") : cause.label, count: cause.coded_count, percent: formatPercent(cause.percent) })}
              style={{ gap: spacing.xxs }}
            >
              <View style={{ flexDirection: "row", justifyContent: "space-between", gap: spacing.sm }}>
                <Text style={{ flex: 1, fontSize: fontSize.body, color: ui.foreground }}>{cause.suppressed ? t("statsOtherCauses") : cause.label}</Text>
                <Text style={{ fontSize: fontSize.body, color: ui.foreground }}>{`${cause.coded_count} · ${formatPercent(cause.percent)}%`}</Text>
              </View>
              <View style={{ height: 6, borderRadius: radius.sm, backgroundColor: ui.secondary, overflow: "hidden" }}>
                <View style={{ width: `${Math.max(1, Math.min(100, cause.percent))}%`, height: 6, backgroundColor: cause.suppressed ? ui.mutedForeground : ui.primary }} />
              </View>
            </View>
          ))}
          {causes.rows.some((cause) => cause.suppressed) ? (
            <Text style={{ fontSize: fontSize.caption, color: ui.mutedForeground }}>{t("statsCausesSuppressed")}</Text>
          ) : null}
        </>
      )}
    </View>
  );
}
