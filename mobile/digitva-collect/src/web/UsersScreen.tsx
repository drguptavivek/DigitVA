import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Image, Modal, Pressable, StyleSheet, Text, TextInput, useWindowDimensions, View } from "react-native";

import { useAppState } from "../AppState";
import { t, type StringKey } from "../i18n";
import type { OrgProject } from "../organization/api";
import { controls, radius, spacing, typography, useTheme } from "../theme";
import { Button, useUiStyles } from "../ui";
import { RoleChip, RoleChips, RoleSentence } from "../ui/RoleChip";
import {
  activeFilterCount, DEFAULT_FILTERS, emailEnrolmentCode, enrolmentProjects, filtersFromSearch, filtersToSearch, getUserActivity,
  getUserPlacement, getUsers, issueEnrolmentCode, signInQrCandidate,
  type DirectoryOptions, type DirectoryUser, type GridUser, type IssuedCode, type UserActivity, type UserFilters, type UserGrant,
} from "../users/api";
import type { JsonRequester } from "../workspace/api";
import { createWebWorkspaceTransport } from "../workspace/transport.web";
import { ChipGroup } from "./caseFilters";
import { browserErrorText, WebShell } from "./common";
import { formatWhen } from "../ui/interviewRows";
import { AccountUpload, GrantGrid } from "./UsersAdminTools";
import { SignInQrDialog, UserStatusPanel } from "./UsersDialogs";
import { FilterSheet, FiltersButton, QuickChips } from "./UsersFilters";
import { OrgTree } from "./OrgTree";
import { roleSummary } from "./OrganizationScreen";
import { roleLabelKey } from "./roleHome";
import { useOpenedUnits } from "./useOpenedUnits";

/**
 * The Users page (digitva-75wn, digitva-x79t): everyone the server lets this viewer see (admin all, project PI their
 * projects, data manager their subtree), filtered on the server, one card per user in a responsive grid. A card shows
 * the contact, account and app state, a role tag per grant (role, project code and, for a site grant, the site code)
 * and compact actions. Selecting a user opens the user view: account status on the left, the user's place in the
 * organization tree (the My organization component) on the right. An admin also gets the grant grid and the account
 * upload (digitva-cgmc, ./UsersAdminTools).
 */

const SEARCH_DELAY_MS = 300;
const TWO_COLUMNS_MIN_WIDTH = 768;
const THREE_COLUMNS_MIN_WIDTH = 1200;

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

/** "Interviewer · HP0001", "Interviewer · HP0001 · AAM01" (site grant) or "... · <unit>" (unit grant): role, project code, site code or unit. */
export function grantTagLabel(grant: UserGrant): string {
  const place = [grant.project_id, grant.scope === "project_site" ? grant.site_id : grant.scope === "org_unit" ? grant.unit_name : null].filter(Boolean).join(" · ");
  return t("usersRoleAt", { role: t(roleLabelKey(grant.role)), place });
}

