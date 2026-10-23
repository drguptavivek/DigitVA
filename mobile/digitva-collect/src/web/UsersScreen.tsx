import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Image, Modal, Pressable, StyleSheet, Text, TextInput, useWindowDimensions, View } from "react-native";

import { useAppState } from "../AppState";
import { t, type StringKey } from "../i18n";
import { controls, radius, spacing, typography, useTheme } from "../theme";
import { Button, useUiStyles } from "../ui";
import {
  activeFilterCount, DEFAULT_FILTERS, emailEnrolmentCode, enrolmentProjects, filtersFromSearch, filtersToSearch, getUserActivity,
  getUsers, issueEnrolmentCode, signInQrCandidate,
  type DirectoryOptions, type DirectoryUser, type GridUser, type IssuedCode, type UserActivity, type UserFilters,
} from "../users/api";
import type { JsonRequester } from "../workspace/api";
import { createWebWorkspaceTransport } from "../workspace/transport.web";
import { ChipGroup } from "./caseFilters";
import { browserErrorText, WebShell } from "./common";
import { formatDisplayTimestamp } from "./DeathsList";
import { AccountUpload, GrantGrid, grantLine } from "./UsersAdminTools";
import { SignInQrDialog, StatusDialog } from "./UsersDialogs";
import { FilterSheet, FiltersButton, QuickChips } from "./UsersFilters";

/**
 * The Users page (digitva-75wn): everyone the server lets this viewer see (admin all, project PI their projects,
 * data manager their subtree), filtered on the server, a table on a wide screen and cards on a phone. Each row opens
 * its activity (loaded on open) and, for a data collector or coder, issues an app enrolment code shown once. An admin
 * also gets the grant grid and the account upload (digitva-cgmc, ./UsersAdminTools).
 */

const WIDE_MIN_WIDTH = 768;
const SEARCH_DELAY_MS = 300;

type UsersView = "list" | "grid" | "upload";

/** The filters in the page URL (a reload or a shared link keeps them); the default view has a bare URL. */
function readUrlFilters(): UserFilters {
  return filtersFromSearch(typeof window !== "undefined" && window.location ? window.location.search : "");
}

function writeUrlFilters(filters: UserFilters) {
  if (typeof window === "undefined" || !window.location || !window.history?.replaceState) return;
  const query = filtersToSearch(filters);
  window.history.replaceState(window.history.state, "", `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash ?? ""}`);
}

function enrolmentLabel(user: DirectoryUser): string {
  const e = user.enrolment;
  if (e.status === "enrolled") return `${t("usersEnrolled")} · ${t("usersDevices", { count: e.devices })}`;
  if (e.status === "revoked") return `${t("usersEnrolRevoked")} · ${t("usersRevokedDevices", { count: e.revoked_devices })}`;
  return t("usersEnrolNone");
}

