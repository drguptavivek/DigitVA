import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { t, type StringKey } from "../i18n";
import { controls, radius, spacing, typography, useTheme } from "../theme";
import { Button, useUiStyles } from "../ui";
import { RoleChip, RoleChips } from "../ui/RoleChip";
import {
  applyUpload, enrolmentProjects, getGrid, GRID_ROLES, previewUpload, primaryUnit, rolesAt, saveGridRow, UPLOAD_TEMPLATE,
  type GridFilters, type GridOptions, type GridRole, type GridSave, type GridUser, type UploadFile, type UploadResult,
  type UserGrant,
} from "../users/api";
import type { JsonRequester } from "../workspace/api";
import { ChipGroup, DateField } from "./caseFilters";
import { browserErrorText } from "./common";
import { formatDisplayTimestamp } from "./DeathsList";
import { roleLabelKey } from "./roleHome";

/**
 * The Users page admin tools (digitva-cgmc): the grant grid (one project, one row per account, six role boxes at one
 * unit, Edit/Save per row) and the account upload (preview, then apply). The server refuses anyone but an admin
 * (docs/policy/access-control-model.md, "Users page admin tools").
 */

const SEARCH_DELAY_MS = 300;
const MAX_UNIT_CHIPS = 20;
const WHOLE_PROJECT = "project";

const ROLE_COLUMN: Record<GridRole, StringKey> = {
  death_reporter: "usersGridReport",
  interviewer: "usersGridInterview",
  interview_supervisor: "usersGridSupervise",
  coder: "usersGridCode",
  reviewer: "usersGridReview",
  data_manager: "usersGridManager",
};

const grantPlace = (grant: UserGrant) =>
  grant.unit_name ?? grant.site_name ?? t("usersWholeProject", { project: grant.project_name ?? grant.project_id });

/** "Role · place" for a grant (the plain text of GrantView, used for labels). */
export function grantLine(grant: UserGrant): string {
  return t("usersRoleAt", { role: t(roleLabelKey(grant.role)), place: grantPlace(grant) });
}

/** A grant as a role chip followed by its place. */
export function GrantView({ grant }: { grant: UserGrant }) {
  const styles = useUiStyles();
  return (
    <RoleChips>
      <RoleChip role={grant.role} />
      <Text style={styles.muted}>{grantPlace(grant)}</Text>
    </RoleChips>
  );
}

function useStyles() {
  const { colors } = useTheme();
  return useMemo(() => StyleSheet.create({
    panel: { gap: spacing.xs, padding: spacing.xs, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceMuted },
    input: {
      minHeight: controls.minHeight, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, backgroundColor: colors.surface,
      paddingHorizontal: spacing.sm, ...typography.subhead, color: colors.text, fontFamily: controls.fontFamily,
    },
    label: { ...typography.caption, fontWeight: "600", color: colors.textMuted, fontFamily: controls.fontFamily },
    dates: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
    row: { flexDirection: "row", gap: spacing.xs, paddingVertical: spacing.xs, borderBottomWidth: 1, borderColor: colors.border, alignItems: "flex-start" },
    head: { ...typography.caption, fontWeight: "700", color: colors.textMuted, fontFamily: controls.fontFamily },
    cell: { flex: 1, minWidth: 0, gap: spacing.xxs },
    wideCell: { flex: 2, minWidth: 0, gap: spacing.xxs },
    boxCell: { width: 64, alignItems: "center" },
    boxes: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
    choice: { flexDirection: "row", alignItems: "center", gap: spacing.xxs, minHeight: 32 },
    box: { width: 18, height: 18, borderWidth: 2, borderColor: colors.borderStrong, borderRadius: radius.sm, backgroundColor: colors.surface },
    boxOn: { backgroundColor: colors.accent, borderColor: colors.accent },
    boxOff: { opacity: 0.5 },
    actions: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
  }), [colors]);
}

function RoleBox({ role, checked, editable, onToggle, name }: { role: GridRole; checked: boolean; editable: boolean; onToggle: () => void; name: string }) {
  const s = useStyles();
  const styles = useUiStyles();
  return (
    <Pressable
      accessibilityRole="checkbox"
      accessibilityState={{ checked, disabled: !editable }}
      accessibilityLabel={t("usersGridRoleFor", { role: t(ROLE_COLUMN[role]), name })}
      disabled={!editable}
      onPress={onToggle}
      style={s.choice}
      testID={`grid-role-${role}`}
    >
      <View style={[s.box, checked && s.boxOn, !editable && s.boxOff]} />
      <RoleChip role={role} label={t(ROLE_COLUMN[role])} />
    </Pressable>
  );
}

