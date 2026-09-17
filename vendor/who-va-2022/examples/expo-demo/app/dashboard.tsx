import { useRouter, type Href } from "expo-router";
import { useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";

import { DemoChrome, EmptyState, ScreenHeader, ScreenScroll, styles } from "../components/DemoLayout";
import {
  countAnswers,
  formatDateTime,
  useDemoState,
  type CompletedSubmission,
  type RegisteredUser
} from "../components/DemoState";

type DashboardStatus = "pending" | "drafted" | "final";
type DashboardAction = "open" | "push" | "none";

interface DashboardEntry {
  id: string;
  title: string;
  userId: string;
  status: DashboardStatus;
  updatedAt: string;
  answers: number;
  action: DashboardAction;
  actionLabel: string;
  route?: Href;
  completedSubmissionId?: string;
  syncStatus?: "pending" | "pushed";
}

interface UserDashboard {
  user: RegisteredUser | { userId: string; name: string; email: string };
  entries: DashboardEntry[];
  pending: number;
  drafted: number;
  final: number;
}

const statusLabel: Record<DashboardStatus, string> = {
  pending: "Pending",
  drafted: "Drafted",
  final: "Final"
};

function caseUidFromCompleted(submission: CompletedSubmission): string | undefined {
  const caseUid = submission.result.data.__caseUid;
  return typeof caseUid === "string" ? caseUid : submission.caseEntry?.uid;
}

function userLabel(user: UserDashboard["user"]): string {
  return user.name || user.email || user.userId;
}

function syncUserLabel(user: RegisteredUser): string {
  return `${user.email} (${user.userId})`;
}

export default function DashboardRoute() {
  const router = useRouter();
  const { cases, completed, currentUser, drafts, pushToServer, syncFromServer, users } = useDemoState();
  const [pushMessage, setPushMessage] = useState("");
  const [pushFailed, setPushFailed] = useState(false);
  const [syncFailed, setSyncFailed] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [activeEntryId, setActiveEntryId] = useState<string | undefined>();
  const [pushApiBaseUrl, setPushApiBaseUrl] = useState("");
  const userMap = new Map<string, UserDashboard["user"]>();
  for (const user of users) userMap.set(user.userId, user);
  if (currentUser) userMap.set(currentUser.userId, currentUser);

  const allCasesByUid = new Map(cases.map((entry) => [entry.uid, entry]));
  const visibleCases = currentUser ? cases.filter((entry) => entry.userId === currentUser.userId) : [];
  const visibleCompleted = currentUser
    ? completed.filter((submission) => {
        const caseUid = caseUidFromCompleted(submission);
        const submissionUserId = submission.userId ?? (caseUid ? allCasesByUid.get(caseUid)?.userId : undefined);
        return submissionUserId === currentUser.userId;
      })
    : [];

  const latestCompletedByCaseUid = new Map<string, CompletedSubmission>();
  const orphanCompleted: CompletedSubmission[] = [];
  for (const submission of visibleCompleted) {
    const caseUid = caseUidFromCompleted(submission);
    if (!caseUid) {
      orphanCompleted.push(submission);
      continue;
    }
    const previous = latestCompletedByCaseUid.get(caseUid);
    if (!previous || new Date(submission.completedAt).getTime() > new Date(previous.completedAt).getTime()) {
      latestCompletedByCaseUid.set(caseUid, submission);
    }
  }

  const draftById = new Map(drafts.map((draft) => [draft.id, draft]));
  const caseUids = new Set(visibleCases.map((entry) => entry.uid));
  const entries: DashboardEntry[] = [];

  for (const entry of visibleCases) {
    const matchingDraft = draftById.get(entry.uid);
    const matchingCompleted = latestCompletedByCaseUid.get(entry.uid);
    const isFinal = Boolean(matchingCompleted);
    const syncStatus = matchingCompleted?.syncStatus;
    entries.push({
      id: entry.uid,
      title: entry.caseEntry.deceasedFullName || entry.uid,
      userId: entry.userId,
      status: isFinal ? "final" : matchingDraft ? "drafted" : "pending",
      updatedAt: matchingCompleted?.completedAt ?? matchingDraft?.updatedAt ?? entry.updatedAt,
      answers: matchingCompleted
        ? Object.keys(matchingCompleted.result.data).length
        : matchingDraft
          ? countAnswers(matchingDraft)
          : 0,
      action: isFinal && syncStatus === "pending" ? "push" : "open",
      actionLabel:
        isFinal && syncStatus === "pending"
          ? "Push data"
          : isFinal
            ? "Update form"
            : matchingDraft
              ? "Complete task"
              : "Start form",
      completedSubmissionId: matchingCompleted?.id,
      route: { pathname: "/start", params: { caseUid: entry.uid } },
      syncStatus
    });
  }

  for (const [caseUid, submission] of latestCompletedByCaseUid) {
    if (caseUids.has(caseUid)) continue;
    const canOpen = Boolean(submission.caseEntry);
    entries.push({
      id: caseUid,
      title: submission.caseEntry?.deceasedFullName || `Final ${caseUid}`,
      userId: submission.userId ?? currentUser?.userId ?? "unknown-user",
      status: "final",
      updatedAt: submission.completedAt,
      answers: Object.keys(submission.result.data).length,
      action: submission.syncStatus === "pending" ? "push" : canOpen ? "open" : "none",
      actionLabel:
        submission.syncStatus === "pending"
          ? "Push data"
          : canOpen
            ? "Update form"
            : "No local case to update",
      completedSubmissionId: submission.id,
      route: canOpen ? { pathname: "/start", params: { caseUid, completedId: submission.id } } : undefined,
      syncStatus: submission.syncStatus
    });
  }

  for (const draft of drafts) {
    if (currentUser && !caseUids.has(draft.id)) continue;
    if (caseUids.has(draft.id)) continue;
    const fallbackUserId = currentUser?.userId ?? "unknown-user";
    entries.push({
      id: draft.id,
      title: `Draft ${draft.id}`,
      userId: fallbackUserId,
      status: "drafted",
      updatedAt: draft.updatedAt,
      answers: countAnswers(draft),
      action: "open",
      actionLabel: "Complete task",
      route: { pathname: "/continue", params: { draftId: draft.id } }
    });
  }

  for (const submission of orphanCompleted) {
    entries.push({
      id: submission.id,
      title: submission.caseEntry?.deceasedFullName || `Final ${submission.id}`,
      userId: submission.userId ?? currentUser?.userId ?? "unknown-user",
      status: "final",
      updatedAt: submission.completedAt,
      answers: Object.keys(submission.result.data).length,
      action: submission.syncStatus === "pending" ? "push" : "none",
      actionLabel: submission.syncStatus === "pending" ? "Push data" : "No local case to update",
      completedSubmissionId: submission.id,
      syncStatus: submission.syncStatus
    });
  }

  const dashboards = [...entries]
    .sort((left, right) => new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime())
    .reduce<UserDashboard[]>((groups, entry) => {
      let group = groups.find((candidate) => candidate.user.userId === entry.userId);
      if (!group) {
        const user = userMap.get(entry.userId) ?? {
          userId: entry.userId,
          name: entry.userId === "unknown-user" ? "Unknown user" : entry.userId,
          email: ""
        };
        group = { user, entries: [], pending: 0, drafted: 0, final: 0 };
        groups.push(group);
      }
      group.entries.push(entry);
      group[entry.status] += 1;
      return groups;
    }, []);
  const totals = dashboards.reduce(
    (summary, dashboard) => {
      summary.pending += dashboard.pending;
      summary.drafted += dashboard.drafted;
      summary.final += dashboard.final;
      return summary;
    },
    { pending: 0, drafted: 0, final: 0 }
  );

  const openEntryForm = (entry: DashboardEntry) => {
    if (entry.route) router.push(entry.route);
  };

  const runServerSync = () => {
    setIsSyncing(true);
    setSyncFailed(false);
    setPushMessage("Syncing server records...");
    void syncFromServer(pushApiBaseUrl)
      .then((result) => {
        setPushMessage(
          result.fetched
            ? `Found ${result.fetched} server records; imported ${result.imported}; skipped ${result.skipped}.${
                result.errors[0] ? ` ${result.errors[0]}` : ""
              }`
            : currentUser
              ? `No server records found for ${syncUserLabel(currentUser)}.`
              : "No server records found for this user."
        );
      })
      .catch((error: unknown) => {
        setSyncFailed(true);
        setPushMessage((error as Error).message);
      })
      .finally(() => {
        setIsSyncing(false);
      });
  };

  const runEntryAction = (entry: DashboardEntry) => {
    if (entry.action === "open") {
      openEntryForm(entry);
      return;
    }
    if (entry.action !== "push" || !entry.completedSubmissionId) return;
    setActiveEntryId(entry.id);
    setPushFailed(false);
    setPushMessage(`Pushing ${entry.title}...`);
    void pushToServer(pushApiBaseUrl, [entry.completedSubmissionId])
      .then((result) => {
        setPushFailed(result.failed > 0);
        setPushMessage(`Pushed ${result.pushed}. ${result.skipped} skipped. ${result.failed} failed.`);
      })
      .catch((error: unknown) => {
        setPushFailed(true);
        setPushMessage((error as Error).message);
      })
      .finally(() => {
        setActiveEntryId(undefined);
      });
  };

  return (
    <DemoChrome>
      <ScreenScroll>
        <ScreenHeader title="Dashboard" />
        <View style={styles.actionStack}>
          <Text style={styles.fieldLabel}>Server URL</Text>
          <TextInput
            autoCapitalize="none"
            keyboardType="url"
            onChangeText={setPushApiBaseUrl}
            placeholder="http://192.168.0.178:5173"
            style={styles.textInput}
            value={pushApiBaseUrl}
          />
          <Pressable
            accessibilityRole="button"
            disabled={!currentUser || isSyncing}
            onPress={runServerSync}
            style={[styles.smallPrimaryButton, (!currentUser || isSyncing) && styles.disabledButton]}
          >
            <Text style={styles.smallPrimaryButtonText}>{isSyncing ? "Syncing..." : "Sync from server"}</Text>
          </Pressable>
          {pushMessage ? (
            <Text style={pushFailed || syncFailed ? styles.pendingText : styles.validText}>
              {pushMessage}
            </Text>
          ) : null}
        </View>
        <View style={styles.dashboardTotals}>
          <View style={styles.metricBox}>
            <Text style={styles.metricValue}>{totals.pending}</Text>
            <Text style={styles.metricLabel}>Pending</Text>
          </View>
          <View style={styles.metricBox}>
            <Text style={styles.metricValue}>{totals.drafted}</Text>
            <Text style={styles.metricLabel}>Drafted</Text>
          </View>
          <View style={styles.metricBox}>
            <Text style={styles.metricValue}>{totals.final}</Text>
            <Text style={styles.metricLabel}>Final</Text>
          </View>
        </View>
        {dashboards.length === 0 ? (
          <EmptyState message="No WHO form entries are saved on this device yet." />
        ) : (
          dashboards.map((dashboard) => (
            <View key={dashboard.user.userId} style={styles.dashboardGroup}>
              <Text style={styles.listItemTitle}>{userLabel(dashboard.user)}</Text>
              <Text style={styles.listItemMeta}>{dashboard.user.email || dashboard.user.userId}</Text>
              <View style={styles.metricRow}>
                <View style={styles.metricBox}>
                  <Text style={styles.metricValue}>{dashboard.pending}</Text>
                  <Text style={styles.metricLabel}>Pending</Text>
                </View>
                <View style={styles.metricBox}>
                  <Text style={styles.metricValue}>{dashboard.drafted}</Text>
                  <Text style={styles.metricLabel}>Drafted</Text>
                </View>
                <View style={styles.metricBox}>
                  <Text style={styles.metricValue}>{dashboard.final}</Text>
                  <Text style={styles.metricLabel}>Final</Text>
                </View>
              </View>
              {dashboard.entries.map((entry) => {
                const isActive = activeEntryId === entry.id;
                return (
                  <View key={entry.id} style={styles.listItem}>
                    <Pressable
                      accessibilityRole={entry.route ? "button" : undefined}
                      disabled={!entry.route}
                      onPress={() => openEntryForm(entry)}
                      style={styles.listItemText}
                    >
                      <Text style={styles.listItemTitle}>{entry.title}</Text>
                      <Text style={styles.listItemMeta}>
                        {statusLabel[entry.status]} - Updated {formatDateTime(entry.updatedAt)}
                      </Text>
                      {entry.syncStatus ? (
                        <Text style={entry.syncStatus === "pending" ? styles.pendingText : styles.validText}>
                          {entry.syncStatus === "pending" ? "Pending server push" : "Pushed to server"}
                        </Text>
                      ) : null}
                      <Text style={styles.listItemId}>
                        {entry.answers ? `${entry.answers} answers - ` : ""}
                        {entry.id}
                      </Text>
                    </Pressable>
                    <View style={styles.dashboardRowActions}>
                      <Text
                        style={[
                          styles.statusPill,
                          entry.status === "pending" && styles.statusPillPending,
                          entry.status === "final" && styles.statusPillFinal
                        ]}
                      >
                        {statusLabel[entry.status]}
                      </Text>
                      {entry.action !== "none" ? (
                        <Pressable
                          accessibilityRole="button"
                          disabled={isActive}
                          onPress={() => runEntryAction(entry)}
                          style={[styles.smallPrimaryButton, isActive && styles.disabledButton]}
                        >
                          <Text style={styles.smallPrimaryButtonText}>
                            {isActive ? "Working..." : entry.actionLabel}
                          </Text>
                        </Pressable>
                      ) : (
                        <Text style={styles.listItemActionLabel}>{entry.actionLabel}</Text>
                      )}
                    </View>
                  </View>
                );
              })}
            </View>
          ))
        )}
      </ScreenScroll>
    </DemoChrome>
  );
}
