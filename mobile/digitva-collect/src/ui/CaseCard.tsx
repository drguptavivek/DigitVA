/**
 * The case card shared by the browser lists (src/web/DeathsList.tsx re-exports it) and the Android Interviews
 * list. Presentational only: it reads no transport, so native may import it.
 */
import { useMemo, type ReactNode } from "react";
import { Platform, StyleSheet, Text, View } from "react-native";

import { t, type StringKey } from "../i18n";
import { MapsPinButton } from "../web/LocationCapture";
import { controls, radius, spacing, typography, useTheme } from "../theme";
import { useUiStyles } from "../ui";

export function sexLabel(value: string | null | undefined): string {
  if (!value) return "";
  const normalized = value.toLowerCase();
  const key = `sex${normalized[0]?.toUpperCase() ?? ""}${normalized.slice(1)}` as StringKey;
  const label = t(key);
  return label === key ? value : label;
}

export function formatDisplayTimestamp(value: string | null | undefined): string {
  if (!value) return "";
  const trimmed = value.trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) return trimmed;
  const parsed = new Date(trimmed);
  if (Number.isNaN(parsed.getTime())) return trimmed;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())} ${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`;
}

/** The case ID's face; the theme has no monospace token. */
const MONOSPACE = Platform.select({ web: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace", ios: "Menlo", default: "monospace" });

/**
 * Card styles shared by both case lists (reported deaths and My interviews). Every card text is >= 14px
 * in `colors.text`, the one token with >= 7:1 on the card in both modes (ui-token-contrast test); facts
 * are plain text, not chips. No fixed heights, so 200% zoom and text spacing wrap instead of clipping.
 */
export function useCaseCardStyles() {
  const { colors, ui } = useTheme();
  return useMemo(() => StyleSheet.create({
    line: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", columnGap: spacing.md, rowGap: spacing.xxs },
    titleGroup: { flexDirection: "row", flexWrap: "wrap", alignItems: "baseline", columnGap: spacing.sm, rowGap: spacing.xxs, flexShrink: 1, minWidth: 0 },
    cardTitle: { ...typography.headline, color: colors.text, fontFamily: controls.fontFamily },
    factList: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", columnGap: spacing.md, rowGap: spacing.xxs },
    factLine: { flexGrow: 1, justifyContent: "space-between" },
    fact: { ...typography.subhead, color: colors.text, fontFamily: controls.fontFamily },
    caseId: { ...typography.subhead, color: colors.text, fontFamily: MONOSPACE },
    caseIdMuted: { ...typography.caption, color: colors.textMuted, fontFamily: MONOSPACE },
    badgeRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xxs, alignItems: "center" },
    badge: { paddingVertical: spacing.xxs / 2, paddingHorizontal: spacing.xs, borderRadius: radius.full, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceMuted },
    badgeAccent: { borderColor: colors.accent, backgroundColor: colors.accentSoft },
    badgeWarning: { borderColor: ui.warningBorder, backgroundColor: ui.warning },
    badgeText: { ...typography.subhead, fontWeight: "600", color: colors.text, fontFamily: controls.fontFamily },
    badgeAccentText: { color: ui.accentForeground },
    badgeWarningText: { color: ui.warningForeground },
    noticeBanner: { paddingVertical: spacing.xxs, paddingHorizontal: spacing.xs, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceMuted },
    noticeBannerDanger: { borderColor: colors.danger, backgroundColor: colors.dangerSoft },
    noticeBannerAccent: { borderColor: colors.accent, backgroundColor: colors.accentSoft },
    noticeText: { ...typography.subhead, color: colors.text, fontFamily: controls.fontFamily },
    cardActions: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs, alignItems: "center" },
    actionButton: { minHeight: controls.minTouchTarget },
    listHeader: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs, alignItems: "center" },
  }), [colors, ui]);
}

/** One fact of a card: its visible text and, for a bare value, the name a screen reader hears instead. */
type CaseFact = { key: string; text: string; a11y?: string };
export type CaseBadge = { label: string; tone?: "neutral" | "accent" | "warning" };

/** A row of facts as a list (role list / listitem), so a screen reader hears each as one named item. */
function FactList({ facts, style }: { facts: CaseFact[]; style?: object }) {
  const c = useCaseCardStyles();
  if (facts.length === 0) return null;
  return (
    <View role="list" style={[c.factList, style]}>
      {facts.map((fact) => (
        <Text key={fact.key} role="listitem" accessibilityLabel={fact.a11y} style={c.fact} testID={`case-fact-${fact.key}`}>{fact.text}</Text>
      ))}
    </View>
  );
}

/**
 * The one case card of both case lists (docs/current-state/expo-client.md, "Case cards"). Line 1: name,
 * age, sex and the status badges; line 2: date of death, area; line 3: last contact, next visit
 * and *extra* facts; then *children* (notices); line 4: *actions* with the map pin, and the case ID on
 * the right. Empty items are omitted; on a narrow screen items wrap in the same order. The map pin shows
 * only when the row carries a GPS fix (the server sends one only to callers who may see it).
 */
export function CaseCard({
  title, titleTestID, caseId, ageYears, sex, dateOfDeath, area, lastContactAt, nextVisitAt,
  extra = [], badges, actions, latitude, longitude, testID, children, idBelowTitle = false,
}: {
  title: string;
  titleTestID?: string;
  caseId?: string | null;
  ageYears?: number | null;
  sex?: string | null;
  dateOfDeath?: string | null;
  area?: string;
  lastContactAt?: string | null;
  nextVisitAt?: string | null;
  extra?: CaseFact[];
  badges: CaseBadge[];
  actions: ReactNode;
  latitude?: number | null;
  longitude?: number | null;
  testID?: string;
  children?: ReactNode;
  /** The phone list puts the ID as a muted second line under the title; the browser keeps it at the foot of the card. */
  idBelowTitle?: boolean;
}) {
  const styles = useUiStyles();
  const c = useCaseCardStyles();
  const sexText = sexLabel(sex);
  const identity: CaseFact[] = [
    ...(ageYears != null ? [{ key: "age", text: t("metaAgeYears", { value: ageYears }), a11y: t("metaAgeA11y", { value: ageYears }) }] : []),
    ...(sexText ? [{ key: "sex", text: sexText, a11y: t("metaSexA11y", { value: sexText }) }] : []),
  ];
  const death: CaseFact[] = [
    ...(idBelowTitle ? identity : []),
    ...(dateOfDeath ? [{ key: "died", text: t("metaDied", { value: dateOfDeath }), a11y: t("metaDiedA11y", { value: dateOfDeath }) }] : []),
    ...(area ? [{ key: "area", text: t("metaArea", { value: area }) }] : []),
  ];
  const contact: CaseFact[] = [
    ...(lastContactAt ? [{ key: "lastContact", text: t("metaLastContact", { value: formatDisplayTimestamp(lastContactAt) }) }] : []),
    ...(nextVisitAt ? [{ key: "nextVisit", text: t("actionVisit", { date: formatDisplayTimestamp(nextVisitAt) }) }] : []),
    ...extra,
  ];
  return (
    <View style={styles.card} testID={testID}>
      <View style={c.line}>
        <View style={idBelowTitle ? { flexShrink: 1, minWidth: 0 } : undefined}>
          <View style={c.titleGroup}>
            <Text style={c.cardTitle} testID={titleTestID}>{title}</Text>
            {idBelowTitle ? null : <FactList facts={identity} />}
          </View>
          {idBelowTitle && caseId ? <Text style={c.caseIdMuted} accessibilityLabel={t("metaCaseIdA11y", { value: caseId })} testID="case-id-line">{caseId}</Text> : null}
        </View>
        {badges.length > 0 ? (
          <View style={c.badgeRow}>
            {badges.map((badge) => (
              <View key={badge.label} style={[c.badge, badge.tone === "accent" && c.badgeAccent, badge.tone === "warning" && c.badgeWarning]}>
                <Text style={[c.badgeText, badge.tone === "accent" && c.badgeAccentText, badge.tone === "warning" && c.badgeWarningText]}>{badge.label}</Text>
              </View>
            ))}
          </View>
        ) : null}
      </View>
      <FactList facts={death} style={c.factLine} />
      <FactList facts={contact} style={c.factLine} />
      {children}
      <View style={c.line}>
        <View style={c.cardActions}>
          {actions}
          <MapsPinButton latitude={latitude} longitude={longitude} />
        </View>
        {caseId && !idBelowTitle ? <FactList facts={[{ key: "caseId", text: caseId, a11y: t("metaCaseIdA11y", { value: caseId }) }]} style={{ marginLeft: "auto" }} /> : null}
      </View>
    </View>
  );
}
