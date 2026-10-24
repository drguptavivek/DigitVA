import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { useAppState } from "../AppState";
import {
  createMentorInstituteStaff,
  getMentoringSummary,
  listMentorInstituteStaff,
  removeMentorInstituteStaff,
  type CreateMentorStaffPayload,
  type MentoringInstituteSummary,
  type MentoringLanguage,
  type MentoringSummary,
  type MentorStaffMember,
} from "../api";
import { t } from "../i18n";
import { fontSize, radius, spacing, useTheme } from "../theme";
import { Button, useUiStyles } from "../ui";
import { browserErrorText, WebShell } from "./common";
import { ContextualHelpBanner } from "./ContextualHelp";
import { RoleSentence } from "../ui/RoleChip";
import { describeProjectGrantRows, openServerPage, projectActionItems } from "./roleHome";

interface InstituteRosterProps {
  institute: MentoringInstituteSummary;
  csrf: { header: string; token: string };
  languages: MentoringLanguage[];
  currentUserId: string;
  isPlatformAdmin: boolean;
}

function InstituteStaffRoster({
  institute,
  csrf,
  languages,
  currentUserId,
  isPlatformAdmin,
}: InstituteRosterProps) {
  const styles = useUiStyles();
  const theme = useTheme();

  const [staff, setStaff] = useState<MentorStaffMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [staffError, setStaffError] = useState("");
  const [staffNotice, setStaffNotice] = useState("");

  const [showAddForm, setShowAddForm] = useState(false);
  const [formName, setFormName] = useState("");
  const [formEmail, setFormEmail] = useState("");
  const [formEmailConfirm, setFormEmailConfirm] = useState("");
  const [formJobTitle, setFormJobTitle] = useState("");
  const [formPhone, setFormPhone] = useState("");
  const [selectedLanguages, setSelectedLanguages] = useState<string[]>([]);
  const [formBusy, setFormBusy] = useState(false);
  const [formError, setFormError] = useState("");

  const [removingUserId, setRemovingUserId] = useState<string | null>(null);
  const [removingBusy, setRemovingBusy] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setStaffError("");
    listMentorInstituteStaff(institute.institute_code, csrf)
      .then((data) => {
        if (active) setStaff(data.staff);
      })
      .catch((caught) => {
        if (active) setStaffError(browserErrorText(caught));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [institute.institute_code, csrf]);

  function toggleLanguage(code: string) {
    setSelectedLanguages((current) =>
      current.includes(code) ? current.filter((c) => c !== code) : [...current, code],
    );
  }

  async function handleCreateStaff() {
    const trimmedName = formName.trim();
    const trimmedEmail = formEmail.trim().toLowerCase();
    const trimmedConfirm = formEmailConfirm.trim().toLowerCase();
    const trimmedJob = formJobTitle.trim();
    const cleanedPhone = formPhone.trim().replace(/[\s-]/g, "");

    setFormError("");

    if (!trimmedName) {
      setFormError("Full Name is required.");
      return;
    }
    if (!trimmedEmail) {
      setFormError("Email is required.");
      return;
    }
    if (!trimmedConfirm) {
      setFormError("Confirm Email is required.");
      return;
    }
    if (trimmedEmail !== trimmedConfirm) {
      setFormError("Email confirmation does not match.");
      return;
    }
    if (languages.length > 0 && selectedLanguages.length === 0) {
      setFormError("At least one coding language must be selected.");
      return;
    }
    if (cleanedPhone && !/^\d{10}$/.test(cleanedPhone)) {
      setFormError("Enter a valid 10-digit mobile number.");
      return;
    }

    const payload: CreateMentorStaffPayload = {
      name: trimmedName,
      email: trimmedEmail,
      email_confirm: trimmedConfirm,
      languages: selectedLanguages,
    };
    if (trimmedJob) payload.job_title = trimmedJob;
    if (cleanedPhone) payload.phone = cleanedPhone;

    setFormBusy(true);
    try {
      const result = await createMentorInstituteStaff(institute.institute_code, payload, csrf);
      setStaff((prev) => [...prev, result.staff]);
      setStaffNotice(
        `Invitation sent to ${trimmedEmail}. Once verified, the District Programme Manager can assign their district roles.`,
      );
      setFormName("");
      setFormEmail("");
      setFormEmailConfirm("");
      setFormJobTitle("");
      setFormPhone("");
      setSelectedLanguages([]);
      setShowAddForm(false);
    } catch (caught) {
      setFormError(browserErrorText(caught));
    } finally {
      setFormBusy(false);
    }
  }

  async function handleConfirmRemove(member: MentorStaffMember) {
    setRemovingBusy(true);
    setStaffError("");
    try {
      await removeMentorInstituteStaff(institute.institute_code, member.user_id, csrf);
      setStaff((prev) => prev.filter((s) => s.user_id !== member.user_id));
      setStaffNotice(`${member.name} removed from ${institute.institute_name}.`);
      setRemovingUserId(null);
    } catch (caught) {
      setStaffError(browserErrorText(caught));
    } finally {
      setRemovingBusy(false);
    }
  }

  return (
    <View style={styles.card}>
      <Text style={styles.headline}>{`Staff Roster — ${institute.institute_name}`}</Text>
      <Text style={styles.muted}>
        {`Manage medical college faculty and resident doctors for ${institute.institute_code}.`}
      </Text>

      {staffNotice ? (
        <View
          style={[
            screenStyles.banner,
            { backgroundColor: theme.colors.accentSoft, borderColor: theme.colors.border },
          ]}
        >
          <Text style={[styles.text, { color: theme.colors.success }]}>{staffNotice}</Text>
        </View>
      ) : null}

      {staffError ? (
        <Text role="alert" style={styles.error}>
          {staffError}
        </Text>
      ) : null}

      {loading ? (
        <Text style={styles.muted}>{t("loading")}</Text>
      ) : (
        <View style={screenStyles.staffList}>
          {staff.length === 0 ? (
            <Text style={styles.muted}>No staff members registered yet.</Text>
          ) : null}
          {staff.map((member) => {
            const isSelf = member.user_id === currentUserId;
            const canRemove = !isSelf && (!member.is_admin || isPlatformAdmin);
            const isRemoving = removingUserId === member.user_id;

            return (
              <View
                key={member.user_id}
                style={[screenStyles.staffRow, { borderBottomColor: theme.colors.border }]}
              >
                <View style={screenStyles.staffHeaderRow}>
                  <Text style={[styles.fieldLabel, { flex: 1 }]}>{member.name}</Text>
                  <View style={screenStyles.badgeRow}>
                    <View
                      style={[
                        screenStyles.pill,
                        {
                          backgroundColor: member.is_admin
                            ? theme.colors.accentSoft
                            : theme.ui.muted,
                        },
                      ]}
                    >
                      <Text
                        style={[
                          screenStyles.pillText,
                          {
                            color: member.is_admin
                              ? theme.colors.accent
                              : theme.ui.mutedForeground,
                          },
                        ]}
                      >
                        {member.is_admin ? "Institute Admin" : "Mentor Staff"}
                      </Text>
                    </View>
                    <View
                      style={[
                        screenStyles.pill,
                        {
                          backgroundColor:
                            member.account_status === "active"
                              ? theme.colors.accentSoft
                              : theme.ui.secondary,
                        },
                      ]}
                    >
                      <Text
                        style={[
                          screenStyles.pillText,
                          {
                            color:
                              member.account_status === "active"
                                ? theme.colors.success
                                : theme.colors.warning,
                          },
                        ]}
                      >
                        {member.account_status === "active" ? "Active" : "Invited"}
                      </Text>
                    </View>
                  </View>
                </View>

                <View style={screenStyles.staffDetails}>
                  <Text style={styles.muted}>
                    {member.email ?? "No email"}
                    {member.job_title ? ` • ${member.job_title}` : ""}
                  </Text>
                </View>

                {canRemove ? (
                  isRemoving ? (
                    <View
                      style={[
                        screenStyles.confirmBox,
                        {
                          backgroundColor: theme.colors.surfaceMuted,
                          borderColor: theme.colors.border,
                        },
                      ]}
                    >
                      <Text style={styles.text}>
                        {`Remove ${member.name} from ${institute.institute_name}? Any active mentoring roles they hold in this institute's districts will be deactivated.`}
                      </Text>
                      <View style={screenStyles.buttonRow}>
                        <Button
                          kind="danger"
                          label="Confirm Removal"
                          loading={removingBusy}
                          onPress={() => void handleConfirmRemove(member)}
                        />
                        <Button
                          kind="secondary"
                          label="Cancel"
                          disabled={removingBusy}
                          onPress={() => setRemovingUserId(null)}
                        />
                      </View>
                    </View>
                  ) : (
                    <View style={screenStyles.removeButtonWrap}>
                      <Button
                        kind="secondary"
                        label="Remove from Institute"
                        onPress={() => {
                          setStaffNotice("");
                          setStaffError("");
                          setRemovingUserId(member.user_id);
                        }}
                      />
                    </View>
                  )
                ) : null}
              </View>
            );
          })}
        </View>
      )}

      <View style={screenStyles.addFormWrap}>
        <Button
          kind="secondary"
          label={showAddForm ? "Cancel Add Staff" : "Add Faculty / Resident Staff"}
          onPress={() => {
            setShowAddForm(!showAddForm);
            setFormError("");
          }}
        />

        {showAddForm ? (
          <View
            style={[
              screenStyles.formCard,
              { backgroundColor: theme.colors.surfaceMuted, borderColor: theme.colors.border },
            ]}
          >
            <Text style={styles.headline}>Add Faculty / Resident Staff</Text>

            <View style={screenStyles.fieldGroup}>
              <Text style={styles.fieldLabel}>Full Name *</Text>
              <TextInput
                style={styles.input}
                value={formName}
                onChangeText={setFormName}
                placeholder="Dr. Full Name"
                placeholderTextColor={theme.colors.textMuted}
                autoCapitalize="words"
              />
            </View>

            <View style={screenStyles.fieldGroup}>
              <Text style={styles.fieldLabel}>Email *</Text>
              <TextInput
                style={styles.input}
                value={formEmail}
                onChangeText={setFormEmail}
                placeholder="doctor@institution.edu.in"
                placeholderTextColor={theme.colors.textMuted}
                keyboardType="email-address"
                autoCapitalize="none"
              />
            </View>

            <View style={screenStyles.fieldGroup}>
              <Text style={styles.fieldLabel}>Confirm Email *</Text>
              <TextInput
                style={styles.input}
                value={formEmailConfirm}
                onChangeText={setFormEmailConfirm}
                placeholder="doctor@institution.edu.in"
                placeholderTextColor={theme.colors.textMuted}
                keyboardType="email-address"
                autoCapitalize="none"
              />
            </View>

            <View style={screenStyles.fieldGroup}>
              <Text style={styles.fieldLabel}>Designation / Job Title</Text>
              <TextInput
                style={styles.input}
                value={formJobTitle}
                onChangeText={setFormJobTitle}
                placeholder="Assistant Professor, Community Medicine"
                placeholderTextColor={theme.colors.textMuted}
              />
            </View>

            <View style={screenStyles.fieldGroup}>
              <Text style={styles.fieldLabel}>Mobile Number (Optional, 10 digits)</Text>
              <TextInput
                style={styles.input}
                value={formPhone}
                onChangeText={setFormPhone}
                placeholder="9876543210"
                placeholderTextColor={theme.colors.textMuted}
                keyboardType="phone-pad"
              />
            </View>

            {languages.length > 0 ? (
              <View style={screenStyles.fieldGroup}>
                <Text style={styles.fieldLabel}>Coding Languages *</Text>
                <View style={screenStyles.chipContainer}>
                  {languages.map((lang) => {
                    const isSelected = selectedLanguages.includes(lang.language_code);
                    return (
                      <Pressable
                        key={lang.language_code}
                        accessibilityRole="button"
                        accessibilityLabel={lang.language_name}
                        onPress={() => toggleLanguage(lang.language_code)}
                        style={[
                          screenStyles.languageChip,
                          {
                            backgroundColor: isSelected
                              ? theme.colors.accent
                              : theme.ui.secondary,
                            borderColor: isSelected
                              ? theme.colors.accent
                              : theme.colors.border,
                          },
                        ]}
                      >
                        <Text
                          style={[
                            screenStyles.chipText,
                            {
                              color: isSelected
                                ? theme.ui.primaryForeground
                                : theme.colors.text,
                            },
                          ]}
                        >
                          {lang.language_name}
                        </Text>
                      </Pressable>
                    );
                  })}
                </View>
              </View>
            ) : null}

            {formError ? (
              <Text role="alert" style={styles.error}>
                {formError}
              </Text>
            ) : null}

            <View style={screenStyles.buttonRow}>
              <Button
                kind="primary"
                label="Send Invitation"
                loading={formBusy}
                onPress={() => void handleCreateStaff()}
              />
            </View>
          </View>
        ) : null}
      </View>
    </View>
  );
}

export default function MentoringScreen() {
  const { bootstrap } = useAppState();
  const router = useRouter();
  const styles = useUiStyles();
  const theme = useTheme();

  const [summary, setSummary] = useState<MentoringSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!bootstrap) return;
    let active = true;
    setLoading(true);
    setError("");

    getMentoringSummary(bootstrap.csrf)
      .then((data) => {
        if (active) setSummary(data);
      })
      .catch((caught) => {
        if (active) setError(browserErrorText(caught));
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [bootstrap]);

  if (!bootstrap) {
    return <WebShell title="Mentoring Institution">{null}</WebShell>;
  }

  const institutes = summary?.institutes ?? [];
  const supportedProjectIds = new Set(
    institutes.flatMap((inst) => inst.districts.map((d) => d.project_id)),
  );
  const relevantProjects = bootstrap.access.projects.filter(
    (project) =>
      supportedProjectIds.has(project.project_id) ||
      project.grants.some((g) => g.active && g.scope === "org_unit"),
  );
  const activeProjects = relevantProjects.filter((p) => p.grants.some((g) => g.active));

  return (
    <WebShell title="Mentoring Institution">
      <ContextualHelpBanner screen="mentoring" />
      {/* Section 1: Plain-Language Guide Card */}
      <View style={styles.card}>
        <Text style={styles.headline}>Mentoring Institution Guide</Text>
        <Text style={styles.text}>
          Your Medical College or Mentoring Institution supports linked districts by coding causes
          of death (3. Coding), reviewing coded cases for quality assurance (4. Review), testing
          coding configurations, or viewing district progress with names (5. Summary Reports).
        </Text>
        <Text style={styles.text}>
          Institute Admins manage the college's faculty and resident roster here. District
          Programme Managers or Project Leads assign specific district or block roles (Within Area)
          to each mentor.
        </Text>
        <View style={screenStyles.helpButtonWrap}>
          <Button
            size="sm"
            kind="secondary"
            label="Help & Guide for Mentoring Staff"
            onPress={() =>
              openServerPage(bootstrap.user.user_id, "/help/mentoring-institutes")
            }
          />
        </View>
      </View>

      {loading ? <Text style={styles.muted}>{t("loading")}</Text> : null}

      {error ? (
        <Text role="alert" style={styles.error}>
          {error}
        </Text>
      ) : null}

      {!loading && !error && institutes.length === 0 ? (
        <View style={styles.card}>
          <Text style={styles.headline}>No Mentoring Institution Membership</Text>
          <Text style={styles.muted}>
            Your account is not currently linked to any Mentoring Institution. If you are medical
            college faculty or resident staff, contact your Institute Admin or a platform
            administrator.
          </Text>
        </View>
      ) : null}

      {/* Section 2: My Mentoring Institution(s) & Supported Districts */}
      {institutes.length > 0 ? (
        <View style={screenStyles.section}>
          <Text style={styles.headline}>
            {institutes.length > 1
              ? "My Mentoring Institutions & Supported Districts"
              : "My Mentoring Institution & Supported Districts"}
          </Text>

          {institutes.map((inst) => (
            <View key={inst.institute_code} style={styles.card}>
              <View style={screenStyles.instituteHeader}>
                <View style={screenStyles.titleGroup}>
                  <Text style={styles.headline}>{inst.institute_name}</Text>
                  <View
                    style={[
                      screenStyles.codeBadge,
                      { backgroundColor: theme.ui.secondary, borderColor: theme.colors.border },
                    ]}
                  >
                    <Text style={[screenStyles.codeBadgeText, { color: theme.colors.text }]}>
                      {inst.institute_code}
                    </Text>
                  </View>
                </View>
                <View
                  style={[
                    screenStyles.pill,
                    {
                      backgroundColor: inst.is_admin
                        ? theme.colors.accentSoft
                        : theme.ui.muted,
                    },
                  ]}
                >
                  <Text
                    style={[
                      screenStyles.pillText,
                      {
                        color: inst.is_admin
                          ? theme.colors.accent
                          : theme.ui.mutedForeground,
                      },
                    ]}
                  >
                    {inst.is_admin ? "Institute Admin" : "Faculty / Mentor Staff"}
                  </Text>
                </View>
              </View>

              <View style={screenStyles.districtsBox}>
                <Text style={styles.fieldLabel}>Supported Districts:</Text>
                {inst.districts.length === 0 ? (
                  <Text style={styles.muted}>No districts attached yet.</Text>
                ) : (
                  inst.districts.map((d) => (
                    <Text key={d.org_unit_id} style={styles.text}>
                      {`• ${d.unit_name} (${d.unit_code}) in ${d.project_name}`}
                    </Text>
                  ))
                )}
              </View>
            </View>
          ))}
        </View>
      ) : null}

      {/* Section 3: My Assigned Roles & Areas in Supported Districts */}
      {!loading && !error && institutes.length > 0 ? (
        <View style={screenStyles.section}>
          <Text style={styles.headline}>My Assigned District Roles & Areas</Text>

          {activeProjects.length === 0 ? (
            <View
              style={[
                styles.card,
                screenStyles.statusBox,
                { backgroundColor: theme.colors.surfaceMuted },
              ]}
            >
              <Text style={styles.text}>
                Your account is linked to your Mentoring Institution, but no District or Block
                role has been assigned yet. Ask the District Programme Manager or Project Lead of
                your supported district to assign your Coding, Review, or Viewer role.
              </Text>
            </View>
          ) : (
            activeProjects.map((project) => {
              const roleRows = describeProjectGrantRows(project.grants, project.sites, t);
              const actions = projectActionItems(project, bootstrap.access.roles);
              const actionKeys = new Set(actions.map((a) => a.key));

              return (
                <View key={project.project_id} style={styles.card}>
                  <Text style={styles.headline}>
                    {`${project.project_name} (${project.project_id})`}
                  </Text>
                  <Text style={styles.muted}>Assigned Roles & Coverage:</Text>
                  {roleRows.map((row, idx) => (
                    <View key={`${project.project_id}-role-${idx}`} style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center" }}>
                      <RoleSentence k="homeRoleWithScope" params={{ scope: row.scope }} roles={[{ role: row.role }]} textStyle={styles.text} />
                      {row.suffix ? <Text style={styles.text}>{row.suffix}</Text> : null}
                    </View>
                  ))}

                  <View style={screenStyles.buttonRow}>
                    {actionKeys.has("coding") ? (
                      <Button
                        size="sm"
                        kind="primary"
                        label="3. Coding"
                        onPress={() =>
                          router.push({
                            pathname: "/coding",
                            params: { project: project.project_id },
                          })
                        }
                      />
                    ) : null}
                    {actionKeys.has("reviewing") ? (
                      <Button
                        size="sm"
                        kind="secondary"
                        label="4. Review"
                        onPress={() =>
                          router.push({
                            pathname: "/reviewing",
                            params: { project: project.project_id },
                          })
                        }
                      />
                    ) : null}
                    {actionKeys.has("organization") ? (
                      <Button
                        size="sm"
                        kind="secondary"
                        label="Organization"
                        onPress={() => router.push("/organization")}
                      />
                    ) : null}
                    <Button
                      size="sm"
                      kind="secondary"
                      label={t("navStatistics")}
                      onPress={() => router.push("/statistics")}
                    />
                  </View>
                </View>
              );
            })
          )}
        </View>
      ) : null}

      {/* Section 4: Institute Staff Roster & Management */}
      {!loading && !error
        ? institutes
            .filter((inst) => inst.is_admin)
            .map((inst) => (
              <InstituteStaffRoster
                key={`roster-${inst.institute_code}`}
                institute={inst}
                csrf={bootstrap.csrf}
                languages={summary?.languages ?? []}
                currentUserId={bootstrap.user.user_id}
                isPlatformAdmin={bootstrap.access.is_admin}
              />
            ))
        : null}
    </WebShell>
  );
}

const screenStyles = StyleSheet.create({
  section: {
    gap: spacing.sm,
  },
  banner: {
    padding: spacing.sm,
    borderRadius: radius.md,
    borderWidth: 1,
  },
  helpButtonWrap: {
    alignSelf: "flex-start",
  },
  instituteHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    flexWrap: "wrap",
    gap: spacing.xs,
  },
  titleGroup: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    flexWrap: "wrap",
  },
  codeBadge: {
    borderRadius: radius.md,
    borderWidth: 1,
    paddingHorizontal: spacing.xs,
    paddingVertical: 2,
  },
  codeBadgeText: {
    fontSize: fontSize.caption,
    fontWeight: "600",
    lineHeight: 16,
  },
  pill: {
    borderRadius: radius.full,
    paddingHorizontal: spacing.xs,
    paddingVertical: 2,
  },
  pillText: {
    fontSize: fontSize.caption,
    fontWeight: "600",
    lineHeight: 16,
  },
  districtsBox: {
    gap: spacing.xxs,
  },
  statusBox: {
    padding: spacing.md,
  },
  buttonRow: {
    flexDirection: "row",
    gap: spacing.xs,
    alignItems: "center",
    flexWrap: "wrap",
    marginTop: spacing.xs,
  },
  staffList: {
    gap: spacing.sm,
  },
  staffRow: {
    paddingVertical: spacing.xs,
    borderBottomWidth: 1,
    gap: spacing.xxs,
  },
  staffHeaderRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: spacing.xs,
  },
  badgeRow: {
    flexDirection: "row",
    gap: spacing.xs,
    alignItems: "center",
  },
  staffDetails: {
    flexDirection: "row",
    alignItems: "center",
  },
  confirmBox: {
    padding: spacing.sm,
    borderRadius: radius.md,
    borderWidth: 1,
    gap: spacing.xs,
    marginTop: spacing.xs,
  },
  removeButtonWrap: {
    alignSelf: "flex-start",
    marginTop: spacing.xxs,
  },
  addFormWrap: {
    marginTop: spacing.sm,
    gap: spacing.sm,
  },
  formCard: {
    padding: spacing.md,
    borderRadius: radius.lg,
    borderWidth: 1,
    gap: spacing.sm,
  },
  fieldGroup: {
    gap: spacing.xxs,
  },
  chipContainer: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.xs,
  },
  languageChip: {
    borderRadius: radius.full,
    borderWidth: 1,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xxs,
  },
  chipText: {
    fontSize: fontSize.caption,
    fontWeight: "500",
    lineHeight: 16,
  },
});
