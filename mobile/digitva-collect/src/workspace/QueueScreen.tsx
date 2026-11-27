import { ErrorCode } from "../errorCodes";
import { useCallback, useEffect, useMemo, useRef, useState, type ComponentType, type ReactNode } from "react";
import { ActivityIndicator, Alert, AppState, Platform, Pressable, Share, StyleSheet, Text, TextInput, View } from "react-native";
import Svg, { Path } from "react-native-svg";

import { APP_VERSION } from "../appVersion";
import { ConfirmDialog } from "../ConfirmDialog";
import { controls, radius, spacing, typography, useTheme } from "../theme";
import { Button, Card, DetailsChip, FieldLabel, Screen, SegmentedControl, TextField, errorText as uiErrorText, useUiStyles } from "../ui";
import { t, type StringKey } from "../i18n";
import { dateOnly } from "../ui/interviewRows";
import { ProjectSelect } from "../ui/ProjectSelect";
import { Select } from "../ui/Select";
import { ContextualHelpBanner } from "../web/ContextualHelp";
import { formatDisplayTimestamp } from "../web/DeathsList";
import { queuePlaceOptions } from "../web/placeOptions";
import type { QueuePlaceFilter, TrainingQueue, WorkspaceApi } from "./api";
import { ApiError, type AccessProject } from "../api";
import { sexLabel } from "../ui/CaseCard";
import { codingLanguageLines, languageLabel, trainingQueueCounts } from "./codingLanguages";
import { cardAge, formatCardDate, shortCaseNumber } from "./caseLabel";
import type { QueueView } from "./viewState";
import type { CodingHistoryCache, CodingHistoryIdentity } from "../codingHistoryCache";
import type {
  AllocationSnapshot,
  CoderAvailableCase,
  CoderHistory,
  CoderHistoryCase,
  CoderProjects,
  CoderQueue,
  CodingStats,
  ProjectOptions,
  QueueCase,
  ReviewerHistory,
  ReviewerQueue,
  ReviewerStats,
  WorkspaceIdentity,
} from "./contracts";

const PAGE_SIZE = 50;
const MAX_OFFSET = 1_000_000;

/** *place*: the chosen "Site and unit" key ("" for none); a page answer belongs to the place it was asked for. */
type QueueScope = { api: WorkspaceApi; mode: "coding" | "reviewing"; projectId?: string; offset: number; showHistory: boolean; place: string };
type GenderFilter = "all" | "female" | "male";
type AnyQueueCase = CoderAvailableCase | CoderHistoryCase | QueueCase;

function normalizeGenderKey(raw: string | null | undefined): "female" | "male" | "other" | null {
  if (!raw) return null;
  const lower = raw.trim().toLowerCase();
  if (lower === "f" || lower === "female") return "female";
  if (lower === "m" || lower === "male") return "male";
  return "other";
}

type QueueData = {
  api: WorkspaceApi;
  mode: "coding" | "reviewing";
  projectId?: string;
  offset: number;
  showHistory: boolean;
  place: string;
  stats?: CodingStats | ReviewerStats;
  coderAvailable?: CoderQueue;
  coderHistory?: CoderHistory;
  available?: ReviewerQueue;
  history?: ReviewerHistory;
  cachedHistoryAt?: string;
};

type AllocationData = { api: WorkspaceApi; mode: "coding" | "reviewing"; generation: number; verified: boolean; snapshot: AllocationSnapshot | null };
type QueueMessage = { scope: QueueScope; text: string; success?: boolean };

function useQueueStyles() {
  const { colors, ui } = useTheme();
  const phone = Platform.OS !== "web";
  return useMemo(() => {
    const base = StyleSheet.create({
    topLine: { flexDirection: "row", justifyContent: "flex-end" },
    titleRow: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
    titleMain: { flex: 1, minWidth: 0, flexDirection: "row", flexWrap: "wrap", alignItems: "baseline", columnGap: spacing.xs },
    iconButton: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderRadius: radius.md, ...(phone ? {} : { borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface }) },
    actions: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
    // Card buttons on the web: right-aligned at their own width, never full width (owner 2026-11-27); the phone fills the row.
    cardActions: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs, ...(phone ? {} : { justifyContent: "flex-end" }) },
    segmentedTrack: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xxs, padding: spacing.xxs, borderRadius: radius.md, backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border },
    actionBtn: { flexGrow: 1, flexBasis: 132 },
    cardBtn: phone ? { flexGrow: 1, flexBasis: 132 } : { minWidth: 160 },
    pager: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
    pagerBtn: { flex: 1 },
    pageText: { flex: 1, textAlign: "center", ...typography.subhead, color: colors.textMuted, fontFamily: controls.fontFamily },
    statsGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
    statTile: { flexGrow: 1, flexBasis: 96, paddingVertical: spacing.xxs, paddingHorizontal: spacing.xs, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceMuted, gap: 2 },
    statValue: { ...typography.headline, color: colors.text, fontFamily: controls.fontFamily },
    statLabel: { ...typography.caption, color: colors.textMuted, fontFamily: controls.fontFamily },
    statTileActive: { borderColor: colors.accent },
    filterBox: { gap: spacing.xs, padding: spacing.xs, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceMuted },
    searchInput: { minHeight: controls.minHeight, borderWidth: 1, borderColor: colors.borderStrong, borderRadius: radius.md, backgroundColor: colors.surface, paddingHorizontal: spacing.sm, paddingVertical: spacing.xxs, ...typography.subhead, color: colors.text, fontFamily: controls.fontFamily },
    chipRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xxs, alignItems: "center" },
    chip: { paddingVertical: spacing.xxs, paddingHorizontal: spacing.sm, borderRadius: radius.full, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
    chipActive: { borderColor: colors.accent, backgroundColor: colors.accent },
    chipText: { ...typography.caption, fontWeight: "600", color: colors.text, fontFamily: controls.fontFamily },
    chipTextActive: { color: colors.onAccent },
    caseCard: { gap: spacing.xxs },
    caseHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.xs, flexWrap: "wrap" },
    caseTitle: { flexShrink: 1, minWidth: 0 },
    badgeRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xxs, alignItems: "center" },
    badge: { paddingVertical: 2, paddingHorizontal: spacing.xs, borderRadius: radius.full, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceMuted },
    badgeAccent: { borderColor: colors.accent, backgroundColor: colors.accentSoft },
    badgeText: { ...typography.caption, fontWeight: "600", color: colors.textMuted, fontFamily: controls.fontFamily },
    badgeAccentText: { color: ui.accentForeground },
    metaGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xxs },
    metaChip: { paddingVertical: 2, paddingHorizontal: spacing.xs, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceMuted },
    metaChipText: { ...typography.caption, color: colors.textMuted, fontFamily: controls.fontFamily },
    // "Sync: Failed": the dark neutral (text-colour fill, inverse text); the card has no red, green or orange.
    metaChipStrong: { backgroundColor: colors.text, borderColor: colors.text },
    metaChipStrongText: { color: colors.surface },
    partsLine: { flexDirection: "row", flexWrap: "wrap", columnGap: spacing.xxs },
    });
    if (!phone) return base;
    // Phone (round-6 Q3-Q7): chips, badges and tiles are filled, never ringed; the selected chip takes the
    // primary tint. The browser keeps `base`; the case card's rows are the same on both (owner 2026-11-27).
    return {
      ...base,
      topLine: { gap: spacing.xxs },
      statTile: { ...base.statTile, borderWidth: 0 },
      statTileActive: { backgroundColor: ui.primaryTint },
      filterBox: { gap: spacing.xs },
      chip: { ...base.chip, borderWidth: 0, backgroundColor: ui.muted },
      chipActive: { backgroundColor: ui.primaryTint },
      chipTextActive: { color: ui.primary },
      badge: { ...base.badge, borderWidth: 0 },
      badgeAccent: { backgroundColor: ui.primaryTint },
      badgeAccentText: { color: ui.primary },
      metaChip: { ...base.metaChip, borderWidth: 0 },
    };
  }, [colors, ui, phone]);
}

function isInternalPlaceholderArea(name: string | null | undefined): boolean {
  return !name || /^sites_in_project_/i.test(name.trim());
}

function queueDate(raw: string | null | undefined): string | undefined {
  return raw && Platform.OS !== "web" ? dateOnly(raw) ?? undefined : raw ?? undefined;
}

function formatQueueDate(raw: string | null | undefined): string {
  if (!raw) return "";
  // The phone writes "21 Oct 2026" like the Interviews cards; the web keeps the ISO date.
  if (Platform.OS !== "web") return dateOnly(raw.trim()) ?? "";
  const trimmed = raw.trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) return trimmed;
  const match = /^(\d{4}-\d{2}-\d{2})T/.exec(trimmed);
  if (match) return match[1];
  return trimmed;
}

/**
 * The offline station's line for a coded case the server has answered: held ("waiting for the
 * server's DORIS") or refused with a plain reason per code, or the recode notice when the server
 * says the interview data changed after coding (`needs_recode`). Null when there is nothing to say.
 */
export function codingServerStatusText(item: Pick<CoderHistoryCase, "server_status" | "server_code" | "needs_recode">): string | null {
  if (item.needs_recode) return t("codingStaleRecode");
  if (item.server_status === "pending") return t("codingServerPending");
  if (item.server_status !== "refused") return null;
  const code = item.server_code ?? "";
  if (code === ErrorCode.CODED_VERSION_SUPERSEDED) return t("codingStaleRecode");
  const key = `codingRefused_${code}` as StringKey;
  // t() answers the key itself for a code this release has no words for.
  const known = /^[a-z_]+$/.test(code) ? t(key) : key;
  const reason = known !== key ? known : t("codingRefused_unknown", { code: code || "?" });
  return t("codingServerRefused", { reason });
}

