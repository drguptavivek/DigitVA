import React, { useEffect, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import type { ClientCsrf } from "../api";
import {
  ACTING_ROLE_LABELS,
  daysUntilConfigExpiry,
  fetchStationRoster,
  getDesignationLabel,
  switchStationActingRole,
  updateStationDesignations,
  upsertStationRosterMember,
  validateUserPin,
  type ActingRole,
  type StationRosterMember,
  type StationRosterSnapshot,
} from "../roster";
import { t } from "../i18n";
import { phoneDisplay } from "../phoneFormat";
import { fontSize, palette, radius, ui } from "../theme";

const webTheme = {
  colors: {
    accent: ui.light.chart[2].bar,
    canvas: palette.light.background,
    ink: palette.light.text,
    muted: palette.light.textMuted,
    border: palette.light.border,
  },
};

export interface StationActorBarProps {
  csrf: ClientCsrf;
  onActorSwitched?: () => void;
  onOpenRosterSettings?: () => void;
}

/**
 * Top-bar "Who am I now" + "Acting as [Role]" selector (`digitva-gb8w.8`, Contract Section 4.1 & 10).
 * Switching acting role to "coder" immediately restricts the session to the masked
 * coder view with no informant personal data, even if the same person holds other roles.
 * In provisioned mode, switching to another roster user requires their 6-16 digit PIN.
 */
export function StationActorBar({
  csrf,
  onActorSwitched,
  onOpenRosterSettings,
}: StationActorBarProps) {
  const [snapshot, setSnapshot] = useState<StationRosterSnapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [pendingMemberId, setPendingMemberId] = useState<string | null>(null);
  const [pin, setPin] = useState("");
  const [pinError, setPinError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void fetchStationRoster(csrf).then((res) => {
      if (active) setSnapshot(res);
    });
    return () => {
      active = false;
    };
  }, [csrf]);

  if (!snapshot) return null;

  const activeMembers = snapshot.members.filter((m) => m.active);
  const currentActor = snapshot.active_actor;
  const isProvisioned = snapshot.station_mode === "provisioned";

  const handleSelectMember = async (memberId: string) => {
    if (busy || memberId === currentActor.member_id) return;
    if (isProvisioned) {
      setPendingMemberId(memberId);
      setPin("");
      setPinError(null);
      return;
    }
    setBusy(true);
    try {
      const res = await switchStationActingRole(memberId, undefined, csrf);
      setSnapshot(res.roster);
      onActorSwitched?.();
    } catch {
      // Keep current actor on error
    } finally {
      setBusy(false);
    }
  };

  const handleConfirmPinSwitch = async () => {
    if (!pendingMemberId || busy) return;
    const pinCheck = validateUserPin(pin);
    if (!pinCheck.valid) {
      setPinError(pinCheck.error);
      return;
    }
    setBusy(true);
    setPinError(null);
    const submittedPin = pin.trim();
    setPin("");
    try {
      const res = await switchStationActingRole(
        pendingMemberId,
        undefined,
        csrf,
        submittedPin,
      );
      setSnapshot(res.roster);
      setPendingMemberId(null);
      onActorSwitched?.();
    } catch {
      setPinError(t("stationPinUnlockFailed"));
    } finally {
      setBusy(false);
    }
  };

  const handleSelectRole = async (role: ActingRole) => {
    if (busy || role === currentActor.acting_role) return;
    setBusy(true);
    try {
      const res = await switchStationActingRole(
        currentActor.member_id,
        role,
        csrf,
      );
      setSnapshot(res.roster);
      onActorSwitched?.();
    } catch {
      // Keep current role on error
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.actorBar} testID="station-actor-bar">
      <View style={styles.actorBarRow}>
        <View
          style={[
            styles.modeBadge,
            isProvisioned ? styles.modeBadgeProvisioned : styles.modeBadgeSandbox,
          ]}
        >
          <Text style={styles.modeBadgeText}>
            {t(isProvisioned ? "stationModeProvisioned" : "stationModeSandbox")}
          </Text>
        </View>

        <View style={styles.actorGroup}>
          <Text style={styles.actorLabel}>{t("stationWhoAmI")}</Text>
          <View style={styles.pillRow}>
            {activeMembers.map((m) => {
              const selected = m.member_id === currentActor.member_id;
              const desigLabel = getDesignationLabel(
                snapshot.designations,
                m.designation,
              );
              return (
                <Pressable
                  key={m.member_id}
                  disabled={busy}
                  onPress={() => void handleSelectMember(m.member_id)}
                  style={[styles.actorPill, selected && styles.actorPillSelected]}
                >
                  <Text
                    style={[
                      styles.actorPillText,
                      selected && styles.actorPillTextSelected,
                    ]}
                  >
                    {m.name} ({desigLabel})
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </View>

        <View style={styles.actorGroup}>
          <Text style={styles.actorLabel}>{t("stationActingAs")}</Text>
          <View style={styles.pillRow}>
            {currentActor.allowed_acting_roles.map((role) => {
              const selected = role === currentActor.acting_role;
              return (
                <Pressable
                  key={role}
                  disabled={busy}
                  onPress={() => void handleSelectRole(role)}
                  style={[
                    styles.rolePill,
                    selected && styles.rolePillSelected,
                    selected && role === "coder" && styles.coderRolePillSelected,
                  ]}
                >
                  <Text
                    style={[
                      styles.actorPillText,
                      selected && styles.actorPillTextSelected,
                    ]}
                  >
                    {ACTING_ROLE_LABELS[role]}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </View>

        {onOpenRosterSettings ? (
          <Pressable onPress={onOpenRosterSettings} style={styles.rosterButton}>
            <Text style={styles.rosterButtonText}>{t("stationRosterButton")}</Text>
          </Pressable>
        ) : null}
      </View>

      {pendingMemberId && isProvisioned ? (
        <View style={styles.pinUnlockBox} testID="pin-unlock-prompt">
          <Text style={styles.pinWarningText}>{t("stationPinPrompt")}</Text>
          <View style={styles.formRow}>
            <TextInput
              value={pin}
              onChangeText={setPin}
              placeholder={t("stationPinPlaceholder")}
              secureTextEntry
              keyboardType="numeric"
              maxLength={16}
              style={styles.pinInput}
            />
            <Pressable
              disabled={busy}
              onPress={() => void handleConfirmPinSwitch()}
              style={styles.primaryBtn}
            >
              <Text style={styles.primaryBtnText}>{t("stationUnlockAndSwitch")}</Text>
            </Pressable>
            <Pressable
              disabled={busy}
              onPress={() => {
                setPendingMemberId(null);
                setPin("");
                setPinError(null);
              }}
              style={styles.closeBtn}
            >
              <Text style={styles.closeBtnText}>{t("cancel")}</Text>
            </Pressable>
          </View>
          {pinError ? <Text style={styles.errorText}>{pinError}</Text> : null}
        </View>
      ) : null}

      {currentActor.acting_role === "coder" ? (
        <Text style={styles.coderMaskNotice}>{t("stationCoderMaskNotice")}</Text>
      ) : null}
    </View>
  );
}

export interface StationRosterScreenProps {
  csrf: ClientCsrf;
  onActorSwitched?: () => void;
  onClose?: () => void;
}

export function StationRosterScreen({
  csrf,
  onActorSwitched,
  onClose,
}: StationRosterScreenProps) {
  const [snapshot, setSnapshot] = useState<StationRosterSnapshot | null>(null);
  const [name, setName] = useState("");
  const [designation, setDesignation] = useState("medical_officer");
  const [isReporter, setIsReporter] = useState(true);
  const [isInterviewer, setIsInterviewer] = useState(true);
  const [isSupervisor, setIsSupervisor] = useState(false);
  const [isCoder, setIsCoder] = useState(false);
  const [newDesignation, setNewDesignation] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [unlockTargetId, setUnlockTargetId] = useState<string | null>(null);
  const [unlockPin, setUnlockPin] = useState("");

  useEffect(() => {
    void fetchStationRoster(csrf).then((res) => {
      setSnapshot(res);
      if (res.designations.length > 0) {
        setDesignation(res.designations[0].code);
      }
    });
  }, [csrf]);

  if (!snapshot) {
    return (
      <View style={styles.container}>
        <Text style={styles.subtitle}>{t("stationRosterLoading")}</Text>
      </View>
    );
  }

  const isProvisioned = snapshot.station_mode === "provisioned";
  const editable = !isProvisioned && snapshot.editable;
  const expiryDays = daysUntilConfigExpiry(snapshot.config_expires_at);

  const handleToggleMemberTick = async (
    member: StationRosterMember,
    field: "is_reporter" | "is_interviewer" | "is_supervisor" | "is_coder" | "active",
  ) => {
    if (!editable || busy) return;
    setError(null);
    setBusy(true);
    try {
      const updated = {
        member_id: member.member_id,
        name: member.name,
        designation: member.designation,
        is_reporter: field === "is_reporter" ? !member.is_reporter : member.is_reporter,
        is_interviewer: field === "is_interviewer" ? !member.is_interviewer : member.is_interviewer,
        is_supervisor: field === "is_supervisor" ? !member.is_supervisor : member.is_supervisor,
        is_coder: field === "is_coder" ? !member.is_coder : member.is_coder,
        active: field === "active" ? !member.active : member.active,
      };
      const res = await upsertStationRosterMember(updated, csrf);
      setSnapshot(res.roster);
      onActorSwitched?.();
    } catch {
      setError(t("stationMemberUpdateFailed"));
    } finally {
      setBusy(false);
    }
  };

  const handleAddMember = async () => {
    if (!editable || busy) return;
    if (!name.trim()) {
      setError(t("stationNameRequired"));
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const res = await upsertStationRosterMember(
        {
          name: name.trim(),
          designation,
          is_reporter: isReporter,
          is_interviewer: isInterviewer,
          is_supervisor: isSupervisor,
          is_coder: isCoder,
          active: true,
        },
        csrf,
      );
      setSnapshot(res.roster);
      setName("");
      onActorSwitched?.();
    } catch {
      setError(t("stationMemberAddFailed"));
    } finally {
      setBusy(false);
    }
  };

  const handleAddDesignation = async () => {
    if (!editable || busy || !newDesignation.trim()) return;
    const trimmed = newDesignation.trim();
    if (
      snapshot.designations.some(
        (d) =>
          d.label.toLowerCase() === trimmed.toLowerCase() ||
          d.code.toLowerCase() === trimmed.toLowerCase(),
      )
    ) {
      setNewDesignation("");
      return;
    }
    setBusy(true);
    try {
      const nextList = [
        ...snapshot.designations,
        {
          code: trimmed
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, "_")
            .replace(/^_+|_+$/g, ""),
          label: trimmed,
        },
      ];
      const res = await updateStationDesignations(nextList, csrf);
      setSnapshot(res.roster);
      if (res.designations.length > 0) {
        setDesignation(res.designations[res.designations.length - 1].code);
      }
      setNewDesignation("");
    } catch {
      setError(t("stationDesignationUpdateFailed"));
    } finally {
      setBusy(false);
    }
  };

  const handleUnlockProvisionedMember = async (memberId: string) => {
    if (busy) return;
    const pinCheck = validateUserPin(unlockPin);
    if (!pinCheck.valid) {
      setError(pinCheck.error);
      return;
    }
    setError(null);
    setBusy(true);
    const submittedPin = unlockPin.trim();
    setUnlockPin("");
    try {
      const res = await switchStationActingRole(
        memberId,
        undefined,
        csrf,
        submittedPin,
      );
      setSnapshot(res.roster);
      setUnlockTargetId(null);
      onActorSwitched?.();
    } catch {
      setError(t("stationStoreUnlockFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <ScrollView keyboardDismissMode="on-drag" style={styles.container} contentContainerStyle={styles.content}>
      <View style={styles.headerRow}>
        <View>
          <Text style={styles.title}>{t("stationRosterTitle")}</Text>
          <Text style={styles.subtitle}>
            {t(isProvisioned ? "stationRosterProvisionedSubtitle" : "stationRosterSandboxSubtitle")}
          </Text>
        </View>
        {onClose ? (
          <Pressable onPress={onClose} style={styles.closeBtn}>
            <Text style={styles.closeBtnText}>{t("stationBackToWorkspace")}</Text>
          </Pressable>
        ) : null}
      </View>

      {!isProvisioned ? (
        <View style={styles.sandboxBanner} testID="sandbox-station-banner">
          <Text style={styles.sandboxBannerTitle}>{t("stationSandboxBannerTitle")}</Text>
          <Text style={styles.sandboxBannerText}>{t("stationSandboxBannerText")}</Text>
        </View>
      ) : (
        <View style={styles.provisionedBanner} testID="provisioned-station-banner">
          <Text style={styles.provisionedBannerTitle}>
            {t("stationModeProvisioned")}
            {snapshot.station_config_id ? ` · ${t("stationProvisionedConfigId", { id: snapshot.station_config_id })}` : ""}
          </Text>
          <Text style={styles.provisionedBannerText}>{t("stationProvisionedBannerText")}</Text>
        </View>
      )}

      {isProvisioned && expiryDays !== null && expiryDays <= 30 ? (
        <View style={styles.expiryWarningBanner} testID="config-expiry-warning">
          <Text style={styles.expiryWarningText}>
            {expiryDays <= 0
              ? t("stationConfigExpired", { date: String(snapshot.config_expires_at) })
              : t(expiryDays === 1 ? "stationConfigExpiresOne" : "stationConfigExpiresMany", {
                  days: expiryDays,
                  date: String(snapshot.config_expires_at),
                })}
          </Text>
        </View>
      ) : null}

      {isProvisioned && snapshot.custodian ? (
        <View style={styles.card} testID="station-custodian-card">
          <Text style={styles.sectionTitle}>{t("stationCustodianTitle")}</Text>
          <Text style={styles.cellText}>
            {t("stationCustodianName", {
              name: snapshot.custodian.name,
              designation: getDesignationLabel(snapshot.designations, snapshot.custodian.designation),
            })}
          </Text>
          <Text style={styles.subtitle}>
            {t("stationCustodianOnboarded", { date: snapshot.custodian.onboarded_on })}
            {snapshot.custodian.verified_by_user_id !== undefined
              ? ` · ${t("stationCustodianVerifiedBy", { id: String(snapshot.custodian.verified_by_user_id) })}`
              : ""}
          </Text>
          <Text style={styles.subtitle}>
            {t("stationCustodianContact", {
              contact:
                [snapshot.custodian.phone ? phoneDisplay(snapshot.custodian.phone) : null, snapshot.custodian.email]
                  .filter(Boolean)
                  .join(" · ") || t("stationCustodianContactOnServer"),
            })}
          </Text>
        </View>
      ) : null}

      {error ? (
        <View style={styles.errorBox}>
          <Text style={styles.errorText}>{error}</Text>
        </View>
      ) : null}

      <View style={styles.card}>
        <Text style={styles.sectionTitle}>
          {t(isProvisioned ? "stationRosterTableReadOnly" : "stationRosterTableEditable")}
        </Text>
        <View style={styles.tableHeader}>
          <Text style={[styles.cellHeader, styles.nameCol]}>{t("stationColName")}</Text>
          <Text style={[styles.cellHeader, styles.desigCol]}>{t("stationColDesignation")}</Text>
          <Text style={[styles.cellHeader, styles.tickCol]}>{t("role_death_reporter")}</Text>
          <Text style={[styles.cellHeader, styles.tickCol]}>{t("role_interviewer")}</Text>
          <Text style={[styles.cellHeader, styles.tickCol]}>{t("stationRoleSupervisor")}</Text>
          <Text style={[styles.cellHeader, styles.tickCol]}>{t("role_coder")}</Text>
          <Text style={[styles.cellHeader, styles.tickCol]}>{t("stationColActive")}</Text>
          {isProvisioned ? (
            <Text style={[styles.cellHeader, styles.tickCol]}>{t("stationColStorePin")}</Text>
          ) : null}
        </View>

        {snapshot.members.map((m) => (
          <View key={m.member_id} style={styles.tableRow}>
            <View style={styles.nameCol}>
              <Text style={styles.cellText}>{m.name}</Text>
              {m.user_id !== null ? (
                <Text style={styles.subtitle}>{t("stationServerId", { id: String(m.user_id) })}</Text>
              ) : null}
            </View>
            <Text style={[styles.cellText, styles.desigCol]}>
              {getDesignationLabel(snapshot.designations, m.designation)}
            </Text>
            {(
              [
                ["is_reporter", m.is_reporter],
                ["is_interviewer", m.is_interviewer],
                ["is_supervisor", m.is_supervisor],
                ["is_coder", m.is_coder],
                ["active", m.active],
              ] as const
            ).map(([field, checked]) => (
              <Pressable
                key={field}
                disabled={!editable || busy}
                onPress={() => void handleToggleMemberTick(m, field)}
                style={[styles.tickCol, styles.tickCell]}
              >
                <View style={[styles.checkbox, checked && styles.checkboxChecked]}>
                  <Text style={styles.checkboxMark}>{checked ? "✓" : ""}</Text>
                </View>
              </Pressable>
            ))}
            {isProvisioned ? (
              <View style={[styles.tickCol, styles.tickCell]}>
                {m.active ? (
                  <Pressable
                    disabled={busy}
                    onPress={() => {
                      setUnlockTargetId(m.member_id);
                      setUnlockPin("");
                      setError(null);
                    }}
                    style={styles.secondaryBtn}
                  >
                    <Text style={styles.secondaryBtnText}>
                      {t(snapshot.active_actor.member_id === m.member_id ? "stationColActive" : "stationSwitchWithPin")}
                    </Text>
                  </Pressable>
                ) : (
                  <Text style={styles.subtitle}>{t("stationMemberInactive")}</Text>
                )}
              </View>
            ) : null}
          </View>
        ))}

        {isProvisioned && unlockTargetId ? (
          <View style={styles.pinUnlockBox}>
            <Text style={styles.pinWarningText}>{t("stationStoreUnlockPrompt")}</Text>
            <View style={styles.formRow}>
              <TextInput
                value={unlockPin}
                onChangeText={setUnlockPin}
                placeholder={t("stationStorePinPlaceholder")}
                secureTextEntry
                keyboardType="numeric"
                maxLength={16}
                style={styles.pinInput}
              />
              <Pressable
                disabled={busy}
                onPress={() => void handleUnlockProvisionedMember(unlockTargetId)}
                style={styles.primaryBtn}
              >
                <Text style={styles.primaryBtnText}>{t("stationUnlockStore")}</Text>
              </Pressable>
              <Pressable
                disabled={busy}
                onPress={() => {
                  setUnlockTargetId(null);
                  setUnlockPin("");
                }}
                style={styles.closeBtn}
              >
                <Text style={styles.closeBtnText}>{t("cancel")}</Text>
              </Pressable>
            </View>
          </View>
        ) : null}
      </View>

      {editable ? (
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>{t("stationAddPersonTitle")}</Text>
          <View style={styles.formRow}>
            <View style={styles.fieldBlock}>
              <Text style={styles.label}>{t("stationFullName")}</Text>
              <TextInput
                value={name}
                onChangeText={setName}
                placeholder={t("stationFullNamePlaceholder")}
                style={styles.input}
              />
            </View>
            <View style={styles.fieldBlock}>
              <Text style={styles.label}>{t("stationColDesignation")}</Text>
              <View style={styles.pillRow}>
                {snapshot.designations.map((d) => (
                  <Pressable
                    key={d.code}
                    onPress={() => setDesignation(d.code)}
                    style={[
                      styles.actorPill,
                      (designation === d.code || designation === d.label) &&
                        styles.actorPillSelected,
                    ]}
                  >
                    <Text
                      style={[
                        styles.actorPillText,
                        (designation === d.code || designation === d.label) &&
                          styles.actorPillTextSelected,
                      ]}
                    >
                      {d.label}
                    </Text>
                  </Pressable>
                ))}
              </View>
            </View>
          </View>

          <View style={styles.pillRow}>
            {(
              [
                [t("role_death_reporter"), isReporter, setIsReporter],
                [t("role_interviewer"), isInterviewer, setIsInterviewer],
                [t("stationRoleSupervisor"), isSupervisor, setIsSupervisor],
                [t("role_coder"), isCoder, setIsCoder],
              ] as const
            ).map(([label, val, setter]) => (
              <Pressable
                key={label}
                onPress={() => setter(!val)}
                style={[styles.actorPill, val && styles.actorPillSelected]}
              >
                <Text style={[styles.actorPillText, val && styles.actorPillTextSelected]}>
                  {val ? "✓ " : ""}
                  {label}
                </Text>
              </Pressable>
            ))}
          </View>

          <Pressable onPress={() => void handleAddMember()} style={styles.primaryBtn}>
            <Text style={styles.primaryBtnText}>{t("stationAddToRoster")}</Text>
          </Pressable>

          <View style={styles.divider} />
          <Text style={styles.sectionTitle}>{t("stationDesignationListTitle")}</Text>
          <View style={styles.formRow}>
            <TextInput
              value={newDesignation}
              onChangeText={setNewDesignation}
              placeholder={t("stationDesignationPlaceholder")}
              style={[styles.input, { flex: 1 }]}
            />
            <Pressable onPress={() => void handleAddDesignation()} style={styles.secondaryBtn}>
              <Text style={styles.secondaryBtnText}>{t("stationAddDesignation")}</Text>
            </Pressable>
          </View>
        </View>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  actorBar: {
    backgroundColor: palette.light.background,
    borderBottomWidth: 1,
    borderBottomColor: palette.light.border,
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  actorBarRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    alignItems: "center",
    gap: 12,
  },
  modeBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: radius.sm,
  },
  modeBadgeSandbox: {
    backgroundColor: ui.light.warningBorder,
  },
  modeBadgeProvisioned: {
    backgroundColor: webTheme.colors.accent,
  },
  modeBadgeText: {
    color: palette.light.onAccent,
    fontSize: fontSize.caption,
    fontWeight: "700",
  },
  actorGroup: {
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
    flexShrink: 1,
    minWidth: 0,
    gap: 6,
  },
  actorLabel: {
    fontSize: fontSize.caption,
    fontWeight: "600",
    color: palette.light.text,
  },
  pillRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    flexShrink: 1,
    minWidth: 0,
    gap: 6,
  },
  actorPill: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: radius.full,
    borderWidth: 1,
    borderColor: palette.light.border,
    backgroundColor: palette.light.surface,
  },
  actorPillSelected: {
    backgroundColor: webTheme.colors.accent,
    borderColor: webTheme.colors.accent,
  },
  rolePill: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: radius.full,
    borderWidth: 1,
    borderColor: palette.light.border,
    backgroundColor: palette.light.surface,
  },
  rolePillSelected: {
    backgroundColor: palette.light.accent,
    borderColor: palette.light.accent,
  },
  coderRolePillSelected: {
    backgroundColor: ui.light.chart[4].bar,
    borderColor: ui.light.chart[4].bar,
  },
  actorPillText: {
    fontSize: fontSize.caption,
    color: palette.light.text,
    fontWeight: "500",
  },
  actorPillTextSelected: {
    color: palette.light.onAccent,
    fontWeight: "700",
  },
  rosterButton: {
    marginLeft: "auto",
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: palette.light.borderStrong,
    backgroundColor: palette.light.surface,
  },
  rosterButtonText: {
    fontSize: fontSize.caption,
    fontWeight: "600",
    color: palette.light.text,
  },
  coderMaskNotice: {
    marginTop: 4,
    fontSize: fontSize.caption,
    color: ui.light.chart[4].bar,
    fontWeight: "600",
  },
  pinUnlockBox: {
    marginTop: 8,
    padding: 10,
    backgroundColor: ui.light.warning,
    borderWidth: 1,
    borderColor: ui.light.warningBorder,
    borderRadius: radius.md,
    gap: 8,
  },
  pinWarningText: {
    fontSize: fontSize.caption,
    color: ui.light.warningForeground,
    fontWeight: "600",
  },
  pinInput: {
    borderWidth: 1,
    borderColor: palette.light.border,
    borderRadius: radius.md,
    paddingHorizontal: 10,
    paddingVertical: 6,
    fontSize: fontSize.body,
    backgroundColor: palette.light.surface,
    minWidth: 180,
  },
  container: {
    flex: 1,
    backgroundColor: webTheme.colors.canvas,
  },
  content: {
    padding: 20,
    gap: 16,
  },
  headerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    flexWrap: "wrap",
    gap: 12,
  },
  title: {
    fontSize: fontSize.heading,
    fontWeight: "700",
    color: webTheme.colors.ink,
  },
  subtitle: {
    fontSize: fontSize.body,
    color: webTheme.colors.muted,
    marginTop: 2,
  },
  sandboxBanner: {
    backgroundColor: ui.light.warning,
    borderColor: ui.light.warningBorder,
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: 12,
    gap: 4,
  },
  sandboxBannerTitle: {
    fontSize: fontSize.body,
    fontWeight: "700",
    color: ui.light.warningForeground,
  },
  sandboxBannerText: {
    fontSize: fontSize.body,
    color: ui.light.warningForeground,
    fontWeight: "600",
  },
  provisionedBanner: {
    backgroundColor: ui.light.chart[2].tint,
    borderColor: webTheme.colors.accent,
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: 12,
    gap: 4,
  },
  provisionedBannerTitle: {
    fontSize: fontSize.body,
    fontWeight: "700",
    color: ui.light.chart[2].foreground,
  },
  provisionedBannerText: {
    fontSize: fontSize.body,
    color: ui.light.chart[2].foreground,
  },
  expiryWarningBanner: {
    backgroundColor: palette.light.dangerSoft,
    borderColor: palette.light.danger,
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: 12,
  },
  expiryWarningText: {
    fontSize: fontSize.body,
    fontWeight: "700",
    color: palette.light.danger,
  },
  card: {
    backgroundColor: palette.light.surface,
    borderRadius: radius.lg,
    padding: 16,
    borderWidth: 1,
    borderColor: webTheme.colors.border,
    gap: 12,
  },
  sectionTitle: {
    fontSize: fontSize.input,
    fontWeight: "700",
    color: webTheme.colors.ink,
  },
  tableHeader: {
    flexDirection: "row",
    borderBottomWidth: 1,
    borderBottomColor: palette.light.border,
    paddingBottom: 8,
  },
  tableRow: {
    flexDirection: "row",
    alignItems: "center",
    borderBottomWidth: 1,
    borderBottomColor: palette.light.surfaceMuted,
    paddingVertical: 8,
  },
  cellHeader: {
    fontSize: fontSize.caption,
    fontWeight: "700",
    color: palette.light.textMuted,
  },
  cellText: {
    fontSize: fontSize.body,
    color: palette.light.text,
  },
  nameCol: {
    flex: 2,
  },
  desigCol: {
    flex: 2,
  },
  tickCol: {
    flex: 1,
    alignItems: "center",
  },
  tickCell: {
    justifyContent: "center",
  },
  checkbox: {
    width: 20,
    height: 20,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: palette.light.borderStrong,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: palette.light.surface,
  },
  checkboxChecked: {
    backgroundColor: webTheme.colors.accent,
    borderColor: webTheme.colors.accent,
  },
  checkboxMark: {
    color: palette.light.onAccent,
    fontSize: fontSize.caption,
    fontWeight: "700",
  },
  formRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 12,
    alignItems: "center",
  },
  fieldBlock: {
    flex: 1,
    minWidth: 220,
    gap: 4,
  },
  label: {
    fontSize: fontSize.caption,
    fontWeight: "600",
    color: palette.light.text,
  },
  input: {
    borderWidth: 1,
    borderColor: palette.light.border,
    borderRadius: radius.md,
    paddingHorizontal: 10,
    paddingVertical: 7,
    fontSize: fontSize.body,
    backgroundColor: palette.light.surface,
  },
  primaryBtn: {
    alignSelf: "flex-start",
    backgroundColor: webTheme.colors.accent,
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: radius.md,
  },
  primaryBtnText: {
    color: palette.light.onAccent,
    fontSize: fontSize.body,
    fontWeight: "700",
  },
  secondaryBtn: {
    borderWidth: 1,
    borderColor: webTheme.colors.accent,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: radius.md,
  },
  secondaryBtnText: {
    color: webTheme.colors.accent,
    fontSize: fontSize.caption,
    fontWeight: "600",
  },
  closeBtn: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: palette.light.border,
    backgroundColor: palette.light.surface,
  },
  closeBtnText: {
    fontSize: fontSize.body,
    fontWeight: "600",
    color: palette.light.text,
  },
  divider: {
    height: 1,
    backgroundColor: palette.light.border,
    marginVertical: 4,
  },
  errorBox: {
    backgroundColor: palette.light.dangerSoft,
    borderColor: palette.light.danger,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: 10,
  },
  errorText: {
    color: palette.light.danger,
    fontSize: fontSize.body,
  },
});