function useStyles() {
  const { colors } = useTheme();
  return useMemo(() => StyleSheet.create({
    input: {
      minHeight: controls.minHeight, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, backgroundColor: colors.surface,
      paddingHorizontal: spacing.sm, ...typography.subhead, color: colors.text, fontFamily: controls.fontFamily,
    },
    label: { ...typography.caption, fontWeight: "600", color: colors.textMuted, fontFamily: controls.fontFamily },
    grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
    cardBody: { gap: spacing.xxs },
    columns: { gap: spacing.md },
    column: { flex: 1, minWidth: 0, gap: spacing.sm },
    toolbar: { flexDirection: "row", gap: spacing.xs, alignItems: "center" },
    searchBox: { flex: 1, minWidth: 0 },
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
        {activity.last_active_at ? t("usersLastActive", { when: formatWhen(activity.last_active_at) }) : t("usersNeverActive")}
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
              <Text style={styles.muted}>{t("usersCodeOnce", { when: formatWhen(issued.expires_at), uses: issued.max_uses })}</Text>
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


type ActionProps = {
  user: DirectoryUser; open: boolean; onToggle: () => void; onIssue: () => void; onStatus?: () => void; onQr: () => void;
};

/** A card's compact actions; the user view leaves out the Details button (it is already open). */
function UserActions({ user, open, onToggle, onIssue, onStatus, onQr }: ActionProps) {
  const s = useStyles();
  return (
    <View style={s.actions}>
      <Button size="sm" kind="secondary" label={open ? t("usersHideActivity") : t("usersActivity")} expanded={open} onPress={onToggle} />
      {user.active && enrolmentProjects(user).length ? (
        <Button size="sm" kind="secondary" label={t("usersIssueCode")} accessibilityLabel={t("usersIssueCodeFor", { name: user.name })} onPress={onIssue} />
      ) : null}
      {onStatus ? (
        <Button size="sm" kind="secondary" label={t("usersDetails")} accessibilityLabel={t("usersStatusFor", { name: user.name })} onPress={onStatus} />
      ) : null}
      {signInQrCandidate(user) ? (
        <Button size="sm" kind="secondary" label={t("usersQr")} accessibilityLabel={t("usersQrFor", { name: user.name })} onPress={onQr} />
      ) : null}
    </View>
  );
}

/** One role tag per grant: the role with its project code and, for a site or unit grant, the site code or unit. */
function GrantTags({ user }: { user: DirectoryUser }) {
  const styles = useUiStyles();
  if (!user.grants.length) return <Text style={styles.muted}>{t("usersNoRoles")}</Text>;
  return (
    <RoleChips>
      {user.grants.map((grant, index) => <RoleChip key={index} role={grant.role} label={grantTagLabel(grant)} />)}
    </RoleChips>
  );
}

/** Where the user sits in each project's organization: the My organization tree, their own units named after them. */
function UserPlacement({ request, user }: { request: JsonRequester; user: Pick<DirectoryUser, "user_id" | "name"> }) {
  const styles = useUiStyles();
  const [projects, setProjects] = useState<OrgProject[]>();
  const [error, setError] = useState("");
  const { opened, toggle } = useOpenedUnits(request);
  useEffect(() => {
    let active = true;
    getUserPlacement(request, user.user_id)
      .then((rows) => { if (active) setProjects(rows); })
      .catch((caught) => { if (active) setError(browserErrorText(caught)); });
    return () => { active = false; };
  }, [request, user.user_id]);
  return (
    <View testID="user-placement" style={{ gap: spacing.sm }}>
      {error ? <Text style={styles.error} accessibilityRole="alert">{error}</Text> : null}
      {!projects && !error ? <Text style={styles.muted}>{t("loading")}</Text> : null}
      {projects && !projects.length ? <Text style={styles.muted}>{t("usersPlacementNone")}</Text> : null}
      {projects?.map((project) => (
        <View key={project.project_id} style={styles.card}>
          <Text style={styles.headline}>{t("orgProjectHeader", { name: project.project_name, code: project.project_id })}</Text>
          {roleSummary(project).map((line, index) => <RoleSentence key={index} k={line.k} params={line.params} roles={line.roles} textStyle={styles.muted} />)}
          {project.has_tree === false ? null : <OrgTree project={project} opened={opened} onToggle={(id) => void toggle(id)} subject={user.name} />}
        </View>
      ))}
    </View>
  );
}

export default function UsersScreen() {
  const { bootstrap } = useAppState();
  const styles = useUiStyles();
  const s = useStyles();
  const { colors } = useTheme();
  const width = useWindowDimensions().width;
  const wide = width >= TWO_COLUMNS_MIN_WIDTH;
  const cardBasis = width >= THREE_COLUMNS_MIN_WIDTH ? "31%" : wide ? "47%" : "100%";
  const request: JsonRequester | undefined = useMemo(
    () => (bootstrap ? createWebWorkspaceTransport(bootstrap.csrf) : undefined),
    [bootstrap],
  );
  const [filters, setFilters] = useState<UserFilters>(readUrlFilters);
  const [search, setSearch] = useState(filters.q ?? "");
  const [sheetOpen, setSheetOpen] = useState(false);
  const [selected, setSelected] = useState<DirectoryUser>();
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
  const actionsFor = (user: DirectoryUser, onStatus?: () => void) => (
    <UserActions
      user={user}
      open={openActivity === user.user_id}
      onToggle={() => toggle(user.user_id)}
      onIssue={() => setIssuing(user)}
      onStatus={onStatus}
      onQr={() => setQrFor(user)}
    />
  );
  const dialogs = (
    <>
      {issuing ? <EnrolmentDialog request={request} user={issuing} onClose={() => setIssuing(undefined)} /> : null}
      {qrFor ? <SignInQrDialog request={request} user={qrFor} onClose={() => setQrFor(undefined)} /> : null}
    </>
  );
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
        {dialogs}
      </WebShell>
    );
  }

  if (selected) {
    return (
      <WebShell title={t("usersTitle")} wide>
        <View style={s.actions}>
          <Button size="sm" kind="secondary" label={t("usersBack")} onPress={() => setSelected(undefined)} />
        </View>
        <Text style={styles.headline} accessibilityRole="header">{t("usersStatusTitle", { name: selected.name })}</Text>
        <Text style={styles.muted} selectable>{[selected.email, selected.phone].filter(Boolean).join(" · ")}</Text>
        <GrantTags user={selected} />
        {actionsFor(selected)}
        {openActivity === selected.user_id ? <ActivityPanel request={request} user={selected} /> : null}
        <View testID="user-view" style={[s.columns, wide && { flexDirection: "row", alignItems: "flex-start" }]}>
          <View testID="user-view-status" style={s.column}>
            <Text style={styles.headline} accessibilityRole="header">{t("usersStatusHeading")}</Text>
            <UserStatusPanel request={request} user={selected} />
          </View>
          <View testID="user-view-placement" style={s.column}>
            <Text style={styles.headline} accessibilityRole="header">{t("usersPlacementTitle")}</Text>
            <UserPlacement request={request} user={selected} />
          </View>
        </View>
        {dialogs}
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

      <View style={s.grid} testID="users-grid">
        {users.map((user) => (
          <View key={user.user_id} style={[styles.card, { flexBasis: cardBasis, flexGrow: 1, minWidth: 0 }]} testID="users-card">
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={t("usersOpenCard", { name: user.name })}
              onPress={() => setSelected(user)}
              style={s.cardBody}
            >
              <Text style={styles.headline}>{user.name}</Text>
              <Text style={styles.muted} selectable>{[user.email, user.phone].filter(Boolean).join(" · ")}</Text>
              <Text style={styles.muted}>{`${user.active ? t("usersActive") : t("usersInactive")} · ${enrolmentLabel(user)}`}</Text>
            </Pressable>
            <GrantTags user={user} />
            {actionsFor(user, () => setSelected(user))}
            {openActivity === user.user_id ? <ActivityPanel request={request} user={user} /> : null}
          </View>
        ))}
      </View>

      {busy ? <Text style={styles.muted}>{t("loading")}</Text> : null}
      {!busy && users.length < total ? (
        <Button kind="secondary" label={t("usersLoadMore")} onPress={() => void load(users.length)} />
      ) : null}

      {dialogs}
      {sheetOpen ? (
        <FilterSheet filters={filters} options={options} wide={wide} onChange={set} onClear={clearAll} onClose={() => setSheetOpen(false)} />
      ) : null}
    </WebShell>
  );
}