/**
 * The recode deadline line on a coded case: "Recode until <local time>" while the Recode action
 * is offered, "Recode window closed" once `recode_until` has passed, else null (the window is the
 * project's, docs/policy/coding-workflow-state-machine.md "Recode Window").
 */
export function recodeDeadlineText(item: Pick<CoderHistoryCase, "recodeable" | "recode_until">, now: number = Date.now()): string | null {
  if (!item.recode_until) return null;
  if (item.recodeable) return t("codingRecodeUntil", { date: formatDisplayTimestamp(item.recode_until) });
  const until = Date.parse(item.recode_until);
  return !Number.isNaN(until) && until <= now ? t("codingRecodeClosed") : null;
}

/**
 * The coded-case card's details as plain text, for its copy icon: the share sheet offers Copy,
 * WhatsApp and email, so a coder can send it to support. The full masked case id, never the deceased's name.
 */
export function codedCaseSupportText(item: CoderHistoryCase, now: number = Date.now()): string {
  const lines = [
    `Case ${item.va_uniqueid_masked}`,
    [item.project_id, !isInternalPlaceholderArea(item.site_id) ? item.site_id : null, queueDate(item.va_submission_date)].filter(Boolean).join(" · "),
    [item.va_deceased_age != null && String(item.va_deceased_age).trim() !== "" ? `Age: ${item.va_deceased_age}` : null,
      item.va_deceased_gender ? `Sex: ${item.va_deceased_gender}` : null,
      item.va_form_id ? `Form: ${item.va_form_id}` : null,
      item.va_coding_date ? `Coded: ${formatQueueDate(item.va_coding_date)}` : null].filter(Boolean).join(" · "),
    [item.va_code_status, item.recodeable ? "Recodeable" : null].filter(Boolean).join(" · "),
    codingServerStatusText(item),
    item.server_status === "refused" && item.server_code ? `Code: ${item.server_code}` : null,
    recodeDeadlineText(item, now),
    `App ${APP_VERSION}`,
  ];
  return lines.filter((line): line is string => Boolean(line)).join("\n");
}

/**
 * An available or reviewed card's details as plain text, for its copy icon (as `codedCaseSupportText`): the full masked case
 * id, never the deceased's name.
 */
export function reviewedCaseSupportText(item: QueueCase | CoderAvailableCase): string {
  const lines = [
    `Case ${item.va_uniqueid_masked}`,
    [item.project_id, !isInternalPlaceholderArea(item.site_id) ? item.site_id : null, queueDate(item.va_submission_date)].filter(Boolean).join(" · "),
    [item.va_deceased_age != null && String(item.va_deceased_age).trim() !== "" ? `Age: ${item.va_deceased_age}` : null,
      item.va_deceased_gender ? `Sex: ${item.va_deceased_gender}` : null,
      item.va_form_id ? `Form: ${item.va_form_id}` : null,
      "va_reviewed_at" in item && item.va_reviewed_at ? `Reviewed: ${formatQueueDate(item.va_reviewed_at)}` : null].filter(Boolean).join(" · "),
    `App ${APP_VERSION}`,
  ];
  return lines.filter((line): line is string => Boolean(line)).join("\n");
}

/** "Case 000020" for a masked id like PHC01-000020_172313647; any other shape is shown as given. */
function caseTitle(masked: string): string {
  const number = shortCaseNumber(masked);
  return number ? t("queueCaseNumber", { number }) : masked;
}

/** Which list a card is on: it picks the last-action pill and the dates the card shows. */
export type QueueCardKind = "coding" | "codingHistory" | "review" | "reviewHistory";

/** The grey last-action pill: what last happened to the case on this list. */
function lastActionLabel(item: AnyQueueCase, kind: QueueCardKind): string {
  if (kind === "coding") return t("queuePillInterviewed");
  if (kind === "reviewHistory") return t("queuePillReviewed");
  if (kind === "codingHistory" && "va_code_status" in item && item.va_code_status === "Not Codeable") return t("queuePillNotCodeable");
  return item.recoded ? t("queuePillRecoded") : t("queuePillCoded");
}

/**
 * The dates line's "label: date" pairs, each only where its value exists: Died, Interviewed, Coded (the case's first
 * final COD; a history row's own coding date when the server sends none, e.g. tester output), Recoded (the latest,
 * only when recoded), then Not codeable or Reviewed (that action's date). A year-only date of death
 * (`death_date_year_only`) shows its year alone, never the stored day.
 */
function cardDates(item: AnyQueueCase, kind: QueueCardKind): string[] {
  const notCodeable = kind === "codingHistory" && "va_code_status" in item && item.va_code_status === "Not Codeable";
  const ownCoding = kind === "codingHistory" && !notCodeable && "va_coding_date" in item ? item.va_coding_date : null;
  const pairs: Array<[StringKey, string | null | undefined]> = [
    ["queueDateDied", item.date_of_death],
    ["queueDateInterviewed", item.va_submission_date],
    ["queueDateCoded", item.first_coded_at ?? ownCoding],
    ["queueDateRecoded", item.recoded ? item.last_coded_at : null],
    ["queueDateNotCodeable", notCodeable && "va_coding_date" in item ? item.va_coding_date : null],
    ["queueDateReviewed", kind === "reviewHistory" && "va_reviewed_at" in item ? item.va_reviewed_at : null],
  ];
  return pairs.flatMap(([key, raw]) => {
    const year = key === "queueDateDied" && item.death_date_year_only ? /^(\d{4})-/.exec(raw ?? "")?.[1] : undefined;
    const date = year ?? formatCardDate(raw);
    return date ? [t(key, { date })] : [];
  });
}

/** Phone only: the offline station's answer to a coded case, from `server_status`. */
function syncPill(item: AnyQueueCase): { label: string; failed: boolean } {
  const status = "server_status" in item ? item.server_status : null;
  if (status === "pending") return { label: t("queueSyncPending"), failed: false };
  if (status === "refused") return { label: t("queueSyncFailed"), failed: true };
  return { label: t("queueSyncDone"), failed: false };
}

/** Parts that wrap only between each other: each part keeps to one line. */
function PartsLine({ parts, testID }: { parts: string[]; testID: string }) {
  const styles = useUiStyles();
  const q = useQueueStyles();
  if (!parts.length) return null;
  return (
    <View style={q.partsLine} testID={testID}>
      {parts.map((part, index) => <Text key={index} numberOfLines={1} style={styles.muted}>{index ? `· ${part}` : part}</Text>)}
    </View>
  );
}

/**
 * One queue case card, the same on Coding and Review, web and phone (owner 2026-11-27), top to bottom:
 * 1. the title (the deceased's name when the item carries one, the server sending it only to a caller with
 *    personal-data access; else the case id) with the language pill and the grey last-action pill on its right;
 * 2. the place line: the case id (only under a name), the unit name (tree projects) or site name (never a code; a
 *    placeholder site hidden), and the project nickname when the picker is on All projects;
 * 3. the dates line (`cardDates`), dd-mmm-yyyy;
 * 4. the pills: age with its unit, sex, interviewer (absent when the server nulls it), and on the phone's coding
 *    history the Sync pill;
 * 5. *children*: each list's notes and its one row of buttons.
 */
export function QueueCaseCard({ item, kind, allProjects, children }: { item: AnyQueueCase; kind: QueueCardKind; allProjects: boolean; children?: ReactNode }) {
  const styles = useUiStyles();
  const q = useQueueStyles();
  const language = "va_narration_language" in item ? item.va_narration_language : null;
  const name = item.deceased_name || null;
  const site = isInternalPlaceholderArea(item.site_id) || isInternalPlaceholderArea(item.site_name) ? null : item.site_name;
  const place = [name ? caseTitle(item.va_uniqueid_masked) : null, item.unit_name || site, allProjects ? item.project_nickname : null]
    .filter((part): part is string => Boolean(part));
  const age = cardAge(item.va_deceased_age_normalized_days, item.va_deceased_age);
  const collector = "va_data_collector" in item ? item.va_data_collector : null;
  const sync = Platform.OS !== "web" && kind === "codingHistory" ? syncPill(item) : null;
  const pills = [
    // Bare values, as the settled card (owner 2026-11-27): "83 y", "Female"; only the interviewer keeps its label.
    age ? t(age.unit === "d" ? "queueAgeDays" : age.unit === "m" ? "queueAgeMonths" : "queueAgeYears", { n: age.n }) : null,
    item.va_deceased_gender ? sexLabel(item.va_deceased_gender) : null,
    collector ? t("queueInterviewer", { name: collector }) : null,
  ].filter((pill): pill is string => Boolean(pill));
  return (
    <View style={[styles.card, q.caseCard]} testID={`queue-case-${item.va_sid}`}>
      <View style={q.caseHeader}>
        <Text style={[styles.headline, q.caseTitle]}>{name || caseTitle(item.va_uniqueid_masked)}</Text>
        <View style={q.badgeRow}>
          {language ? (
            <View style={[q.badge, q.badgeAccent]} testID={`queue-case-language-${item.va_sid}`}>
              <Text style={[q.badgeText, q.badgeAccentText]}>{languageLabel(language)}</Text>
            </View>
          ) : null}
          <View style={q.badge} testID={`queue-case-action-${item.va_sid}`}>
            <Text style={q.badgeText}>{lastActionLabel(item, kind)}</Text>
          </View>
        </View>
      </View>
      <PartsLine parts={place} testID={`queue-case-place-${item.va_sid}`} />
      <PartsLine parts={cardDates(item, kind)} testID={`queue-case-dates-${item.va_sid}`} />
      {pills.length || sync ? (
        <View style={q.metaGrid}>
          {pills.map((pill) => <View key={pill} style={q.metaChip}><Text style={q.metaChipText}>{pill}</Text></View>)}
          {sync ? (
            <View style={[q.metaChip, sync.failed && q.metaChipStrong]} testID={`queue-case-sync-${item.va_sid}`}>
              <Text style={[q.metaChipText, sync.failed && q.metaChipStrongText]}>{sync.label}</Text>
            </View>
          ) : null}
        </View>
      ) : null}
      {children}
    </View>
  );
}