function useStyles() {
  const { colors } = useTheme();
  return useMemo(() => StyleSheet.create({
    filters: { gap: spacing.xs, padding: spacing.xs, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceMuted },
    input: {
      minHeight: controls.minHeight, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, backgroundColor: colors.surface,
      paddingHorizontal: spacing.sm, ...typography.subhead, color: colors.text, fontFamily: controls.fontFamily,
    },
    label: { ...typography.caption, fontWeight: "600", color: colors.textMuted, fontFamily: controls.fontFamily },
    row: { flexDirection: "row", gap: spacing.xs, paddingVertical: spacing.xs, borderBottomWidth: 1, borderColor: colors.border, alignItems: "flex-start" },
    head: { ...typography.caption, fontWeight: "700", color: colors.textMuted, fontFamily: controls.fontFamily },
    cell: { flex: 1, minWidth: 0, gap: spacing.xxs },
    line: { alignItems: "center" },
    nameCell: { flex: 1.2, minWidth: 0 },
    contactCell: { flex: 1.8, minWidth: 0 },
    statusCell: { width: 80 },
    appCell: { flex: 1.3, minWidth: 0 },
    actionsCell: { flexDirection: "row", gap: spacing.xs, flexShrink: 0, justifyContent: "flex-end" },
    toolbar: { flexDirection: "row", gap: spacing.xs, alignItems: "center" },
    searchBox: { flex: 1, minWidth: 0 },
    wideCell: { flex: 2, minWidth: 0, gap: spacing.xxs },
    actions: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
    counts: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
    count: { minWidth: 120, padding: spacing.xs, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
    countValue: { ...typography.headline, color: colors.text, fontFamily: controls.fontFamily },
    backdrop: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.md, backgroundColor: "rgba(0,0,0,0.5)" },
    dialog: { width: "100%", maxWidth: 420, gap: spacing.sm, padding: spacing.md, borderRadius: radius.lg, backgroundColor: colors.surface },
    qr: { width: 240, height: 240, alignSelf: "center" },
    code: { ...typography.subhead, color: colors.text, fontFamily: controls.fontFamily, textAlign: "center" },
  }), [colors]);
}

function ActivityPanel({ request, user }: { request: JsonRequester; user: DirectoryUser }) {
  const styles = useUiStyles();
  const s = useStyles();
  const [activity, setActivity] = useState<UserActivity>();
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    getUserActivity(request, user.user_id)
      .then((body) => { if (active) setActivity(body); })
      .catch((caught) => { if (active) setError(browserErrorText(caught)); });
    return () => { active = false; };
  }, [request, user.user_id]);
  if (error) return <Text style={styles.error} accessibilityRole="alert">{error}</Text>;
  if (!activity) return <Text style={styles.muted}>{t("loading")}</Text>;
  const counts: [StringKey, number][] = [
    ["usersActivityInterviews", activity.totals.interviews_submitted],
    ["usersActivityDeaths", activity.totals.deaths_reported],
    ["usersActivityDrafts", activity.totals.drafts_in_progress],
    ["usersActivityCoded", activity.totals.coded],
    ["usersActivityNotCodeable", activity.totals.not_codeable],
    ["usersActivityReviewed", activity.totals.reviewed],
  ];
  return (
    <View style={{ gap: spacing.xs }} accessibilityLabel={t("usersActivityFor", { name: user.name })}>
      <View style={s.counts}>
        {counts.map(([key, value]) => (
          <View key={key} style={s.count}>
            <Text style={s.countValue}>{value}</Text>
            <Text style={styles.muted}>{t(key)}</Text>
          </View>
        ))}
      </View>
      <Text style={styles.muted}>
        {activity.last_active_at ? t("usersLastActive", { when: formatDisplayTimestamp(activity.last_active_at) }) : t("usersNeverActive")}
      </Text>
    </View>
  );
}

