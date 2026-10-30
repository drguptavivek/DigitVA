import { useMemo, useState } from "react";
import { Modal, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import { t, type StringKey } from "../i18n";
import { controls, radius, spacing, typography, useTheme } from "../theme";
import { Button } from "../ui";
import type { DirectoryOptions, UserFilters, YesNo } from "../users/api";
import { ChipGroup, DateField } from "./caseFilters";
import { roleLabelKey } from "./roleHome";

/**
 * The Users page filters (digitva-9npt): the fly-out (side sheet on a wide screen, bottom sheet on a phone) and the
 * quick chips above the list. Both read and write the same `UserFilters`, so they always agree; every change goes
 * to the server through the list params. The sheet is a Modal: RN-web traps focus in it and Escape calls onClose.
 */

const MAX_UNIT_CHIPS = 20;
export const ROLE_FILTERS = ["interviewer", "death_reporter", "coder", "reviewer", "data_manager", "interview_supervisor", "site_pi", "project_pi"];

type Patch = Partial<UserFilters>;

function useStyles() {
  const { colors } = useTheme();
  return useMemo(() => StyleSheet.create({
    input: {
      minHeight: controls.minHeight, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, backgroundColor: colors.surface,
      paddingHorizontal: spacing.sm, ...typography.subhead, color: colors.text, fontFamily: controls.fontFamily,
    },
    backdropSheet: { flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(0,0,0,0.5)" },
    backdropSide: { flex: 1, flexDirection: "row", justifyContent: "flex-end", backgroundColor: "rgba(0,0,0,0.35)" },
    sheet: { maxHeight: "88%", width: "100%", backgroundColor: colors.background, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, borderWidth: 1, borderColor: colors.border },
    side: { height: "100%", width: 400, maxWidth: "100%", backgroundColor: colors.background, borderLeftWidth: 1, borderColor: colors.border },
    header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.xs, padding: spacing.sm, borderBottomWidth: 1, borderColor: colors.border },
    title: { ...typography.headline, color: colors.text, fontFamily: controls.fontFamily },
    body: { padding: spacing.sm, gap: spacing.sm },
    footer: { flexDirection: "row", justifyContent: "space-between", gap: spacing.xs, padding: spacing.sm, borderTopWidth: 1, borderColor: colors.border },
    group: { gap: spacing.xxs },
    label: { ...typography.caption, fontWeight: "600", color: colors.textMuted, fontFamily: controls.fontFamily },
    pair: { flexDirection: "row", gap: spacing.xs },
    chips: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xxs, alignItems: "center" },
    chip: { paddingVertical: spacing.xxs, paddingHorizontal: spacing.sm, borderRadius: radius.full, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
    chipOn: { borderColor: colors.accent, backgroundColor: colors.accent },
    chipText: { ...typography.caption, fontWeight: "600", color: colors.textMuted, fontFamily: controls.fontFamily },
    chipTextOn: { color: colors.onAccent },
    badge: { minWidth: 20, height: 20, paddingHorizontal: 6, borderRadius: radius.full, backgroundColor: colors.accent, alignItems: "center", justifyContent: "center" },
    badgeText: { ...typography.caption, fontWeight: "700", color: colors.onAccent, fontFamily: controls.fontFamily },
    filterButton: {
      flexDirection: "row", alignItems: "center", gap: spacing.xxs, minHeight: controls.minHeight, paddingHorizontal: spacing.sm,
      borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
    },
    filterButtonText: { ...typography.subhead, fontWeight: "600", color: colors.text, fontFamily: controls.fontFamily },
  }), [colors]);
}

/** The "Filters" button with the number of filters set. */
export function FiltersButton({ count, onPress }: { count: number; onPress: () => void }) {
  const s = useStyles();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={count ? t("usersFiltersActive", { count }) : t("usersFilters")}
      onPress={onPress}
      style={s.filterButton}
      testID="users-filters-button"
    >
      <Text style={s.filterButtonText}>{t("usersFilters")}</Text>
      {count ? <View style={s.badge}><Text style={s.badgeText}>{count}</Text></View> : null}
    </Pressable>
  );
}