/** The 44px copy icon on every queue card (owner 2026-11-27): shares the case's support text (Copy, WhatsApp, email). */
function CopyIcon({ label, message }: { label: string; message: string }) {
  const { colors } = useTheme();
  const q = useQueueStyles();
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={label} onPress={() => void Share.share({ message }).catch(() => undefined)} style={q.iconButton}>
      {/* Tabler "copy": two overlapping sheets. */}
      <Svg width={22} height={22} viewBox="0 0 24 24">
        <Path d="M7 9.667a2.667 2.667 0 0 1 2.667 -2.667h8.666a2.667 2.667 0 0 1 2.667 2.667v8.666a2.667 2.667 0 0 1 -2.667 2.667h-8.666a2.667 2.667 0 0 1 -2.667 -2.667z" stroke={colors.text} strokeWidth={2} fill="none" strokeLinecap="round" strokeLinejoin="round" />
        <Path d="M4.012 16.737a2 2 0 0 1 -1.012 -1.737v-10c0 -1.1 .9 -2 2 -2h10c.75 0 1.158 .385 1.5 1" stroke={colors.text} strokeWidth={2} fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </Svg>
    </Pressable>
  );
}

function RefreshIcon({ onPress, disabled, loading = false }: { onPress: () => void; disabled: boolean; loading?: boolean }) {
  const { colors } = useTheme();
  const q = useQueueStyles();
  // Loading shows in the icon's own spot: a spinner row above the cards pushed them down and back (a layout shift).
  if (loading) return <View style={q.iconButton}><ActivityIndicator accessibilityLabel="Loading queue" /></View>;
  return (
    <Pressable accessibilityRole="button" accessibilityLabel="Refresh cases" accessibilityState={{ disabled }} disabled={disabled} onPress={onPress} style={[q.iconButton, disabled && { opacity: 0.5 }]}>
      {/* Tabler "refresh": two arrows round a circle, like the chevrons (Chevron.tsx). */}
      <Svg width={22} height={22} viewBox="0 0 24 24">
        <Path d="M20 11a8.1 8.1 0 0 0 -15.5 -2m-.5 -4v4h4" stroke={colors.text} strokeWidth={2} fill="none" strokeLinecap="round" strokeLinejoin="round" />
        <Path d="M4 13a8.1 8.1 0 0 0 15.5 2m.5 4v-4h-4" stroke={colors.text} strokeWidth={2} fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </Svg>
    </Pressable>
  );
}

/**
 * Load and operate the coder or reviewer queue without reading the unbounded
 * coder pick/history routes. Requests are discarded when scope or app state changes.
 */
/** Coder queue modes last seen per project, kept across remounts of the queue. */
const knownCoderModes = new Map<string, { pick: boolean; random: boolean }>();