function EnrolmentDialog({ request, user, onClose }: { request: JsonRequester; user: DirectoryUser; onClose: () => void }) {
  const styles = useUiStyles();
  const s = useStyles();
  const projects = enrolmentProjects(user);
  const [project, setProject] = useState(projects[0]?.project_id ?? "");
  const [busy, setBusy] = useState(false);
  const [issued, setIssued] = useState<IssuedCode>();
  const [emailed, setEmailed] = useState(false);
  const [error, setError] = useState("");

  async function run(action: "show" | "email") {
    setBusy(true);
    setError("");
    try {
      if (action === "show") setIssued(await issueEnrolmentCode(request, user.user_id, project));
      else {
        await emailEnrolmentCode(request, user.user_id, project);
        setEmailed(true);
      }
    } catch (caught) {
      setError(browserErrorText(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal visible transparent animationType="fade" onRequestClose={onClose}>
      <View style={s.backdrop}>
        <View style={s.dialog} accessibilityViewIsModal>
          <Text style={styles.headline} accessibilityRole="header">{t("usersCodeTitle", { name: user.name })}</Text>
          {issued ? (
            <>
              <Image style={s.qr} accessibilityLabel={t("usersCodeQr")} source={{ uri: `data:image/png;base64,${issued.qr_png}` }} />
              <Text style={s.code} selectable>{issued.code}</Text>
              <Text style={styles.muted}>{t("usersCodeOnce", { when: formatDisplayTimestamp(issued.expires_at), uses: issued.max_uses })}</Text>
            </>
          ) : emailed ? (
            <Text style={styles.text}>{t("usersCodeEmailed")}</Text>
          ) : (
            <>
              {projects.length > 1 ? (
                <View style={{ gap: spacing.xxs }}>
                  <Text style={s.label}>{t("usersCodeProject")}</Text>
                  <ChipGroup
                    options={projects.map((p) => ({ key: p.project_id, label: p.project_name }))}
                    value={project}
                    onChange={setProject}
                    a11yLabel={(label) => t("usersChipLabel", { label })}
                  />
                </View>
              ) : null}
              <View style={s.actions}>
                <Button label={t("usersShowCode")} loading={busy} disabled={!project} onPress={() => void run("show")} />
                {user.email ? <Button kind="secondary" label={t("usersEmailCode")} disabled={busy || !project} onPress={() => void run("email")} /> : null}
              </View>
            </>
          )}
          {error ? <Text style={styles.error} accessibilityRole="alert">{error}</Text> : null}
          <Button kind="secondary" label={t("usersCodeClose")} onPress={onClose} />
        </View>
      </View>
    </Modal>
  );
}

function UserActions({ user, open, onToggle, onIssue, onStatus, onQr }: {
  user: DirectoryUser; open: boolean; onToggle: () => void; onIssue: () => void; onStatus: () => void; onQr: () => void;
}) {
  const s = useStyles();
  return (
    <View style={s.actions}>
      <Button size="sm" kind="secondary" label={open ? t("usersHideActivity") : t("usersActivity")} expanded={open} onPress={onToggle} />
      {user.active && enrolmentProjects(user).length ? (
        <Button size="sm" kind="secondary" label={t("usersIssueCode")} accessibilityLabel={t("usersIssueCodeFor", { name: user.name })} onPress={onIssue} />
      ) : null}
      <Button size="sm" kind="secondary" label={t("usersStatus")} accessibilityLabel={t("usersStatusFor", { name: user.name })} onPress={onStatus} />
      {signInQrCandidate(user) ? (
        <Button size="sm" kind="secondary" label={t("usersQr")} accessibilityLabel={t("usersQrFor", { name: user.name })} onPress={onQr} />
      ) : null}
    </View>
  );
}

/** One line of roles (the first grant and a count); pressing it shows or hides the rest. */
function RolesCell({ user }: { user: DirectoryUser }) {
  const styles = useUiStyles();
  const [open, setOpen] = useState(false);
  const lines = user.grants.map(grantLine);
  if (!lines.length) return <Text style={styles.muted} numberOfLines={1}>{t("usersNoRoles")}</Text>;
  if (lines.length === 1) return <Text style={styles.muted} numberOfLines={1}>{lines[0]}</Text>;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={open ? t("usersHideRoles", { name: user.name }) : t("usersShowRoles", { name: user.name })}
      accessibilityState={{ expanded: open }}
      onPress={() => setOpen((current) => !current)}
    >
      {open
        ? lines.map((line, index) => <Text key={index} style={styles.muted}>{line}</Text>)
        : <Text style={styles.muted} numberOfLines={1}>{t("usersRolesMore", { summary: lines[0], count: lines.length - 1 })}</Text>}
    </Pressable>
  );
}

export default function UsersScreen() {
  const { bootstrap } = useAppState();
  const styles = useUiStyles();
  const s = useStyles();
  const { colors } = useTheme();
  const wide = useWindowDimensions().width >= WIDE_MIN_WIDTH;
  const request: JsonRequester | undefined = useMemo(
    () => (bootstrap ? createWebWorkspaceTransport(bootstrap.csrf) : undefined),
    [bootstrap],
  );
  const [filters, setFilters] = useState<UserFilters>(readUrlFilters);
  const [search, setSearch] = useState(filters.q ?? "");
  const [sheetOpen, setSheetOpen] = useState(false);
  const [statusFor, setStatusFor] = useState<DirectoryUser>();
  const [qrFor, setQrFor] = useState<DirectoryUser>();
  const [users, setUsers] = useState<DirectoryUser[]>([]);
  const [total, setTotal] = useState(0);
  const [options, setOptions] = useState<DirectoryOptions>({ projects: [], units: [] });
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [openActivity, setOpenActivity] = useState<string>();
  const [issuing, setIssuing] = useState<DirectoryUser>();
  const [view, setView] = useState<UsersView>("list");
  const isAdmin = bootstrap?.access.roles.includes("admin") ?? false;
  const generation = useRef(0);

  // The search box applies after a pause in typing.
  useEffect(() => {
    const timer = setTimeout(() => setFilters((current) => (current.q === search ? current : { ...current, q: search })), SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => { writeUrlFilters(filters); }, [filters]);

  const load = useCallback(async (offset: number) => {
    if (!request) return;
    const mine = ++generation.current;
    setBusy(true);
    setError("");
    try {
      const page = await getUsers(request, filters, offset);
      if (mine !== generation.current) return;
      setUsers((current) => (offset ? [...current, ...page.users] : page.users));
      setTotal(page.total);
      if (page.options) setOptions(page.options);
    } catch (caught) {
      if (mine === generation.current) setError(browserErrorText(caught));
    } finally {
      if (mine === generation.current) setBusy(false);
    }
  }, [request, filters]);

  useEffect(() => { void load(0); }, [load]);

  const set = (patch: Partial<UserFilters>) => setFilters((current) => ({ ...current, ...patch }));
  const clearAll = () => {
    setSearch("");
    setFilters(DEFAULT_FILTERS);
  };

  if (!bootstrap || !request) return <WebShell title={t("usersTitle")}>{null}</WebShell>;

  const toggle = (userId: string) => setOpenActivity((current) => (current === userId ? undefined : userId));

  const issueFor = (user: GridUser) => setIssuing({ ...user, last_signed_in_at: null });
  const views = isAdmin ? (
    <ChipGroup
      options={[{ key: "list", label: t("usersViewList") }, { key: "grid", label: t("usersViewGrid") }, { key: "upload", label: t("usersViewUpload") }]}
      value={view}
      onChange={(next) => setView(next as UsersView)}
      a11yLabel={(label) => t("usersViewLabel", { label })}
    />
  ) : null;

  if (isAdmin && view !== "list") {
    return (
      <WebShell title={t("usersTitle")}>
        {views}
        {view === "grid"
          ? <GrantGrid request={request} projects={options.projects} wide={wide} onIssue={issueFor} />
          : <AccountUpload request={request} />}
        {issuing ? <EnrolmentDialog request={request} user={issuing} onClose={() => setIssuing(undefined)} /> : null}
      </WebShell>
    );
  }

  return (
    <WebShell title={t("usersTitle")} wide>
      {views}
      <View style={s.toolbar}>
        <TextInput
          accessibilityLabel={t("usersSearchLabel")}
          placeholder={t("usersSearchPlaceholder")}
          placeholderTextColor={colors.textMuted}
          value={search}
          onChangeText={setSearch}
          style={[s.input, s.searchBox]}
        />
        <FiltersButton count={activeFilterCount(filters)} onPress={() => setSheetOpen(true)} />
      </View>
      <QuickChips filters={filters} onChange={set} />

      {error ? <Text style={styles.error} accessibilityRole="alert">{error}</Text> : null}
      {!busy && !error && users.length === 0 ? <Text style={styles.muted}>{t("usersNone")}</Text> : null}
      {users.length ? <Text style={styles.muted}>{t("usersCount", { shown: users.length, total })}</Text> : null}

      {wide && users.length ? (
        <View testID="users-table">
          <View style={[s.row, s.line]}>
            <Text style={[s.head, s.nameCell]}>{t("usersColName")}</Text>
            <Text style={[s.head, s.contactCell]}>{t("usersColContact")}</Text>
            <Text style={[s.head, s.wideCell]}>{t("usersColRoles")}</Text>
            <Text style={[s.head, s.statusCell]}>{t("usersColStatus")}</Text>
            <Text style={[s.head, s.appCell]}>{t("usersColApp")}</Text>
            <View style={s.actionsCell} />
          </View>
          {users.map((user) => (
            <View key={user.user_id} testID="users-row">
              <View style={[s.row, s.line]} testID="users-line">
                <Text style={[styles.text, s.nameCell]} numberOfLines={1}>{user.name}</Text>
                <Text style={[styles.muted, s.contactCell]} numberOfLines={1} selectable>{[user.email, user.phone].filter(Boolean).join(" · ")}</Text>
                <View style={s.wideCell}><RolesCell user={user} /></View>
                <Text style={[styles.muted, s.statusCell]} numberOfLines={1}>{user.active ? t("usersActive") : t("usersInactive")}</Text>
                <Text style={[styles.muted, s.appCell]} numberOfLines={1}>{enrolmentLabel(user)}</Text>
                <View style={s.actionsCell}>
                  <UserActions
                    user={user}
                    open={openActivity === user.user_id}
                    onToggle={() => toggle(user.user_id)}
                    onIssue={() => setIssuing(user)}
                    onStatus={() => setStatusFor(user)}
                    onQr={() => setQrFor(user)}
                  />
                </View>
              </View>
              {openActivity === user.user_id ? <ActivityPanel request={request} user={user} /> : null}
            </View>
          ))}
        </View>
      ) : null}

      {!wide ? users.map((user) => (
        <View key={user.user_id} style={styles.card} testID="users-card">
          <Text style={styles.headline}>{user.name}</Text>
          {user.email ? <Text style={styles.muted} selectable>{user.email}</Text> : null}
          {user.phone ? <Text style={styles.muted} selectable>{user.phone}</Text> : null}
          {user.grants.map((grant, index) => <Text key={index} style={styles.text}>{grantLine(grant)}</Text>)}
          <Text style={styles.muted}>
            {`${user.active ? t("usersActive") : t("usersInactive")} · ${enrolmentLabel(user)}`}
          </Text>
          <UserActions user={user} open={openActivity === user.user_id} onToggle={() => toggle(user.user_id)} onIssue={() => setIssuing(user)} onStatus={() => setStatusFor(user)} onQr={() => setQrFor(user)} />
          {openActivity === user.user_id ? <ActivityPanel request={request} user={user} /> : null}
        </View>
      )) : null}

      {busy ? <Text style={styles.muted}>{t("loading")}</Text> : null}
      {!busy && users.length < total ? (
        <Button kind="secondary" label={t("usersLoadMore")} onPress={() => void load(users.length)} />
      ) : null}

      {issuing ? <EnrolmentDialog request={request} user={issuing} onClose={() => setIssuing(undefined)} /> : null}
      {statusFor ? <StatusDialog request={request} user={statusFor} onClose={() => setStatusFor(undefined)} /> : null}
      {qrFor ? <SignInQrDialog request={request} user={qrFor} onClose={() => setQrFor(undefined)} /> : null}
      {sheetOpen ? (
        <FilterSheet filters={filters} options={options} wide={wide} onChange={set} onClear={clearAll} onClose={() => setSheetOpen(false)} />
      ) : null}
    </WebShell>
  );
}