type Quick = { key: string; label: StringKey; on: (f: UserFilters) => boolean; patch: Patch; off: Patch };

const QUICK: Quick[] = [
  { key: "today", label: "usersChipToday", on: (f) => f.created === "today", patch: { created: "today", created_from: "", created_to: "" }, off: { created: "" } },
  { key: "yesterday", label: "usersChipYesterday", on: (f) => f.created === "yesterday", patch: { created: "yesterday", created_from: "", created_to: "" }, off: { created: "" } },
  { key: "verified", label: "usersChipVerified", on: (f) => f.email_verified === "yes", patch: { email_verified: "yes" }, off: { email_verified: "" } },
  { key: "not-verified", label: "usersChipNotVerified", on: (f) => f.email_verified === "no", patch: { email_verified: "no" }, off: { email_verified: "" } },
  { key: "enrolled", label: "usersChipEnrolled", on: (f) => f.enrolment === "enrolled", patch: { enrolment: "enrolled" }, off: { enrolment: "" } },
  { key: "revoked", label: "usersChipRevoked", on: (f) => f.enrolment === "revoked", patch: { enrolment: "revoked" }, off: { enrolment: "" } },
  { key: "none", label: "usersChipNotEnrolled", on: (f) => f.enrolment === "none", patch: { enrolment: "none" }, off: { enrolment: "" } },
];

