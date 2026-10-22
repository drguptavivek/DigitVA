import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Image, Modal, StyleSheet, Text, TextInput, useWindowDimensions, View } from "react-native";

import { useAppState } from "../AppState";
import { t, type StringKey } from "../i18n";
import { controls, radius, spacing, typography, useTheme } from "../theme";
import { Button, useUiStyles } from "../ui";
import {
  emailEnrolmentCode, enrolmentProjects, getUserActivity, getUsers, issueEnrolmentCode,
  type DirectoryOptions, type DirectoryUser, type IssuedCode, type UserActivity, type UserFilters, type UserGrant,
} from "../users/api";
import type { JsonRequester } from "../workspace/api";
import { createWebWorkspaceTransport } from "../workspace/transport.web";
import { ChipGroup } from "./caseFilters";
import { browserErrorText, WebShell } from "./common";
import { formatDisplayTimestamp } from "./DeathsList";
import { roleLabelKey } from "./roleHome";

/**
 * The Users page (digitva-75wn): everyone the server lets this viewer see (admin all, project PI their projects,
 * data manager their subtree), filtered on the server, a table on a wide screen and cards on a phone. Each row opens
 * its activity (loaded on open) and, for a data collector or coder, issues an app enrolment code shown once.
 */

const WIDE_MIN_WIDTH = 768;
const SEARCH_DELAY_MS = 300;
const MAX_UNIT_CHIPS = 20;
const ROLE_FILTERS = ["interviewer", "death_reporter", "coder", "reviewer", "data_manager", "interview_supervisor", "site_pi", "project_pi"];

const EMPTY_FILTERS: UserFilters = { q: "", project: "", unit: "", role: "", status: "active", enrolment: "" };