type UnitChoice = { key: string; label: string };

function GridRow({ user, projectId, units, options, request, wide, onSaved, onIssue }: {
  user: GridUser;
  projectId: string;
  units: UnitChoice[];
  options: GridOptions;
  request: JsonRequester;
  wide: boolean;
  onSaved: (user: GridUser) => void;
  onIssue: (user: GridUser) => void;
}) {
  const styles = useUiStyles();
  const s = useStyles();
  const { colors } = useTheme();
  const initialUnit = primaryUnit(user, units[0]?.key ?? WHOLE_PROJECT);
  const [editing, setEditing] = useState(false);
  const [unit, setUnit] = useState(initialUnit);
  const [roles, setRoles] = useState<GridRole[]>(rolesAt(user, initialUnit));
  const [name, setName] = useState(user.name);
  const [phone, setPhone] = useState(user.phone ?? "");
  const [active, setActive] = useState(user.active);
  const [cadre, setCadre] = useState("");
  const [unitSearch, setUnitSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notes, setNotes] = useState<string[]>([]);

  function reset() {
    const next = primaryUnit(user, units[0]?.key ?? WHOLE_PROJECT);
    setUnit(next);
    setRoles(rolesAt(user, next));
    setName(user.name);
    setPhone(user.phone ?? "");
    setActive(user.active);
    setCadre("");
    setError("");
  }

  function chooseUnit(next: string) {
    setUnit(next);
    setRoles(rolesAt(user, next));
  }

  const toggle = (role: GridRole) => setRoles((current) => (current.includes(role) ? current.filter((r) => r !== role) : [...current, role]));

  async function save() {
    const body: GridSave = { project_id: projectId, unit, roles: GRID_ROLES.filter((r) => roles.includes(r)) };
    if (name.trim() !== user.name) body.name = name.trim();
    if (phone.trim() !== (user.phone ?? "")) body.phone = phone.trim();
    if (active !== user.active) body.active = active;
    if (cadre) body.cadre_id = cadre;
    setBusy(true);
    setError("");
    setNotes([]);
    try {
      const result = await saveGridRow(request, user.user_id, body);
      const sent: string[] = [];
      if (result.invited) sent.push(t("usersGridInvited"));
      if (result.enrolment_email === "sent") sent.push(t("usersGridEnrolmentSent"));
      setNotes([...sent, ...result.warnings]);
      setEditing(false);
      onSaved(result.user);
    } catch (caught) {
      setError(browserErrorText(caught));
    } finally {
      setBusy(false);
    }
  }

  const unitLabel = units.find((u) => u.key === unit)?.label ?? unit;
  const elsewhere = user.grants.filter((g) => g.unit !== unit || !(GRID_ROLES as readonly string[]).includes(g.role));
  const shownUnits = useMemo(() => {
    const needle = unitSearch.trim().toLowerCase();
    const chosen = units.filter((u) => u.key === unit);
    const matches = units.filter((u) => u.key !== unit && (!needle || u.label.toLowerCase().includes(needle)));
    return [...chosen, ...matches].slice(0, MAX_UNIT_CHIPS);
  }, [units, unit, unitSearch]);
  const chipLabel = (label: string) => t("usersChipLabel", { label });

  const boxes = GRID_ROLES.map((role) => (
    <RoleBox key={role} role={role} name={user.name} checked={editing ? roles.includes(role) : rolesAt(user, unit).includes(role)}
      editable={editing} onToggle={() => toggle(role)} />
  ));

  const editor = editing ? (
    <View style={s.panel} testID="grid-editor">
      <Text style={s.label}>{t("usersGridName")}</Text>
      <TextInput accessibilityLabel={t("usersGridName")} value={name} onChangeText={setName} style={s.input} maxLength={128} />
      <Text style={s.label}>{t("usersGridPhone")}</Text>
      <TextInput accessibilityLabel={t("usersGridPhone")} value={phone} onChangeText={setPhone} style={s.input} inputMode="tel" maxLength={15} />
      <Text style={s.label}>{t("usersGridEmailReadOnly")}</Text>
      <Text style={styles.muted} selectable>{user.email ?? ""}</Text>
      <Text style={s.label}>{t("usersFilterUnit")}</Text>
      {units.length > MAX_UNIT_CHIPS ? (
        <TextInput accessibilityLabel={t("usersUnitSearch")} placeholder={t("usersUnitSearch")} placeholderTextColor={colors.textMuted}
          value={unitSearch} onChangeText={setUnitSearch} style={s.input} />
      ) : null}
      <ChipGroup options={shownUnits} value={unit} onChange={chooseUnit} a11yLabel={chipLabel} />
      {unit.startsWith("unit:") && options.cadres.length ? (
        <>
          <Text style={s.label}>{t("usersGridCadre")}</Text>
          <ChipGroup
            options={[{ key: "", label: t("usersGridCadreKeep") }, ...options.cadres.map((c) => ({ key: c.cadre_id, label: c.cadre_name }))]}
            value={cadre}
            onChange={setCadre}
            a11yLabel={chipLabel}
          />
        </>
      ) : null}
      <Text style={s.label}>{t("usersFilterStatus")}</Text>
      <ChipGroup
        options={[{ key: "active", label: t("usersActive") }, { key: "inactive", label: t("usersInactive") }]}
        value={active ? "active" : "inactive"}
        onChange={(next) => setActive(next === "active")}
        a11yLabel={(label) => t("usersGridRoleFor", { role: label, name: user.name })}
      />
    </View>
  ) : null;

  const rowActions = (
    <View style={s.actions}>
      {editing ? (
        <>
          <Button size="sm" label={t("usersGridSave")} accessibilityLabel={t("usersGridSaveFor", { name: user.name })} loading={busy} onPress={() => void save()} />
          <Button size="sm" kind="secondary" label={t("usersGridCancel")} disabled={busy} onPress={() => { reset(); setEditing(false); }} />
        </>
      ) : (
        <Button size="sm" kind="secondary" label={t("usersGridEdit")} accessibilityLabel={t("usersGridEditFor", { name: user.name })} onPress={() => { reset(); setEditing(true); }} />
      )}
      {user.active && enrolmentProjects({ ...user, last_signed_in_at: null }).length ? (
        <Button size="sm" kind="secondary" label={t("usersIssueCode")} accessibilityLabel={t("usersIssueCodeFor", { name: user.name })} onPress={() => onIssue(user)} />
      ) : null}
    </View>
  );

  const status = `${user.active ? t("usersActive") : t("usersInactive")} · ${user.enrolment.status === "enrolled" ? t("usersEnrolled") : user.enrolment.status === "revoked" ? t("usersEnrolRevoked") : t("usersEnrolNone")}`;
  const hints = elsewhere.length ? (
    <View>
      <Text style={s.label}>{t("usersGridElsewhere")}</Text>
      {elsewhere.map((g, i) => <GrantView key={i} grant={g} />)}
    </View>
  ) : null;
  const feedback = (
    <>
      {error ? <Text style={styles.error} accessibilityRole="alert">{error}</Text> : null}
      {notes.map((note, i) => <Text key={i} style={styles.muted} accessibilityRole="alert">{note}</Text>)}
    </>
  );

  if (wide) {
    return (
      <View testID="grid-row">
        <View style={s.row}>
          <View style={s.cell}>
            <Text style={styles.text}>{user.name}</Text>
            {user.email ? <Text style={styles.muted} selectable>{user.email}</Text> : null}
            {user.created_at ? <Text style={styles.muted}>{t("usersGridCreated", { when: formatDisplayTimestamp(user.created_at) })}</Text> : null}
          </View>
          <View style={s.cell}><Text style={styles.muted}>{unitLabel}</Text>{hints}</View>
          <View style={[s.wideCell, s.boxes]}>{boxes}</View>
          <View style={s.cell}><Text style={styles.muted}>{status}</Text>{rowActions}</View>
        </View>
        {editor}
        {feedback}
      </View>
    );
  }
  return (
    <View style={styles.card} testID="grid-card">
      <Text style={styles.headline}>{user.name}</Text>
      {user.email ? <Text style={styles.muted} selectable>{user.email}</Text> : null}
      {user.created_at ? <Text style={styles.muted}>{t("usersGridCreated", { when: formatDisplayTimestamp(user.created_at) })}</Text> : null}
      <Text style={styles.muted}>{unitLabel}</Text>
      <View style={s.boxes}>{boxes}</View>
      <Text style={styles.muted}>{status}</Text>
      {hints}
      {editor}
      {rowActions}
      {feedback}
    </View>
  );
}

