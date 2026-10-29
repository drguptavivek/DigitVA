import { Text, View } from "react-native";

import type { DmKpi } from "../../data/api";
import { applyCard, cardActive, CARDS, type CardDef, type CardKey, type DataQuery } from "../../data/query";
import { t, type StringKey } from "../../i18n";
import { fontSize, spacing, typography, useTheme } from "../../theme";
import { StatPressable, TextAction } from "../stats/controls";

const CARD_LABELS: Record<CardKey, StringKey> = {
  total: "dataCardTotal", pending: "dataCardPending", smartvaPending: "dataCardSmartvaPending", coded: "dataCardCoded",
  upstream: "dataCardUpstream", attention: "dataCardAttention", notCodeable: "dataCardNotCodeable",
  notAnalysable: "dataCardNotAnalysable", missingOdk: "dataCardMissingOdk", smartvaMissing: "dataCardSmartvaMissing",
  smartvaFailed: "dataCardSmartvaFailed",
};

const ITEM_WIDTH = 104;

/**
 * The counts of the current filters as one wrapping strip, a number over its name. A card with a filter is a button:
 * its filter joins the view, and the active one is underlined and marked selected (a second press lifts it). The
 * counts come from a view rebuilt about every hour, so they can trail the list: the note says so and, for a data
 * manager, Refresh rebuilds it now (the server rate-limits that). The number is always written; nothing is carried by colour alone.
 */
export function DataCards({ kpi, query, loadedAt, busy, canRefresh, refreshing, onQuery, onRefresh }: {
  kpi: DmKpi | null;
  query: DataQuery;
  loadedAt: string;
  busy: boolean;
  canRefresh: boolean;
  refreshing: boolean;
  onQuery: (next: DataQuery) => void;
  onRefresh: () => void;
}) {
  const { ui } = useTheme();
  const reasons = kpi?.not_analysable_by_reason;
  const number = (value: number) => value.toLocaleString();
  const item = (card: CardDef) => {
    const count = kpi ? number(card.count(kpi)) : "–";
    const active = cardActive(card, query.filters);
    const body = (
      <View style={{ minWidth: ITEM_WIDTH, paddingVertical: spacing.xxs, paddingHorizontal: spacing.xs, borderBottomWidth: 2, borderBottomColor: active ? ui.primary : "transparent" }}>
        <Text style={{ ...typography.headline, fontWeight: "600", color: ui.foreground }}>{count}</Text>
        <Text style={{ fontSize: fontSize.caption, fontWeight: active ? "600" : "400", color: ui.mutedForeground }}>{t(CARD_LABELS[card.key])}</Text>
      </View>
    );
    const spoken = `${t(CARD_LABELS[card.key])}: ${count}`;
    return card.filter ? (
      <StatPressable key={card.key} label={t(active ? "dataCardLift" : "dataCardShow", { card: spoken })} selected={active} onPress={() => onQuery(applyCard(query, card))}>{body}</StatPressable>
    ) : (
      <View key={card.key} accessible accessibilityLabel={spoken}>{body}</View>
    );
  };
  return (
    <View accessibilityState={{ busy }} style={{ gap: spacing.xxs, opacity: busy ? 0.55 : 1 }}>
      <View accessibilityRole="toolbar" accessibilityLabel={t("dataCardsLabel")} style={{ flexDirection: "row", flexWrap: "wrap", columnGap: spacing.xs, rowGap: spacing.xxs }}>
        {CARDS.map(item)}
      </View>
      {reasons ? (
        <Text style={{ fontSize: fontSize.caption, color: ui.mutedForeground }}>
          {t("dataNotAnalysableSplit", { refused: number(reasons.refused ?? 0), unavailable: number(reasons.respondent_unavailable ?? 0), partial: number(reasons.partially_completed ?? 0) })}
        </Text>
      ) : null}
      <View style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center", columnGap: spacing.sm }}>
        <Text style={{ fontSize: fontSize.caption, color: ui.mutedForeground }}>{t("dataCountsNote", { time: loadedAt })}</Text>
        {canRefresh ? <TextAction small label={t(refreshing ? "dataRefreshing" : "dataRefresh")} onPress={refreshing ? () => undefined : onRefresh} /> : null}
      </View>
    </View>
  );
}