function grantLine(grant: UserGrant): string {
  const role = t(roleLabelKey(grant.role));
  const place = grant.unit_name ?? grant.site_name;
  return place ? t("usersRoleAt", { role, place }) : t("usersRoleAt", { role, place: t("usersWholeProject", { project: grant.project_name ?? grant.project_id }) });
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

function UserActions({ user, open, onToggle, onIssue }: { user: DirectoryUser; open: boolean; onToggle: () => void; onIssue: () => void }) {
  const s = useStyles();
  return (
    <View style={s.actions}>
      <Button size="sm" kind="secondary" label={open ? t("usersHideActivity") : t("usersActivity")} expanded={open} onPress={onToggle} />
      {user.active && enrolmentProjects(user).length ? (
        <Button size="sm" kind="secondary" label={t("usersIssueCode")} accessibilityLabel={t("usersIssueCodeFor", { name: user.name })} onPress={onIssue} />
      ) : null}
    </View>
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
  const [filters, setFilters] = useState<UserFilters>(EMPTY_FILTERS);
  const [search, setSearch] = useState("");
  const [unitSearch, setUnitSearch] = useState("");
  const [users, setUsers] = useState<DirectoryUser[]>([]);
  const [total, setTotal] = useState(0);
  const [options, setOptions] = useState<DirectoryOptions>({ projects: [], units: [] });
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [openActivity, setOpenActivity] = useState<string>();
  const [issuing, setIssuing] = useState<DirectoryUser>();
  const generation = useRef(0);

  // The search box applies after a pause in typing.
  useEffect(() => {
    const timer = setTimeout(() => setFilters((current) => (current.q === search ? current : { ...current, q: search })), SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [search]);

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
  const chipLabel = (label: string) => t("usersChipLabel", { label });
  const units = useMemo(() => {
    const needle = unitSearch.trim().toLowerCase();
    const chosen = options.units.filter((u) => u.org_unit_id === filters.unit);
    const matches = options.units.filter((u) => u.org_unit_id !== filters.unit && (!needle || u.unit_name.toLowerCase().includes(needle)));
    return [...chosen, ...matches].slice(0, MAX_UNIT_CHIPS);
  }, [options.units, unitSearch, filters.unit]);

  if (!bootstrap || !request) return <WebShell title={t("usersTitle")}>{null}</WebShell>;

  const toggle = (userId: string) => setOpenActivity((current) => (current === userId ? undefined : userId));

  return (
    <WebShell title={t("usersTitle")}>
      <View style={s.filters}>
        <TextInput
          accessibilityLabel={t("usersSearchLabel")}
          placeholder={t("usersSearchPlaceholder")}
          placeholderTextColor={colors.textMuted}
          value={search}
          onChangeText={setSearch}
          style={s.input}
        />
        <Text style={s.label}>{t("usersFilterStatus")}</Text>
        <ChipGroup
          options={[{ key: "active", label: t("usersActive") }, { key: "inactive", label: t("usersInactive") }, { key: "all", label: t("usersAll") }]}
          value={filters.status ?? "all"}
          onChange={(status) => set({ status: status as UserFilters["status"] })}
          a11yLabel={chipLabel}
        />
        <Text style={s.label}>{t("usersFilterEnrolment")}</Text>
        <ChipGroup
          options={[{ key: "", label: t("usersAll") }, { key: "enrolled", label: t("usersEnrolled") }, { key: "revoked", label: t("usersEnrolRevoked") }, { key: "none", label: t("usersEnrolNone") }]}
          value={filters.enrolment ?? ""}
          onChange={(enrolment) => set({ enrolment: enrolment as UserFilters["enrolment"] })}
          a11yLabel={chipLabel}
        />
        <Text style={s.label}>{t("usersFilterRole")}</Text>
        <ChipGroup
          options={[{ key: "", label: t("usersAll") }, ...ROLE_FILTERS.map((role) => ({ key: role, label: t(roleLabelKey(role)) }))]}
          value={filters.role ?? ""}
          onChange={(role) => set({ role })}
          a11yLabel={chipLabel}
        />
        {options.projects.length > 1 ? (
          <>
            <Text style={s.label}>{t("usersFilterProject")}</Text>
            <ChipGroup
              options={[{ key: "", label: t("usersAll") }, ...options.projects.map((p) => ({ key: p.project_id, label: p.project_name }))]}
              value={filters.project ?? ""}
              onChange={(project) => set({ project, unit: "" })}
              a11yLabel={chipLabel}
            />
          </>
        ) : null}
        {options.units.length > 0 ? (
          <>
            <Text style={s.label}>{t("usersFilterUnit")}</Text>
            <TextInput
              accessibilityLabel={t("usersUnitSearch")}
              placeholder={t("usersUnitSearch")}
              placeholderTextColor={colors.textMuted}
              value={unitSearch}
              onChangeText={setUnitSearch}
              style={s.input}
            />
            <ChipGroup
              options={[{ key: "", label: t("usersAll") }, ...units.map((u) => ({ key: u.org_unit_id, label: `${u.unit_name} (${u.level_name})` }))]}
              value={filters.unit ?? ""}
              onChange={(unit) => set({ unit })}
              a11yLabel={chipLabel}
            />
          </>
        ) : null}
      </View>

      {error ? <Text style={styles.error} accessibilityRole="alert">{error}</Text> : null}
      {!busy && !error && users.length === 0 ? <Text style={styles.muted}>{t("usersNone")}</Text> : null}
      {users.length ? <Text style={styles.muted}>{t("usersCount", { shown: users.length, total })}</Text> : null}

      {wide && users.length ? (
        <View testID="users-table">
          <View style={s.row}>
            {(["usersColName", "usersColContact", "usersColRoles", "usersColStatus", "usersColApp"] as StringKey[]).map((key) => (
              <Text key={key} style={[s.head, key === "usersColRoles" ? s.wideCell : s.cell]}>{t(key)}</Text>
            ))}
          </View>
          {users.map((user) => (
            <View key={user.user_id} testID="users-row">
              <View style={s.row}>
                <View style={s.cell}>
                  <Text style={styles.text}>{user.name}</Text>
                  <UserActions user={user} open={openActivity === user.user_id} onToggle={() => toggle(user.user_id)} onIssue={() => setIssuing(user)} />
                </View>
                <View style={s.cell}>
                  {user.email ? <Text style={styles.muted} selectable>{user.email}</Text> : null}
                  {user.phone ? <Text style={styles.muted} selectable>{user.phone}</Text> : null}
                </View>
                <View style={s.wideCell}>
                  {user.grants.map((grant, index) => <Text key={index} style={styles.muted}>{grantLine(grant)}</Text>)}
                </View>
                <Text style={[styles.muted, s.cell]}>{user.active ? t("usersActive") : t("usersInactive")}</Text>
                <View style={s.cell}>
                  <Text style={styles.muted}>{enrolmentLabel(user)}</Text>
                  {user.enrolment.last_seen_at ? <Text style={styles.muted}>{t("usersLastSeen", { when: formatDisplayTimestamp(user.enrolment.last_seen_at) })}</Text> : null}
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
          <UserActions user={user} open={openActivity === user.user_id} onToggle={() => toggle(user.user_id)} onIssue={() => setIssuing(user)} />
          {openActivity === user.user_id ? <ActivityPanel request={request} user={user} /> : null}
        </View>
      )) : null}

      {busy ? <Text style={styles.muted}>{t("loading")}</Text> : null}
      {!busy && users.length < total ? (
        <Button kind="secondary" label={t("usersLoadMore")} onPress={() => void load(users.length)} />
      ) : null}

      {issuing ? <EnrolmentDialog request={request} user={issuing} onClose={() => setIssuing(undefined)} /> : null}
    </WebShell>
  );
}