export function QueueScreen({
  api,
  mode,
  onOpen,
  onExit,
  initialView,
  onViewChange,
  Shell,
  historyCache,
  historyIdentity,
  reloadKey,
  trainingQueue,
  onTrainingQueue,
  onEditLanguages,
  accessProjects,
}: {
  api: WorkspaceApi;
  mode: "coding" | "reviewing";
  onOpen: (identity: WorkspaceIdentity) => void;
  onExit?: () => void;
  /** Project, tab and page from the URL, already parsed; the project is checked against the catalogue before use. */
  initialView?: QueueView;
  /** Reports the settled project, tab and page so the route can keep them in the URL across a reload. */
  onViewChange?: (view: { projectId?: string; showHistory: boolean; offset: number }) => void;
  /** Optional shell component (e.g. WebShell on web) to wrap the queue with left navigation and language switcher. */
  Shell?: ComponentType<{ title: string; headerAction?: ReactNode; headerProject?: ReactNode; children: ReactNode }>;
  /** Native only; web leaves this unset. */
  historyCache?: CodingHistoryCache;
  historyIdentity?: CodingHistoryIdentity;
  /** A change reloads the page (native: the route bumps it when the queue regains focus; both: after a coding languages save). */
  reloadKey?: number;
  /** Training coding only: the queue *api* was made for; the queue buttons report the next one (the route makes a new api). */
  trainingQueue?: TrainingQueue;
  onTrainingQueue?: (queue: TrainingQueue) => void;
  /** Opens the in-app coding languages editor (the ✎ after "My languages"). */
  onEditLanguages?: () => void;
  /** The signed-in user's /me/access projects: their code/review reach builds the "Site and unit" filter. Unset: no filter. */
  accessProjects?: AccessProject[];
}) {
  const ActiveShell = Shell ?? Screen;
  // Phone presentation only (round-6 Q1-Q8); the browser keeps its own look.
  const phone = Platform.OS !== "web";
  const styles = useUiStyles();
  const q = useQueueStyles();
  const { colors, ui } = useTheme();
  const [projectId, setProjectId] = useState<string | undefined>(initialView?.projectId);
  const [offset, setOffset] = useState(initialView?.offset ?? 0);
  const [showHistory, setShowHistory] = useState(initialView?.showHistory ?? false);
  const startedOnAll = useRef(initialView?.allProjects === true);
  const startedOnProject = useRef(initialView?.projectId !== undefined);
  const [data, setData] = useState<QueueData | null>(null);
  const [allocationData, setAllocationData] = useState<AllocationData | null>(null);
  const [catalog, setCatalog] = useState<{ api: WorkspaceApi; mode: "coding" | "reviewing"; projects?: ProjectOptions } | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [confirmRelease, setConfirmRelease] = useState<{ warning: string; proceed: () => void } | null>(null);
  const [message, setMessage] = useState<QueueMessage | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [searchQuery, setSearchQuery] = useState("");
  const [genderFilter, setGenderFilter] = useState<GenderFilter>("all");
  const [placeKey, setPlaceKey] = useState("");
  const [recodeableOnly, setRecodeableOnly] = useState(false);
  const generation = useRef(0);
  // null until the first coder stats answer; load() uses it to pick the tab before fetching a page.
  const lastPickMode = useRef<boolean | null>(null);
  // Same for random mode, so the card title does not flip while a project's stats load.
  const lastRandomMode = useRef<boolean | null>(null);
  const actionInFlight = useRef(false);
  const cachedHistoryOnly = useRef(false);
  const actionError = useRef<QueueMessage | null>(null);
  // "Site and unit": the places the user's code or review reach covers in the chosen project (every queue project on All).
  // Only a key still offered counts, so a project change (picker, URL, fallback) drops a choice it no longer offers.
  const placeChoices = useMemo(() => {
    const offered = catalog?.api === api && catalog.mode === mode ? catalog.projects?.project_options.map((option) => option.project_id) : undefined;
    if (!accessProjects || !offered) return null;
    return queuePlaceOptions(accessProjects, mode === "coding" ? "code" : "review", projectId ? [projectId] : offered);
  }, [accessProjects, api, catalog, mode, projectId]);
  const placeFilter = placeChoices?.options.some((option) => option.value === placeKey) ? placeChoices.places.get(placeKey) : undefined;
  const place = placeFilter ? placeKey : "";
  // Primitives for load's deps: a re-read access summary rebuilds placeFilter without changing the place.
  const placeProjectId = placeFilter?.projectId;
  const placeSiteId = placeFilter?.siteId;
  const placeUnitId = placeFilter?.orgUnitId;
  const scopeRef = useRef<QueueScope>({ api, mode, projectId, offset, showHistory, place });
  scopeRef.current = { api, mode, projectId, offset, showHistory, place };
  const activeRef = useRef(AppState.currentState !== "background" && AppState.currentState !== "inactive" && (typeof document === "undefined" || document.visibilityState !== "hidden"));

  // A training queue the caller may not use answers 400/403 (training_scope.resolve_queue).
  const errorText = (error: unknown) => trainingQueue === "own" && error instanceof ApiError && (error.status === 400 || error.status === 403)
    && (error.code === ErrorCode.FORBIDDEN || error.code === ErrorCode.INVALID_REQUEST) ? t("errTrainingQueue") : uiErrorText(error);

  function clearMessage() {
    actionError.current = null;
    setMessage(null);
  }

  useEffect(() => {
    setSearchQuery("");
    setGenderFilter("all");
    setRecodeableOnly(false);
  }, [projectId, showHistory, offset, mode]);

  function isCurrent(requestGeneration: number, requestScope: typeof scopeRef.current) {
    const current = scopeRef.current;
    return generation.current === requestGeneration
      && activeRef.current
      && AppState.currentState !== "background"
      && AppState.currentState !== "inactive"
      && (typeof document === "undefined" || document.visibilityState !== "hidden")
      && current.api === requestScope.api
      && current.mode === requestScope.mode
      && current.projectId === requestScope.projectId
      && current.offset === requestScope.offset
      && current.showHistory === requestScope.showHistory
      && current.place === requestScope.place;
  }

  // The queue waits for the project catalogue, so the first load already uses the last project.
  const catalogReady = catalog?.api === api && catalog.mode === mode;

  const load = useCallback(async () => {
    const requestScope = { api, mode, projectId, offset, showHistory, place };
    if (!isCurrent(generation.current, requestScope) || !catalogReady) return;
    // A place on All projects also names its project: a site id alone may sit in two projects.
    const pageFilter = { projectId: projectId ?? placeProjectId, siteId: placeSiteId, orgUnitId: placeUnitId };
    // The counts follow the place too (owner 2026-11-27); without one the stats call is exactly as before.
    const statsArgs: [string | undefined, QueuePlaceFilter?] = place ? [pageFilter.projectId, { siteId: placeSiteId, orgUnitId: placeUnitId }] : [projectId];
    const requestGeneration = ++generation.current;
    cachedHistoryOnly.current = false;
    setAllocationData({ api, mode, generation: requestGeneration, verified: false, snapshot: null });
    setLoading(true);
    const allocationRequest = mode === "coding" ? api.getCodingAllocation() : api.getReviewerAllocation();
    void allocationRequest.then((snapshot) => {
      if (isCurrent(requestGeneration, requestScope)) {
        setAllocationData({ api, mode, generation: requestGeneration, verified: true, snapshot });
      }
    }).catch((error: unknown) => {
      if (isCurrent(requestGeneration, requestScope)) {
        setAllocationData(null);
        if (!actionError.current && !cachedHistoryOnly.current) setMessage({ scope: requestScope, text: errorText(error) });
      }
    });
    try {
      let next: QueueData;
      if (mode === "coding") {
        if (!showHistory && lastPickMode.current === null) {
          // Pick mode unknown: ask stats first so a random-only coder never fetches the available page.
          const first = await api.getCodingStats(...statsArgs);
          if (!isCurrent(requestGeneration, requestScope)) return;
          if ((first as { has_pick_mode?: boolean }).has_pick_mode === false) {
            lastPickMode.current = false;
            if ((first as { has_random_mode?: boolean }).has_random_mode !== true) {
              setOffset(0);
              setShowHistory(true);
              return;
            }
          }
        }
        if (!showHistory && lastPickMode.current === false) {
          // Random-only: the Available segment is the random panel, so there is no pick list to fetch (and no place).
          next = { api, mode, projectId, offset, showHistory, place, stats: await api.getCodingStats(projectId) };
        } else {
          const [stats, page] = await Promise.all([
            api.getCodingStats(...statsArgs),
            showHistory
              ? api.getCodingHistory({ ...pageFilter, limit: PAGE_SIZE, offset })
              : api.getCodingAvailable({ ...pageFilter, limit: PAGE_SIZE, offset }),
          ]);
          next = {
            api,
            mode,
            projectId,
            offset,
            showHistory,
            place,
            stats,
            ...(showHistory ? { coderHistory: page as CoderHistory } : { coderAvailable: page as CoderQueue }),
          };
        }
      } else {
        const [stats, page] = await Promise.all([
          api.getReviewerStats(...statsArgs),
          showHistory
            ? api.getReviewerHistory({ ...pageFilter, limit: PAGE_SIZE, offset })
            : api.getReviewerAvailable({ ...pageFilter, limit: PAGE_SIZE, offset }),
        ]);
        next = {
          api,
          mode,
          projectId,
          offset,
          showHistory,
          place,
          stats,
          ...(showHistory ? { history: page as ReviewerHistory } : { available: page as ReviewerQueue }),
        };
      }
      if (isCurrent(requestGeneration, requestScope)) {
        setData(next);
        // A place-filtered page is not the project's history: never saved as it.
        if (mode === "coding" && showHistory && projectId && !place && historyCache && historyIdentity) {
          const fingerprint = historyCache.fingerprintForProject(projectId);
          if (fingerprint) void historyCache.writePage(historyIdentity, projectId, next.coderHistory!, fingerprint).catch(() => undefined);
        }
      }
    } catch (error) {
      if (isCurrent(requestGeneration, requestScope)) {
        let cached: Awaited<ReturnType<CodingHistoryCache["readPage"]>> = null;
        // The cache holds whole-project pages: a place-filtered load never reads, writes or clears it, and a network
        // failure (TypeError) never clears it.
        const cacheable = mode === "coding" && projectId && !place && historyCache && historyIdentity;
        if (error instanceof TypeError) {
          if (cacheable && showHistory) {
            try {
              cached = await historyCache.readPage(historyIdentity, projectId, offset);
            } catch {
              cached = null;
            }
          }
        } else if (cacheable) {
          // Authorization, malformed-response, and server errors must never fall back to old rows.
          try { await historyCache.invalidateProject(historyIdentity, projectId); } catch { /* cache cleanup is best effort */ }
        }
        if (cached && isCurrent(requestGeneration, requestScope)) {
          cachedHistoryOnly.current = true;
          setSearchQuery("");
          setGenderFilter("all");
          setRecodeableOnly(false);
          setData({
            api, mode, projectId, offset, showHistory, place, coderHistory: cached.page,
            cachedHistoryAt: cached.fetchedAt,
          });
          setMessage(null);
          return;
        }
        setData(null);
        const previousError = actionError.current;
        if (!previousError || previousError.scope.api !== requestScope.api || previousError.scope.mode !== requestScope.mode
          || previousError.scope.projectId !== requestScope.projectId || previousError.scope.offset !== requestScope.offset
          || previousError.scope.showHistory !== requestScope.showHistory || previousError.scope.place !== requestScope.place) {
          actionError.current = null;
          setMessage({ scope: requestScope, text: errorText(error) });
        }
      }
    } finally {
      if (isCurrent(requestGeneration, requestScope)) setLoading(false);
    }
  }, [api, catalogReady, historyCache, historyIdentity, mode, offset, place, placeProjectId, placeSiteId, placeUnitId, projectId, showHistory]);

  // Load the project catalogue once per api and mode. Default: the URL's project, else the last project
  // when still offered, else (reviewers) the first project with cases to review, else All projects.
  useEffect(() => {
    let active = true;
    const request = mode === "coding" ? api.getCodingProjects() : api.getReviewerProjects();
    void request.then(async (projects) => {
      if (!active) return;
      const offered = (id: string | null | undefined) => id != null && projects.project_options.some((option) => option.project_id === id);
      let fallback = !startedOnAll.current && offered(projects.last_project_id) ? projects.last_project_id ?? undefined : undefined;
      if (fallback === undefined && !startedOnAll.current && !startedOnProject.current
        && mode === "reviewing" && projects.project_options.length > 1) {
        // ponytail: one stats call per offered project, only on this fallback path; a per-project
        // `available` count on /reviewing/projects would remove the fan-out.
        const counts = await Promise.all(projects.project_options.map((option) => api.getReviewerStats(option.project_id).catch(() => null)));
        if (!active) return;
        fallback = projects.project_options.find((_, index) => (counts[index]?.available ?? 0) > 0)?.project_id;
      }
      // A project named by the URL that is not offered (stale or edited) falls back to All projects.
      setProjectId((current) => {
        if (current !== undefined) return offered(current) ? current : undefined;
        return fallback;
      });
      setCatalog({ api, mode, projects });
    }).catch(async (error) => {
      if (!active) return;
      if (error instanceof TypeError && mode === "coding" && historyCache && historyIdentity) {
        const cachedProjects: string[] = await historyCache.cachedProjects(historyIdentity).catch((): string[] => []);
        if (!active) return;
        if (cachedProjects.length) {
          const options = cachedProjects.map((projectId) => ({ project_id: projectId, project_name: projectId }));
          const cachedCatalog: CoderProjects = { project_options: options, projects: cachedProjects, last_project_id: cachedProjects[0] };
          const cachedProject = cachedProjects[0];
          setProjectId((current) => current && cachedProjects.includes(current) ? current : cachedProject);
          setShowHistory(true);
          setCatalog({ api, mode, projects: cachedCatalog });
          lastPickMode.current = false;
          return;
        }
      }
      setProjectId(undefined);
      setCatalog({ api, mode });
    });
    return () => {
      active = false;
    };
  }, [api, historyCache, historyIdentity, mode]);

  useEffect(() => {
    setData(null);
    setBusy(false);
    actionInFlight.current = false;
    void load();
    return () => {
      generation.current += 1;
    };
  }, [load, refresh]);

  const lastReloadKey = useRef(reloadKey);
  useEffect(() => {
    if (reloadKey === lastReloadKey.current) return;
    lastReloadKey.current = reloadKey;
    setRefresh((n) => n + 1);
  }, [reloadKey]);

  useEffect(() => {
    let previous = AppState.currentState;
    const invalidate = () => {
      activeRef.current = false;
      generation.current += 1;
      actionInFlight.current = false;
      setData(null);
      clearMessage();
      setBusy(false);
      setLoading(false);
    };
    const subscription = AppState.addEventListener("change", (next) => {
      activeRef.current = next === "active" && (typeof document === "undefined" || document.visibilityState !== "hidden");
      if (activeRef.current && previous !== "active") {
        if (scopeRef.current.mode === "coding") {
          setShowHistory(false);
          setOffset(0);
        }
        setRefresh((value) => value + 1);
      }
      if (next !== "active") invalidate();
      previous = next;
    });
    const visibilityChanged = () => {
      if (typeof document === "undefined") return;
      if (document.visibilityState === "hidden") invalidate();
      else if (AppState.currentState === "active") {
        activeRef.current = true;
        if (scopeRef.current.mode === "coding") {
          setShowHistory(false);
          setOffset(0);
        }
        setRefresh((value) => value + 1);
      }
    };
    if (typeof document !== "undefined") document.addEventListener("visibilitychange", visibilityChanged);
    return () => {
      subscription.remove();
      if (typeof document !== "undefined") document.removeEventListener("visibilitychange", visibilityChanged);
    };
  }, []);

  const currentData = activeRef.current && AppState.currentState !== "background" && AppState.currentState !== "inactive"
    && (typeof document === "undefined" || document.visibilityState !== "hidden")
    && data?.api === api && data.mode === mode && data.projectId === projectId
    && data.offset === offset && data.showHistory === showHistory && data.place === place ? data : null;
  const currentMessage = activeRef.current && AppState.currentState !== "background" && AppState.currentState !== "inactive"
    && (typeof document === "undefined" || document.visibilityState !== "hidden")
    && message?.scope.api === api && message.scope.mode === mode
    && message.scope.projectId === projectId && message.scope.offset === offset
    && message.scope.showHistory === showHistory && message.scope.place === place ? message.text : "";

  function openCurrent(identity: WorkspaceIdentity) {
    const requestScope = { api, mode, projectId, offset, showHistory, place };
    if (isCurrent(generation.current, requestScope)) onOpen(identity);
  }

  const refreshAfterError = useCallback(async (error: unknown, requestScope: QueueScope) => {
    setBusy(false);
    actionInFlight.current = false;
    if (requestScope.mode === "coding") {
      const nextMessage = { scope: { ...requestScope, offset: 0, showHistory: false }, text: errorText(error) };
      actionError.current = nextMessage;
      setMessage(nextMessage);
      setOffset(0);
      setShowHistory(false);
      setRefresh((value) => value + 1);
    } else {
      const nextMessage = { scope: requestScope, text: errorText(error) };
      actionError.current = nextMessage;
      setMessage(nextMessage);
      await load();
    }
  }, [load]);

  async function allocateRandom() {
    const requestScope = { api, mode, projectId, offset, showHistory, place };
    if (busy || actionInFlight.current || mode !== "coding" || !allocationVerified || !isCurrent(generation.current, requestScope)) return;
    const requestGeneration = generation.current;
    actionInFlight.current = true;
    setBusy(true);
    clearMessage();
    try {
      const result = await api.allocateCoding(undefined, projectId);
      if (!isCurrent(requestGeneration, requestScope)) return;
      onOpen({ vaSid: result.va_sid, mode: "coding" });
    } catch (error) {
      if (isCurrent(requestGeneration, requestScope)) await refreshAfterError(error, requestScope);
    } finally {
      if (isCurrent(requestGeneration, requestScope)) {
        actionInFlight.current = false;
        setBusy(false);
      }
    }
  }

  async function allocateReviewer(vaSid: string) {
    const requestScope = { api, mode, projectId, offset, showHistory, place };
    if (busy || actionInFlight.current || mode !== "reviewing" || !allocationVerified || !isCurrent(generation.current, requestScope)) return;
    const requestGeneration = generation.current;
    actionInFlight.current = true;
    setBusy(true);
    clearMessage();
    try {
      const result = await api.allocateReviewer(vaSid);
      if (!isCurrent(requestGeneration, requestScope)) return;
      if (result.va_sid !== vaSid) throw new Error("allocation_case_mismatch");
      onOpen({ vaSid: result.va_sid, mode: "reviewing" });
    } catch (error) {
      if (isCurrent(requestGeneration, requestScope)) await refreshAfterError(error, requestScope);
    } finally {
      if (isCurrent(requestGeneration, requestScope)) {
        actionInFlight.current = false;
        setBusy(false);
      }
    }
  }

  async function releaseAllocation(requestGeneration: number, requestScope: typeof scopeRef.current) {
    if (busy || actionInFlight.current || !isCurrent(requestGeneration, requestScope)) return;
    actionInFlight.current = true;
    setBusy(true);
    clearMessage();
    try {
      if (mode === "coding") await api.releaseCoding();
      else await api.releaseReviewer();
      if (!isCurrent(requestGeneration, requestScope)) return;
      actionError.current = null;
      setMessage({ scope: requestScope, success: true, text: mode === "coding" ? "Coding case released." : "Review case released. Step 1 is kept; NQA and Social Autopsy are cleared." });
      setBusy(false);
      actionInFlight.current = false;
      await load();
    } catch (error) {
      if (isCurrent(requestGeneration, requestScope)) {
        setBusy(false);
        actionInFlight.current = false;
        await refreshAfterError(error, requestScope);
      }
    } finally {
      if (isCurrent(requestGeneration, requestScope)) {
        actionInFlight.current = false;
        setBusy(false);
      }
    }
  }

  function askRelease() {
    const requestGeneration = generation.current;
    const requestScope = { api, mode, projectId, offset, showHistory, place };
    if (!isCurrent(requestGeneration, requestScope)) return;
    // Name the case being given up, so the coder sees what is lost.
    const name = heldCase?.formId;
    const warning = `${name ? `${t("releaseCaseNamed", { name })} ` : ""}${t(mode === "reviewing" ? "releaseReviewWarning" : "releaseCodingWarning")}`;
    const proceed = () => {
      if (isCurrent(requestGeneration, requestScope)) void releaseAllocation(requestGeneration, requestScope);
    };
    if (Platform.OS === "web") {
      setConfirmRelease({ warning, proceed });
      return;
    }
    Alert.alert(
      t("releaseCaseTitle"),
      warning,
      [
        { text: t("codeNowKeepCase"), style: "cancel" },
        { text: t("releaseCaseAction"), style: "destructive", onPress: proceed },
      ],
    );
  }

  const allocation = allocationData?.api === api && allocationData.mode === mode
    && allocationData.generation === generation.current ? allocationData.snapshot : null;
  const allocationVerified = allocationData?.api === api && allocationData.mode === mode
    && allocationData.generation === generation.current && allocationData.verified;
  // Switching Available / My coded cases reloads the list; keep the last counts of the same queue on screen
  // meanwhile, so the header, languages and filters do not collapse and reappear (they all follow the stats).
  // The counts follow the place, so another place's counts are never held over (they would also mislead the tab rules).
  const lastStats = useRef<{ api: unknown; mode: string; projectId: unknown; place: string; stats: NonNullable<typeof currentData>["stats"] } | null>(null);
  if (currentData?.stats) lastStats.current = { api, mode, projectId, place, stats: currentData.stats };
  const heldStats = lastStats.current && lastStats.current.api === api && lastStats.current.mode === mode
    && lastStats.current.projectId === projectId && lastStats.current.place === place ? lastStats.current.stats : undefined;
  const stats = currentData?.stats ?? heldStats;
  const projects = catalogReady ? catalog?.projects : undefined;

  // The allocation snapshot carries only the SID; one workspace read per held case names its form and project.
  const [heldCase, setHeldCase] = useState<{ api: WorkspaceApi; mode: "coding" | "reviewing"; vaSid: string; formId: string; deceasedName: string | null; projectCode: string | null; siteCode: string | null; orgProject: boolean } | null>(null);
  const heldCaseRef = useRef(heldCase);
  heldCaseRef.current = heldCase;
  const allocationSid = allocation?.va_sid;
  useEffect(() => {
    const known = heldCaseRef.current;
    if (!allocationSid || (known?.api === api && known.mode === mode && known.vaSid === allocationSid)) return undefined;
    let active = true;
    void Promise.resolve()
      .then(() => api.getWorkspace(allocationSid, mode))
      .then((workspace) => {
        if (active) setHeldCase({ api, mode, vaSid: allocationSid, formId: workspace.case.instance_name, deceasedName: workspace.case.deceased_name ?? null, projectCode: workspace.case.project_code ?? null, siteCode: workspace.case.site_code ?? null, orgProject: workspace.case.is_org_project === true });
      })
      .catch(() => undefined);
    return () => { active = false; };
  }, [allocationSid, api, mode]);
  const heldLabel = allocation && heldCase?.api === api && heldCase.mode === mode && heldCase.vaSid === allocation.va_sid ? heldCase : null;
  // Same "Project / Site" the case workspace shows; the project's name when its code is also a catalogue id.
  const heldProjectName = heldLabel?.projectCode
    ? projects?.project_options.find((option) => option.project_id === heldLabel.projectCode)?.project_name ?? null
    : null;
  const heldText = heldLabel
    ? [heldLabel.deceasedName, heldLabel.formId, heldLabel.orgProject ? `Project: ${heldLabel.projectCode ?? "-"}` : `Project / Site: ${heldLabel.projectCode ?? "-"}/${heldLabel.siteCode ?? "-"}`, heldProjectName].filter(Boolean).join(" · ")
    : "";
  const coderStats = mode === "coding" && stats && "random_ready" in stats ? stats : undefined;
  const reviewerStats = mode === "reviewing" && stats && "available" in stats ? stats : undefined;
  const randomReady = coderStats?.random_ready;
  // With a place the random pool count is the place's, but random allocation ignores the place: an empty place count
  // must not disable it (the server answers if the whole pool is empty).
  const canAllocateRandom = mode === "coding"
    && allocationVerified
    && coderStats?.has_random_mode === true
    && typeof randomReady === "number"
    && (randomReady > 0 || Boolean(place));
  const coderCount = showHistory ? currentData?.coderHistory?.history.length : currentData?.coderAvailable?.forms.length;
  const reviewerRows = showHistory ? currentData?.history?.history : currentData?.available?.cases;
  const canGoNext = mode === "coding"
    ? showHistory ? currentData?.coderHistory?.has_more : currentData?.coderAvailable?.has_more
    : showHistory ? currentData?.history?.has_more : currentData?.available?.has_more;
  // Previous / Page N / Next only when there is another page to reach: past page one, or a next page.
  const showPager = offset > 0 || Boolean(canGoNext);

  // Random-only coders have nothing to pick by hand, so their list is the coded-case history.
  // lastPickMode (declared above load) keeps the tab row from flickering while page loads clear stats.
  // Before this mount's first stats, the project's modes from the last visit: guessing drew the random panel
  // that the stats then swapped for the pick list (a flash on every return to the Code tab).
  // Keyed by the project the stats were asked for: on All projects a place's stats are its own project's.
  const modesKey = `${mode}:${String(place ? projectId ?? placeProjectId : projectId)}`;
  if (coderStats) knownCoderModes.set(modesKey, { pick: coderStats.has_pick_mode === true, random: coderStats.has_random_mode === true });
  const knownModes = knownCoderModes.get(modesKey);
  if (coderStats) lastPickMode.current = coderStats.has_pick_mode === true;
  const pickMode = coderStats ? coderStats.has_pick_mode === true : lastPickMode.current ?? knownModes?.pick ?? false;
  if (coderStats) lastRandomMode.current = coderStats.has_random_mode === true;
  const randomMode = coderStats ? coderStats.has_random_mode === true : lastRandomMode.current ?? knownModes?.random ?? true;
  // Random-only: Available is the random panel; the list, filters and pager belong to My coded cases.
  const showList = showHistory || pickMode || !randomMode;
  const pickReady = typeof coderStats?.pick_ready === "number" ? coderStats.pick_ready : undefined;
  // Random-only coding has no list to narrow (owner rule 2026-11-27): no place choice there, and none is sent.
  // On All projects a place's stats carry its own project's modes: a random-only project there keeps the choice
  // (the coder changes it back), rather than the field vanishing under them.
  const placeHidden = mode === "coding" && randomMode && !pickMode && !(projectId === undefined && place);
  useEffect(() => {
    if (placeHidden && placeKey) setPlaceKey("");
  }, [placeHidden, placeKey]);
  // No count-driven tab switch while a place is chosen: a place's zero must not move the coder to their history.
  useEffect(() => {
    const emptyPick = !place && pickMode && pickReady === 0 && randomMode && typeof randomReady === "number" && randomReady > 0;
    if (coderStats && ((!pickMode && !randomMode) || emptyPick) && !showHistory) {
      setOffset(0);
      setShowHistory(true);
    }
  }, [coderStats, pickMode, pickReady, place, randomMode, randomReady, showHistory]);
  // A project that has pick mode (after one that had not) must not stay stuck on the history tab.
  const wasPickMode = useRef(pickMode || showHistory);
  // Only loaded stats count: a page load clears them, and reading that gap as "pick_ready unknown"
  // would undo the history tab the effect above (or the user) just chose, in a loop.
  const statsLoaded = Boolean(coderStats);
  useEffect(() => {
    // A place's counts say nothing about the project's pick list: leave the tab and the memory as they are.
    if (!statsLoaded || place) return;
    const pickable = pickMode && (pickReady === undefined || pickReady > 0);
    if (pickable && !wasPickMode.current && showHistory) {
      setOffset(0);
      setShowHistory(false);
    }
    wasPickMode.current = pickable;
  }, [statsLoaded, pickMode, pickReady, place, showHistory]);

  const viewChanged = useRef(onViewChange);
  viewChanged.current = onViewChange;
  useEffect(() => {
    if (catalogReady) viewChanged.current?.({ projectId, showHistory, offset });
  }, [catalogReady, projectId, showHistory, offset]);

  // Back and Forward change the URL's project under a mounted queue: follow it once the catalogue is in (the first
  // value is the default chain's, above). A project the catalogue does not offer is All projects, as on first load.
  const urlProject = initialView?.allProjects ? "all" : initialView?.projectId;
  const seenUrlProject = useRef(urlProject);
  useEffect(() => {
    if (!catalogReady || seenUrlProject.current === urlProject) return;
    seenUrlProject.current = urlProject;
    const next = projects?.project_options.some((option) => option.project_id === urlProject) ? urlProject : undefined;
    if (next === projectId) return;
    clearMessage();
    setOffset(initialView?.offset ?? 0);
    setPlaceKey("");
    setProjectId(next);
  }, [catalogReady, urlProject]);

  const activeItems = useMemo<AnyQueueCase[]>(() => {
    if (mode === "coding") {
      return showHistory
        ? (currentData?.coderHistory?.history ?? [])
        : (currentData?.coderAvailable?.forms ?? []);
    }
    return reviewerRows ?? [];
  }, [currentData, mode, reviewerRows, showHistory]);

  const hasGenderData = useMemo(
    () => activeItems.some((item) => Boolean(item.va_deceased_gender)),
    [activeItems],
  );

  const hasRecodeableData = useMemo(
    () => mode === "coding" && showHistory && activeItems.some((item) => "recodeable" in item && item.recodeable === true),
    [activeItems, mode, showHistory],
  );

  const matchesCase = useCallback((item: AnyQueueCase): boolean => {
    if (genderFilter !== "all" && normalizeGenderKey(item.va_deceased_gender) !== genderFilter) return false;
    if (recodeableOnly && mode === "coding" && showHistory) {
      if (!("recodeable" in item && item.recodeable === true)) return false;
    }
    const query = searchQuery.trim().toLowerCase();
    if (!query) return true;
    const haystack = [
      item.va_uniqueid_masked,
      "deceased_name" in item ? item.deceased_name : undefined,
      item.va_form_id,
      item.project_id,
      item.site_id,
      item.va_submission_date,
      "va_data_collector" in item ? item.va_data_collector : undefined,
      "va_code_status" in item ? item.va_code_status : undefined,
      "va_narration_language" in item ? item.va_narration_language : undefined,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(query);
  }, [genderFilter, mode, recodeableOnly, searchQuery, showHistory]);

  const filteredCoderHistory = useMemo(
    () => (currentData?.coderHistory?.history ?? []).filter(matchesCase),
    [currentData?.coderHistory?.history, matchesCase],
  );
  const filteredCoderAvailable = useMemo(
    () => (currentData?.coderAvailable?.forms ?? []).filter(matchesCase),
    [currentData?.coderAvailable?.forms, matchesCase],
  );
  const filteredReviewerRows = useMemo(
    () => (reviewerRows ?? []).filter(matchesCase),
    [matchesCase, reviewerRows],
  );

  const hasActiveFilters = searchQuery.trim().length > 0 || genderFilter !== "all" || recodeableOnly;
  const filteredCount = mode === "coding"
    ? (showHistory ? filteredCoderHistory.length : filteredCoderAvailable.length)
    : filteredReviewerRows.length;

  /** "My languages ✎" (both queues filter on them) and, on Coding, "Forms pending coding". */
  function renderLanguageLines() {
    const lines = codingLanguageLines(coderStats ?? reviewerStats);
    if (!lines) return null;
    return (
      <View testID="coding-languages">
        <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.xs }}>
          <Text style={styles.muted}>{lines.mine}</Text>
          {onEditLanguages ? (
            <Pressable accessibilityRole="link" accessibilityLabel={t("queueLanguagesEdit")} onPress={onEditLanguages} hitSlop={12} testID="coding-languages-edit">
              <Text style={[styles.muted, { color: colors.accent }]}>✎</Text>
            </Pressable>
          ) : null}
        </View>
        {lines.pending ? <Text style={styles.muted} testID="coding-pending-languages">{lines.pending}</Text> : null}
      </View>
    );
  }

  /** Coder sessions: the standard set; self-coding sessions also their own interviews. The queues never mix. */
  function renderTrainingQueues() {
    const counts = trainingQueueCounts(coderStats);
    if (!counts || !onTrainingQueue) return null;
    const current = trainingQueue ?? "standard";
    const queue = (value: TrainingQueue, label: string, count: { coded: number; total: number }, countKey: "trainingQueueStandardCount" | "trainingQueueOwnCount") => (
      <View key={value} style={{ gap: spacing.xxs }}>
        <Button size="sm" kind={current === value ? "primary" : "secondary"} label={label} disabled={busy || loading} selected={current === value}
          onPress={() => { if (current !== value) onTrainingQueue(value); }} testID={`training-queue-${value}`} />
        <Text style={styles.muted}>{t(countKey, { x: count.coded, y: count.total })}</Text>
      </View>
    );
    return (
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm }} testID="training-queues">
        {queue("standard", t("trainingQueueStandard"), counts.standard, "trainingQueueStandardCount")}
        {counts.own ? queue("own", t("trainingQueueOwn"), counts.own, "trainingQueueOwnCount") : null}
      </View>
    );
  }

  function renderFilterControls() {
    if (activeItems.length === 0 && !(mode === "coding" && showHistory)) return null;
    return (
      <View style={q.filterBox}>
        {phone ? (
          <TextField onCard accessibilityLabel="Filter cases" placeholder="Filter by ID, area, interviewer, or form..." value={searchQuery} onChangeText={setSearchQuery} />
        ) : (
          <TextInput
            accessibilityLabel="Filter cases"
            placeholder="Filter by ID, area, interviewer, or form..."
            placeholderTextColor={colors.textMuted}
            value={searchQuery}
            onChangeText={setSearchQuery}
            style={q.searchInput}
          />
        )}
        {(hasGenderData || hasRecodeableData) ? (
          <View style={q.chipRow}>
            {hasGenderData ? (
              <>
                {([
                  { key: "all" as const, label: "All sexes" },
                  { key: "female" as const, label: "Female" },
                  { key: "male" as const, label: "Male" },
                ]).map((opt) => {
                  const active = genderFilter === opt.key;
                  return (
                    <Pressable
                      key={opt.key}
                      hitSlop={spacing.xs}
                      accessibilityRole="button"
                      accessibilityLabel={`Filter sex: ${opt.label}`}
                      accessibilityState={{ selected: active }}
                      onPress={() => setGenderFilter(opt.key)}
                      style={[q.chip, active && q.chipActive]}
                    >
                      <Text style={[q.chipText, active && q.chipTextActive]}>{opt.label}</Text>
                    </Pressable>
                  );
                })}
              </>
            ) : null}
            {hasRecodeableData ? (
              <Pressable
                hitSlop={spacing.xs}
                accessibilityRole="button"
                accessibilityLabel="Filter recodeable only"
                accessibilityState={{ selected: recodeableOnly }}
                onPress={() => setRecodeableOnly((prev) => !prev)}
                style={[q.chip, recodeableOnly && q.chipActive]}
              >
                <Text style={[q.chipText, recodeableOnly && q.chipTextActive]}>Recodeable only</Text>
              </Pressable>
            ) : null}
          </View>
        ) : null}
        {hasActiveFilters ? (
          <View style={q.chipRow}>
            <Text style={styles.muted}>Showing {filteredCount} of {activeItems.length} cases</Text>
            <Pressable
              hitSlop={spacing.xs}
              accessibilityRole="button"
              accessibilityLabel="Clear filters"
              onPress={() => {
                setSearchQuery("");
                setGenderFilter("all");
                setRecodeableOnly(false);
              }}
              style={q.chip}
            >
              <Text style={q.chipText}>Clear filters</Text>
            </Pressable>
          </View>
        ) : null}
      </View>
    );
  }

  /** Allocate a SID from the current server page; mismatches fail and action errors survive refresh. */
  async function allocatePicked(vaSid: string) {
    const requestScope = { api, mode, projectId, offset, showHistory, place };
    if (busy || actionInFlight.current || mode !== "coding" || showHistory || !allocationVerified || allocation || !isCurrent(generation.current, requestScope)) return;
    const requestGeneration = generation.current;
    actionInFlight.current = true;
    setBusy(true);
    clearMessage();
    try {
      const result = await api.allocateCoding(vaSid, projectId);
      if (!isCurrent(requestGeneration, requestScope)) return;
      if (result.va_sid !== vaSid) throw new Error("allocation_case_mismatch");
      onOpen({ vaSid: result.va_sid, mode: "coding" });
    } catch (error) {
      if (isCurrent(requestGeneration, requestScope)) await refreshAfterError(error, requestScope);
    } finally {
      if (isCurrent(requestGeneration, requestScope)) {
        actionInFlight.current = false;
        setBusy(false);
      }
    }
  }

  /** Recode a server-marked history SID; mismatches fail and action errors survive refresh. */
  async function recodeCase(vaSid: string) {
    const requestScope = { api, mode, projectId, offset, showHistory, place };
    if (busy || actionInFlight.current || mode !== "coding" || !showHistory || !allocationVerified || allocation || !isCurrent(generation.current, requestScope)) return;
    const requestGeneration = generation.current;
    actionInFlight.current = true;
    setBusy(true);
    clearMessage();
    try {
      const result = await api.recode(vaSid);
      if (!isCurrent(requestGeneration, requestScope)) return;
      if (result.va_sid !== vaSid) throw new Error("allocation_case_mismatch");
      onOpen({ vaSid: result.va_sid, mode: "coding" });
    } catch (error) {
      if (isCurrent(requestGeneration, requestScope)) await refreshAfterError(error, requestScope);
    } finally {
      if (isCurrent(requestGeneration, requestScope)) {
        actionInFlight.current = false;
        setBusy(false);
      }
    }
  }

  /** Why the reviewer list is empty, in plain words; the counts alone do not say. */
  function reviewerEmptyText(): string {
    if (showHistory) return "No reviewed cases yet.";
    if (offset > 0) return "No more cases to review.";
    const where = projectId === undefined ? "in your projects" : "in this project";
    if (reviewerStats?.in_scope === 0) return `No cases ${where} yet.`;
    if (reviewerStats && reviewerStats.available === 0) {
      return `Nothing to review ${where} yet: cases appear here after a coder finalises them.`;
    }
    return "No cases to review right now.";
  }

  /** Phone: the header, tiles, tabs and filter share one card and each case is its own card; the browser nests all in one. */
  const headBlock = (kids: ReactNode) => (phone ? <Card>{kids}</Card> : <>{kids}</>);
  /** Available (false) or the history segment (true): the segment buttons and the count tiles share it. */
  const showTab = (history: boolean) => { clearMessage(); setShowHistory(history); setOffset(0); };
  const tabs = (history: string) => (phone ? (
    <SegmentedControl
      accessibilityLabel="Cases"
      disabled={busy}
      value={showHistory ? "history" : "available"}
      options={[{ value: "available", label: "Available" }, { value: "history", label: history }]}
      onChange={(next) => showTab(next === "history")}
    />
  ) : (
    <View style={q.segmentedTrack}>
      <Button label="Available" size="sm" kind={!showHistory ? "primary" : "secondary"} style={q.actionBtn} disabled={busy} onPress={() => showTab(false)} />
      <Button label={history} size="sm" accessibilityLabel="History" kind={showHistory ? "primary" : "secondary"} style={q.actionBtn} disabled={busy} onPress={() => showTab(true)} />
    </View>
  ));
  /**
   * One count tile. With *history* (false: Available, true: the history segment) it is a button doing what that
   * segment does, selected while that segment shows; without, a plain count (no list behind it).
   */
  const statTile = (value: number | string, label: string, history?: boolean) => {
    const body = <><Text style={q.statValue}>{String(value)}</Text><Text style={q.statLabel}>{label}</Text></>;
    if (history === undefined) return <View key={label} style={q.statTile}>{body}</View>;
    const selected = showHistory === history;
    return (
      <Pressable key={label} accessibilityRole="button" accessibilityLabel={`${label}: ${value}`} accessibilityState={{ selected, disabled: busy }}
        disabled={busy} focusable onPress={() => showTab(history)} style={[q.statTile, selected && q.statTileActive]}>
        {body}
      </Pressable>
    );
  };

  function refreshCases() {
    clearMessage();
    setShowHistory(false);
    setOffset(0);
    setRefresh((value) => value + 1);
  }

  // On the web shell the project switcher joins the title row (left of the language button); the phone and a bare Screen keep a line of their own.
  const projectInHeader = !phone && Boolean(Shell);
  const projectSelect = projects?.project_options.length ? (
    <ProjectSelect
      projects={projects.project_options.map((option) => ({ id: option.project_id, name: option.project_name }))}
      value={projectId ? [projectId] : []}
      disabled={busy}
      onChange={(next) => {
        clearMessage();
        setOffset(0);
        // A new project starts on its default segment; its pick mode is not known until its stats arrive.
        setShowHistory(initialView?.showHistory ?? false);
        lastPickMode.current = null;
        // Choosing the project already shown keeps its place; another project starts on All areas.
        if (next[0] !== projectId) setPlaceKey("");
        setProjectId(next[0]);
      }}
      fieldRow={phone}
    />
  ) : null;
  // One "Site and unit" choice under the project (owner rule 2026-11-27); the server narrows every page to it.
  const placeSelect = placeChoices?.options.length && !placeHidden ? (
    <View style={{ gap: spacing.xxs }} testID="queue-place">
      <FieldLabel label={t("chooseSite")} />
      <Select
        label={t("chooseSite")}
        placeholder={t("filterAllAreas")}
        searchLabel={t("filterUnitSearch")}
        searchable
        options={[{ value: "", label: t("filterAllAreas") }, ...placeChoices.options]}
        value={place}
        onChange={(next) => {
          if (next === place) return;
          clearMessage();
          setOffset(0);
          setPlaceKey(next);
        }}
      />
    </View>
  ) : null;

  return (
    <ActiveShell
      title={mode === "coding" ? "Coding queue" : "Review queue"}
      {...(projectInHeader ? { headerProject: projectSelect } : {})}
      // Phone: the bar has the back arrow and the shell Help sheet has the guide, so no Back or Help pill here.
      headerAction={onExit && !phone ? <Button label="Back" kind="secondary" size="sm" onPress={onExit} /> : undefined}
    >
      {phone ? null : <ContextualHelpBanner screen={mode === "coding" ? "coding" : "reviewing"} />}
      {projectSelect && !projectInHeader ? <View style={q.topLine}>{projectSelect}</View> : null}
      {placeSelect}
      {/* First load only: once a card is drawn its refresh icon spins instead. */}
      {loading && !stats ? <ActivityIndicator accessibilityLabel="Loading queue" /> : null}
      {currentMessage ? <Text accessibilityRole={message?.success ? "text" : "alert"} style={[styles.error, message?.success && { color: ui.success }]}>{currentMessage}</Text> : null}

      {allocation && !currentData?.cachedHistoryAt ? (
        <View style={styles.card}>
          <Text style={styles.headline}>{`You have an active ${mode === "coding" ? "coding" : "review"} case`}</Text>
          {heldText ? <Text style={styles.text}>{heldText}</Text> : null}
          <Text style={styles.muted}>Resume it, or release it, before you start another case.</Text>
          <View style={q.actions}>
            <Button label="Resume case" size="sm" style={q.actionBtn} disabled={busy || loading} onPress={() => openCurrent({ vaSid: allocation.va_sid, mode })} />
            <Button label="Release case" kind="danger" size="sm" style={q.actionBtn} disabled={busy || loading} onPress={askRelease} />
          </View>
        </View>
      ) : null}


      {mode === "coding" ? (
        <View style={phone ? { gap: controls.gap } : styles.card}>
          {headBlock(<>
          {/* No card title on Coding (owner 2026-11-27): the page title says it; the refresh icon shares the languages row, so no empty row. */}
          <View style={q.titleRow}>
            <View style={{ flex: 1, minWidth: 0 }}>{renderLanguageLines()}</View>
            <RefreshIcon disabled={busy || loading} loading={loading} onPress={refreshCases} />
          </View>
          {renderTrainingQueues()}
          {coderStats ? (
            <View style={q.statsGrid}>
              {randomMode && typeof coderStats.random_ready === "number" ? statTile(coderStats.random_ready, "Random pool") : null}
              {pickMode && typeof coderStats.pick_ready === "number" ? statTile(coderStats.pick_ready, "Ready to pick", false) : null}
              {typeof coderStats.completed === "number" ? statTile(coderStats.completed, "Coded", true) : null}
              {typeof coderStats.not_codeable === "number" && coderStats.not_codeable > 0 ? statTile(coderStats.not_codeable, "Not codeable") : null}
            </View>
          ) : null}
          {randomMode && (pickMode || !showHistory) && !currentData?.cachedHistoryAt ? <Button label="Start a random case" size="sm" disabled={busy || loading || !canAllocateRandom || Boolean(allocation)} loading={busy} onPress={() => void allocateRandom()} /> : null}
          {pickMode || randomMode ? tabs("My coded cases") : <Text style={styles.muted}>My coded cases</Text>}
          {currentData?.cachedHistoryAt ? <Text style={styles.muted} testID="cached-coding-history">Saved on this phone · last updated {formatDisplayTimestamp(currentData.cachedHistoryAt)} · read only</Text> : null}
          {showList ? renderFilterControls() : null}
          </>)}
          {!showList ? null : showHistory ? filteredCoderHistory.map((item) => (
            <QueueCaseCard key={item.va_sid} item={item} kind="codingHistory" allProjects={projectId === undefined}>
              {codingServerStatusText(item) ? <Text style={styles.muted} testID={`coding-server-status-${item.va_sid}`}>{codingServerStatusText(item)}</Text> : null}
              {item.server_status === "refused" ? <DetailsChip code={item.server_code} /> : null}
              <View style={q.cardActions}>
                {!currentData?.cachedHistoryAt ? <>
                  <Button label="View case" kind="secondary" size="sm" style={q.cardBtn} disabled={busy || loading} onPress={() => openCurrent({ vaSid: item.va_sid, mode: "view" })} />
                  {item.recodeable ? <Button label={t("queueRecodeCase")} size="sm" style={q.cardBtn} disabled={busy || loading || !allocationVerified || Boolean(allocation)} loading={busy} onPress={() => void recodeCase(item.va_sid)} /> : null}
                </> : null}
                <CopyIcon label={`Copy details of ${caseTitle(item.va_uniqueid_masked)}`} message={codedCaseSupportText(item)} />
              </View>
            </QueueCaseCard>
          )) : filteredCoderAvailable.map((item) => (
            <QueueCaseCard key={item.va_sid} item={item} kind="coding" allProjects={projectId === undefined}>
              <View style={q.cardActions}>
                <Button label={t("queueCodeCase")} size="sm" style={q.cardBtn} disabled={busy || loading || !allocationVerified || Boolean(allocation) || coderStats?.has_pick_mode !== true} loading={busy} onPress={() => void allocatePicked(item.va_sid)} />
                <CopyIcon label={`Copy details of ${caseTitle(item.va_uniqueid_masked)}`} message={reviewedCaseSupportText(item)} />
              </View>
            </QueueCaseCard>
          ))}
          {(projects as CoderProjects | undefined)?.station_coding_disabled ? <Text style={styles.muted} testID="coding-done-on-server">{t("codingDoneOnServer")}</Text> : null}
          {showList && coderCount === 0 ? <Text style={styles.muted}>{showHistory ? "No coded cases yet." : pickMode ? "No cases to pick right now." : "No available cases on this page."}</Text> : null}
          {(coderCount ?? 0) > 0 && filteredCount === 0 ? <Text style={styles.muted}>No cases match your filters.</Text> : null}
          {showList && showPager ? <View style={q.pager}>
            <Button label="Previous" kind="secondary" size="sm" style={q.pagerBtn} disabled={busy || loading || offset === 0} onPress={() => { clearMessage(); setOffset(Math.max(0, offset - PAGE_SIZE)); }} />
            <Text style={q.pageText}>Page {Math.floor(offset / PAGE_SIZE) + 1}</Text>
            <Button label="Next" kind="secondary" size="sm" style={q.pagerBtn} disabled={busy || loading || offset >= MAX_OFFSET || !canGoNext} onPress={() => { clearMessage(); setOffset(Math.min(MAX_OFFSET, offset + PAGE_SIZE)); }} />
          </View> : null}
        </View>
      ) : (
        <View style={phone ? { gap: controls.gap } : styles.card}>
          {headBlock(<>
          {/* As Coding: no card title under the page title; the refresh icon shares the languages row. */}
          <View style={q.titleRow}>
            <View style={{ flex: 1, minWidth: 0 }}>{renderLanguageLines()}</View>
            <RefreshIcon disabled={busy || loading} loading={loading} onPress={refreshCases} />
          </View>
          {reviewerStats ? (
            <View style={q.statsGrid}>
              {statTile(String(reviewerStats.available ?? 0), "Available to review", false)}
              {/* Pending coding (owner 2026-11-27); an older server without it keeps In scope. */}
              {typeof reviewerStats.pending_coding === "number" ? statTile(reviewerStats.pending_coding, t("queuePendingCoding"))
                : typeof reviewerStats.in_scope === "number" ? statTile(reviewerStats.in_scope, "In scope") : null}
              {statTile(String(reviewerStats.completed ?? 0), t("queueReviewedByMe"), true)}
            </View>
          ) : null}
          {tabs("My reviewed cases")}
          {renderFilterControls()}
          </>)}
          {filteredReviewerRows.map((item) => (
            <QueueCaseCard key={item.va_sid} item={item} kind={showHistory ? "reviewHistory" : "review"} allProjects={projectId === undefined}>
              {showHistory ? (
                <View style={q.cardActions}>
                  <Button label="View case" kind="secondary" size="sm" style={q.cardBtn} disabled={busy || loading} onPress={() => openCurrent({ vaSid: item.va_sid, mode: "view" })} />
                  <CopyIcon label={`Copy details of ${caseTitle(item.va_uniqueid_masked)}`} message={reviewedCaseSupportText(item)} />
                </View>
              ) : (
                <View style={q.cardActions}>
                  <Button label="Review case" size="sm" style={q.cardBtn} disabled={busy || loading || !allocationVerified || Boolean(allocation)} loading={busy} onPress={() => void allocateReviewer(item.va_sid)} />
                  <CopyIcon label={`Copy details of ${caseTitle(item.va_uniqueid_masked)}`} message={reviewedCaseSupportText(item)} />
                </View>
              )}
            </QueueCaseCard>
          ))}
          {reviewerRows?.length === 0 ? <Text style={styles.muted}>{reviewerEmptyText()}</Text> : null}
          {(reviewerRows?.length ?? 0) > 0 && filteredReviewerRows.length === 0 ? <Text style={styles.muted}>No cases match your filters.</Text> : null}
          {showPager ? <View style={q.pager}>
            <Button label="Previous" kind="secondary" size="sm" style={q.pagerBtn} disabled={busy || loading || offset === 0} onPress={() => { clearMessage(); setOffset(Math.max(0, offset - PAGE_SIZE)); }} />
            <Text style={q.pageText}>Page {Math.floor(offset / PAGE_SIZE) + 1}</Text>
            <Button label="Next" kind="secondary" size="sm" style={q.pagerBtn} disabled={busy || loading || offset >= MAX_OFFSET || !canGoNext} onPress={() => { clearMessage(); setOffset(Math.min(MAX_OFFSET, offset + PAGE_SIZE)); }} />
          </View> : null}
        </View>
      )}
      {confirmRelease ? <ConfirmDialog
        destructive
        title={t("releaseCaseTitle")}
        message={confirmRelease.warning}
        cancelLabel={t("codeNowKeepCase")}
        confirmLabel={t("releaseCaseAction")}
        onCancel={() => setConfirmRelease(null)}
        onConfirm={() => {
          const pending = confirmRelease;
          setConfirmRelease(null);
          pending.proceed();
        }}
      /> : null}
    </ActiveShell>
  );
}