/** Toggle chips over the list: each sets, or clears, the same param the fly-out shows. */
export function QuickChips({ filters, onChange }: { filters: UserFilters; onChange: (patch: Patch) => void }) {
  const s = useStyles();
  return (
    <View style={s.chips} accessibilityLabel={t("usersQuickFilters")} role="group">
      {QUICK.map((chip) => {
        const on = chip.on(filters);
        return (
          <Pressable
            key={chip.key}
            accessibilityRole="button"
            accessibilityLabel={t("usersChipLabel", { label: t(chip.label) })}
            accessibilityState={{ selected: on }}
            hitSlop={spacing.xs}
            onPress={() => onChange(on ? chip.off : chip.patch)}
            style={[s.chip, on && s.chipOn]}
          >
            <Text style={[s.chipText, on && s.chipTextOn]}>{t(chip.label)}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  const s = useStyles();
  return (
    <View style={s.group}>
      <Text style={s.label}>{label}</Text>
      {children}
    </View>
  );
}

export function FilterSheet({ filters, options, wide, onChange, onClear, onClose }: {
  filters: UserFilters;
  options: DirectoryOptions;
  wide: boolean;
  onChange: (patch: Patch) => void;
  onClear: () => void;
  onClose: () => void;
}) {
  const s = useStyles();
  const { colors } = useTheme();
  const [unitSearch, setUnitSearch] = useState("");
  const chipLabel = (label: string) => t("usersChipLabel", { label });
  const yesNo = (key: "email_verified" | "password_set" | "passkey") => (
    <ChipGroup<YesNo>
      options={[{ key: "", label: t("usersAll") }, { key: "yes", label: t("usersYes") }, { key: "no", label: t("usersNo") }]}
      value={filters[key] ?? ""}
      onChange={(value) => onChange({ [key]: value })}
      a11yLabel={(label) => t("usersChipLabel", { label: `${t(key === "email_verified" ? "usersFilterEmailVerified" : key === "password_set" ? "usersFilterPasswordSet" : "usersFilterPasskey")} ${label}` })}
    />
  );
  const units = useMemo(() => {
    const needle = unitSearch.trim().toLowerCase();
    const chosen = options.units.filter((u) => u.org_unit_id === filters.unit);
    const matches = options.units.filter((u) => u.org_unit_id !== filters.unit && (!needle || u.unit_name.toLowerCase().includes(needle)));
    return [...chosen, ...matches].slice(0, MAX_UNIT_CHIPS);
  }, [options.units, unitSearch, filters.unit]);

  return (
    <Modal visible transparent animationType={wide ? "fade" : "slide"} onRequestClose={onClose}>
      <View style={wide ? s.backdropSide : s.backdropSheet}>
        <Pressable accessibilityRole="button" accessibilityLabel={t("usersCodeClose")} onPress={onClose} style={StyleSheet.absoluteFill} />
        <View style={wide ? s.side : s.sheet} accessibilityViewIsModal accessibilityLabel={t("usersFiltersTitle")} role="dialog" aria-modal={true} testID={wide ? "users-filter-side" : "users-filter-bottom"}>
          <View style={s.header}>
            <Text style={s.title} accessibilityRole="header">{t("usersFiltersTitle")}</Text>
            <Button kind="secondary" size="sm" label={t("usersFiltersDone")} onPress={onClose} />
          </View>
          <ScrollView keyboardDismissMode="on-drag" contentContainerStyle={s.body} keyboardShouldPersistTaps="handled">
            {options.projects.length > 1 ? (
              <Group label={t("usersFilterProject")}>
                <ChipGroup
                  options={[{ key: "", label: t("usersAllProjects") }, ...options.projects.map((p) => ({ key: p.project_id, label: p.project_name }))]}
                  value={filters.project ?? ""}
                  onChange={(project) => onChange({ project, unit: "" })}
                  a11yLabel={chipLabel}
                />
              </Group>
            ) : null}
            {options.units.length > 0 ? (
              <Group label={t("usersFilterUnit")}>
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
                  onChange={(unit) => onChange({ unit })}
                  a11yLabel={chipLabel}
                />
              </Group>
            ) : null}
            <Group label={t("usersFilterStatus")}>
              <ChipGroup
                options={[{ key: "active", label: t("usersActive") }, { key: "inactive", label: t("usersInactive") }, { key: "all", label: t("usersAll") }]}
                value={filters.status ?? "all"}
                onChange={(status) => onChange({ status: status as UserFilters["status"] })}
                a11yLabel={chipLabel}
              />
            </Group>
            <Group label={t("usersFilterEnrolment")}>
              <ChipGroup
                options={[{ key: "", label: t("usersAll") }, { key: "enrolled", label: t("usersEnrolled") }, { key: "revoked", label: t("usersEnrolRevoked") }, { key: "none", label: t("usersEnrolNone") }]}
                value={filters.enrolment ?? ""}
                onChange={(enrolment) => onChange({ enrolment: enrolment as UserFilters["enrolment"] })}
                a11yLabel={chipLabel}
              />
            </Group>
            <Group label={t("usersFilterRole")}>
              <ChipGroup
                options={[{ key: "", label: t("usersAll") }, ...ROLE_FILTERS.map((role) => ({ key: role, label: t(roleLabelKey(role)) }))]}
                value={filters.role ?? ""}
                onChange={(role) => onChange({ role })}
                a11yLabel={chipLabel}
              />
            </Group>
            <Group label={t("usersFilterCreated")}>
              <ChipGroup
                options={[{ key: "", label: t("usersAll") }, { key: "today", label: t("usersChipToday") }, { key: "yesterday", label: t("usersChipYesterday") }]}
                value={filters.created ?? ""}
                onChange={(created) => onChange({ created: created as UserFilters["created"], created_from: "", created_to: "" })}
                a11yLabel={chipLabel}
              />
              <View style={s.pair}>
                <DateField label={t("usersFilterCreatedFrom")} value={filters.created_from ?? ""} onChange={(created_from) => onChange({ created_from, created: "" })} />
                <DateField label={t("usersFilterCreatedTo")} value={filters.created_to ?? ""} onChange={(created_to) => onChange({ created_to, created: "" })} />
              </View>
            </Group>
            <Group label={t("usersFilterEmailVerified")}>{yesNo("email_verified")}</Group>
            <Group label={t("usersFilterPasswordSet")}>{yesNo("password_set")}</Group>
            <Group label={t("usersFilterPasskey")}>{yesNo("passkey")}</Group>
          </ScrollView>
          <View style={s.footer}>
            <Button kind="secondary" label={t("usersFiltersClear")} onPress={onClear} />
            <Button label={t("usersFiltersDone")} onPress={onClose} />
          </View>
        </View>
      </View>
    </Modal>
  );
}