const ROLE_FILTERS = [...GRID_ROLES, "site_pi", "project_pi"];

/** The grant grid for one chosen project. */
export function GrantGrid({ request, projects, wide, onIssue }: {
  request: JsonRequester;
  projects: { project_id: string; project_name: string }[];
  wide: boolean;
  onIssue: (user: GridUser) => void;
}) {
  const styles = useUiStyles();
  const s = useStyles();
  const { colors } = useTheme();
  const [filters, setFilters] = useState<GridFilters>({ project: "", from: "", to: "", q: "", role: "", status: "all" });
  const [search, setSearch] = useState("");
  const [users, setUsers] = useState<GridUser[]>([]);
  const [total, setTotal] = useState(0);
  const [options, setOptions] = useState<GridOptions>({ mode: "organization", units: [], cadres: [] });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);

  useEffect(() => {
    const timer = setTimeout(() => setFilters((current) => (current.q === search ? current : { ...current, q: search })), SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [search]);

  const load = useCallback(async (offset: number) => {
    if (!filters.project) return;
    const mine = ++generation.current;
    setBusy(true);
    setError("");
    try {
      const page = await getGrid(request, filters, offset);
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

  const set = (patch: Partial<GridFilters>) => setFilters((current) => ({ ...current, ...patch }));
  const chipLabel = (label: string) => t("usersChipLabel", { label });
  const units: UnitChoice[] = useMemo(
    () => [{ key: WHOLE_PROJECT, label: t("usersGridWholeProject") }, ...options.units.map((u) => ({ key: u.key, label: u.label }))],
    [options.units],
  );

  return (
    <View style={{ gap: spacing.sm }} testID="grant-grid">
      <View style={s.panel}>
        <Text style={s.label}>{t("usersFilterProject")}</Text>
        <ChipGroup
          options={projects.map((p) => ({ key: p.project_id, label: p.project_name }))}
          value={filters.project}
          onChange={(project) => { setUsers([]); set({ project }); }}
          a11yLabel={chipLabel}
        />
        {filters.project ? (
          <>
            <TextInput
              accessibilityLabel={t("usersGridSearchLabel")}
              placeholder={t("usersGridSearchPlaceholder")}
              placeholderTextColor={colors.textMuted}
              value={search}
              onChangeText={setSearch}
              style={s.input}
            />
            <View style={s.dates}>
              <DateField label={t("usersGridCreatedFrom")} value={filters.from ?? ""} onChange={(from) => set({ from })} />
              <DateField label={t("usersGridCreatedTo")} value={filters.to ?? ""} onChange={(to) => set({ to })} />
            </View>
            <Text style={s.label}>{t("usersFilterRole")}</Text>
            <ChipGroup
              options={[{ key: "", label: t("usersAll") }, ...ROLE_FILTERS.map((role) => ({ key: role, label: t(roleLabelKey(role)) }))]}
              value={filters.role ?? ""}
              onChange={(role) => set({ role })}
              a11yLabel={chipLabel}
            />
            <Text style={s.label}>{t("usersFilterStatus")}</Text>
            <ChipGroup
              options={[{ key: "all", label: t("usersAll") }, { key: "active", label: t("usersActive") }, { key: "inactive", label: t("usersInactive") }]}
              value={filters.status ?? "all"}
              onChange={(status) => set({ status: status as GridFilters["status"] })}
              a11yLabel={chipLabel}
            />
          </>
        ) : null}
      </View>

      {!filters.project ? <Text style={styles.muted}>{t("usersGridChooseProject")}</Text> : null}
      {error ? <Text style={styles.error} accessibilityRole="alert">{error}</Text> : null}
      {filters.project && !busy && !error && users.length === 0 ? <Text style={styles.muted}>{t("usersNone")}</Text> : null}
      {users.length ? <Text style={styles.muted}>{t("usersCount", { shown: users.length, total })}</Text> : null}
      {options.mode === "sites" && filters.project ? <Text style={styles.muted}>{t("usersGridSitesNote")}</Text> : null}

      {wide && users.length ? (
        <View testID="grid-table">
          <View style={s.row}>
            {(["usersColName", "usersGridColUnit", "usersColRoles", "usersColStatus"] as StringKey[]).map((key) => (
              <Text key={key} style={[s.head, key === "usersColRoles" ? s.wideCell : s.cell]}>{t(key)}</Text>
            ))}
          </View>
          {users.map((user) => (
            <GridRow key={user.user_id} user={user} projectId={filters.project} units={units} options={options} request={request} wide
              onSaved={(next) => setUsers((current) => current.map((u) => (u.user_id === next.user_id ? next : u)))} onIssue={onIssue} />
          ))}
        </View>
      ) : null}
      {!wide ? users.map((user) => (
        <GridRow key={user.user_id} user={user} projectId={filters.project} units={units} options={options} request={request} wide={false}
          onSaved={(next) => setUsers((current) => current.map((u) => (u.user_id === next.user_id ? next : u)))} onIssue={onIssue} />
      )) : null}

      {busy ? <Text style={styles.muted}>{t("loading")}</Text> : null}
      {!busy && users.length < total ? <Button kind="secondary" label={t("usersLoadMore")} onPress={() => void load(users.length)} /> : null}
    </View>
  );
}

/** Ask the browser for a .csv or .xlsx and read it as base64; undefined when cancelled. */
export function pickUploadFile(): Promise<UploadFile | undefined> {
  return new Promise((resolve) => {
    if (typeof document === "undefined") return resolve(undefined);
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".csv,.xlsx";
    input.onchange = () => {
      const file = input.files?.[0];
      if (!file) return resolve(undefined);
      const reader = new FileReader();
      reader.onload = () => {
        const url = String(reader.result ?? "");
        resolve({ filename: file.name, content: url.slice(url.indexOf(",") + 1) });
      };
      reader.onerror = () => resolve(undefined);
      reader.readAsDataURL(file);
    };
    input.click();
  });
}

function downloadTemplate() {
  if (typeof document === "undefined" || typeof URL.createObjectURL !== "function") return;
  const url = URL.createObjectURL(new Blob([UPLOAD_TEMPLATE], { type: "text/csv" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "digitva-accounts.csv";
  link.click();
  URL.revokeObjectURL(url);
}

const STATUS_LABEL: Record<UploadRow["status"], StringKey> = { new: "usersUploadNew", exists: "usersUploadExists", invalid: "usersUploadInvalid" };
type UploadRow = UploadResult["rows"][number];

/** Account upload: choose a file, preview every row, then create the new ones. */
export function AccountUpload({ request, pickFile = pickUploadFile }: { request: JsonRequester; pickFile?: () => Promise<UploadFile | undefined> }) {
  const styles = useUiStyles();
  const s = useStyles();
  const [file, setFile] = useState<UploadFile>();
  const [result, setResult] = useState<UploadResult>();
  const [applied, setApplied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (caught) {
      setError(browserErrorText(caught));
    } finally {
      setBusy(false);
    }
  }

  const choose = () => run(async () => {
    const picked = await pickFile();
    if (!picked) return;
    setFile(picked);
    setApplied(false);
    setResult(await previewUpload(request, picked));
  });
  const apply = () => run(async () => {
    if (!file) return;
    setResult(await applyUpload(request, file));
    setApplied(true);
  });

  return (
    <View style={{ gap: spacing.sm }} testID="account-upload">
      <Text style={styles.muted}>{t("usersUploadHelp")}</Text>
      <View style={s.actions}>
        <Button kind="secondary" label={t("usersUploadTemplate")} onPress={downloadTemplate} />
        <Button label={t("usersUploadChoose")} loading={busy && !result} disabled={busy} onPress={() => void choose()} />
      </View>
      {error ? <Text style={styles.error} accessibilityRole="alert">{error}</Text> : null}
      {result ? (
        <>
          <Text style={styles.text}>
            {applied
              ? t("usersUploadCreated", { count: result.created ?? 0 })
              : t("usersUploadCounts", { new: result.counts.new, exists: result.counts.exists, invalid: result.counts.invalid })}
          </Text>
          {result.rows.map((row) => (
            <View key={row.row} style={s.row} testID="upload-row">
              <Text style={[styles.muted, { width: 48 }]}>{row.row}</Text>
              <Text style={[styles.text, s.cell]}>{row.name}</Text>
              <Text style={[styles.muted, s.cell]} selectable>{row.email}</Text>
              <Text style={[styles.muted, s.cell]}>{row.phone ?? ""}</Text>
              <Text style={[row.status === "invalid" ? styles.error : styles.muted, s.cell]}>
                {[t(STATUS_LABEL[row.status]), row.reason, row.phone_clash ? t("usersUploadPhoneClash") : null].filter(Boolean).join(" · ")}
              </Text>
            </View>
          ))}
          {!applied ? (
            <Button
              label={t("usersUploadApply", { count: result.counts.new })}
              disabled={busy || result.counts.new === 0}
              loading={busy}
              onPress={() => void apply()}
            />
          ) : null}
        </>
      ) : null}
    </View>
  );
}
