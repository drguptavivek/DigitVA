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
      setPinError(
        "PIN unlock failed. Warning: 5 wrong PIN attempts wipe that user's local store.",
      );
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
            {isProvisioned
              ? "Onboarded Provisioned Station"
              : "Standalone Sandbox"}
          </Text>
        </View>

        <View style={styles.actorGroup}>
          <Text style={styles.actorLabel}>Who am I now:</Text>
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
          <Text style={styles.actorLabel}>Acting as:</Text>
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
            <Text style={styles.rosterButtonText}>Station Roster</Text>
          </Pressable>
        ) : null}
      </View>

      {pendingMemberId && isProvisioned ? (
        <View style={styles.pinUnlockBox} testID="pin-unlock-prompt">
          <Text style={styles.pinWarningText}>
            Enter your 6–16 digit PIN to unlock this user&apos;s encrypted store. Warning: 5 wrong PIN attempts wipe that user&apos;s local store.
          </Text>
          <View style={styles.formRow}>
            <TextInput
              value={pin}
              onChangeText={setPin}
              placeholder="6–16 digit PIN"
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
              <Text style={styles.primaryBtnText}>Unlock &amp; Switch</Text>
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
              <Text style={styles.closeBtnText}>Cancel</Text>
            </Pressable>
          </View>
          {pinError ? <Text style={styles.errorText}>{pinError}</Text> : null}
        </View>
      ) : null}

      {currentActor.acting_role === "coder" ? (
        <Text style={styles.coderMaskNotice}>
          Acting as Coder: Informant personal data, consent records, and sealed PII fields are masked/omitted for this task.
        </Text>
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
        <Text style={styles.subtitle}>Loading station roster...</Text>
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
      setError("Could not update roster member. Ensure at least one role tick remains checked.");
    } finally {
      setBusy(false);
    }
  };

  const handleAddMember = async () => {
    if (!editable || busy) return;
    if (!name.trim()) {
      setError("Name is required.");
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
      setError("Could not add roster member. Check name and role ticks.");
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
      setError("Failed to update designation list.");
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
      setError(
        "Could not unlock roster user store. Warning: 5 wrong PIN attempts wipe that user's local store.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <View style={styles.headerRow}>
        <View>
          <Text style={styles.title}>PHC Station Roster &amp; Acting Roles</Text>
          <Text style={styles.subtitle}>
            {isProvisioned
              ? "Onboarded Provisioned Station Mode: Roster is attested by the signed station config and is read-only on this station."
              : "Standalone Sandbox Mode: Local editable roster for training and testing. No passwords required."}
          </Text>
        </View>
        {onClose ? (
          <Pressable onPress={onClose} style={styles.closeBtn}>
            <Text style={styles.closeBtnText}>Back to Workspace</Text>
          </Pressable>
        ) : null}
      </View>

      {!isProvisioned ? (
        <View style={styles.sandboxBanner} testID="sandbox-station-banner">
          <Text style={styles.sandboxBannerTitle}>Unprovisioned Standalone Sandbox</Text>
          <Text style={styles.sandboxBannerText}>
            Sandbox data is local-only and never ingestable into a server project.
          </Text>
        </View>
      ) : (
        <View style={styles.provisionedBanner} testID="provisioned-station-banner">
          <Text style={styles.provisionedBannerTitle}>
            Onboarded Provisioned Station
            {snapshot.station_config_id ? ` · Config ${snapshot.station_config_id}` : ""}
          </Text>
          <Text style={styles.provisionedBannerText}>
            Roster and project scope are verified from the signed station config and cannot be edited locally.
          </Text>
        </View>
      )}

      {isProvisioned && expiryDays !== null && expiryDays <= 30 ? (
        <View style={styles.expiryWarningBanner} testID="config-expiry-warning">
          <Text style={styles.expiryWarningText}>
            {expiryDays <= 0
              ? `Station configuration expired (${snapshot.config_expires_at}). Import a renewed signed station config before starting new interviews.`
              : `Station configuration expires in ${expiryDays} day${expiryDays === 1 ? "" : "s"} (${snapshot.config_expires_at}). Request and import a renewed station config soon.`}
          </Text>
        </View>
      ) : null}

      {isProvisioned && snapshot.custodian ? (
        <View style={styles.card} testID="station-custodian-card">
          <Text style={styles.sectionTitle}>Verified Station Custodian</Text>
          <Text style={styles.cellText}>
            Name: {snapshot.custodian.name} (
            {getDesignationLabel(snapshot.designations, snapshot.custodian.designation)})
          </Text>
          <Text style={styles.subtitle}>
            Onboarded on: {snapshot.custodian.onboarded_on}
            {snapshot.custodian.verified_by_user_id !== undefined
              ? ` · Verified by Server User #${snapshot.custodian.verified_by_user_id}`
              : ""}
          </Text>
          <Text style={styles.subtitle}>
            Contact:{" "}
            {[snapshot.custodian.phone, snapshot.custodian.email]
              .filter(Boolean)
              .join(" · ") || "Recorded on server"}
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
          Station Roster {isProvisioned ? "(Read-Only)" : "(Editable Sandbox)"}
        </Text>
        <View style={styles.tableHeader}>
          <Text style={[styles.cellHeader, styles.nameCol]}>Name</Text>
          <Text style={[styles.cellHeader, styles.desigCol]}>Designation</Text>
          <Text style={[styles.cellHeader, styles.tickCol]}>Death Reporter</Text>
          <Text style={[styles.cellHeader, styles.tickCol]}>Interviewer</Text>
          <Text style={[styles.cellHeader, styles.tickCol]}>Station Supervisor</Text>
          <Text style={[styles.cellHeader, styles.tickCol]}>Coder</Text>
          <Text style={[styles.cellHeader, styles.tickCol]}>Active</Text>
          {isProvisioned ? (
            <Text style={[styles.cellHeader, styles.tickCol]}>Store PIN</Text>
          ) : null}
        </View>

        {snapshot.members.map((m) => (
          <View key={m.member_id} style={styles.tableRow}>
            <View style={styles.nameCol}>
              <Text style={styles.cellText}>{m.name}</Text>
              {m.user_id !== null ? (
                <Text style={styles.subtitle}>Server ID #{m.user_id}</Text>
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
                      {snapshot.active_actor.member_id === m.member_id
                        ? "Active"
                        : "Switch (PIN)"}
                    </Text>
                  </Pressable>
                ) : (
                  <Text style={styles.subtitle}>Inactive</Text>
                )}
              </View>
            ) : null}
          </View>
        ))}

        {isProvisioned && unlockTargetId ? (
          <View style={styles.pinUnlockBox}>
            <Text style={styles.pinWarningText}>
              Unlock SQLCipher store for selected roster user (6–16 digit PIN). 5 wrong PIN attempts wipe that user&apos;s local store only.
            </Text>
            <View style={styles.formRow}>
              <TextInput
                value={unlockPin}
                onChangeText={setUnlockPin}
                placeholder="Enter 6–16 digit PIN"
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
                <Text style={styles.primaryBtnText}>Unlock Store</Text>
              </Pressable>
              <Pressable
                disabled={busy}
                onPress={() => {
                  setUnlockTargetId(null);
                  setUnlockPin("");
                }}
                style={styles.closeBtn}
              >
                <Text style={styles.closeBtnText}>Cancel</Text>
              </Pressable>
            </View>
          </View>
        ) : null}
      </View>

      {editable ? (
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Add Person to Sandbox Roster</Text>
          <View style={styles.formRow}>
            <View style={styles.fieldBlock}>
              <Text style={styles.label}>Full Name</Text>
              <TextInput
                value={name}
                onChangeText={setName}
                placeholder="e.g. Dr. Rajesh Verma"
                style={styles.input}
              />
            </View>
            <View style={styles.fieldBlock}>
              <Text style={styles.label}>Designation</Text>
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
                ["Death Reporter", isReporter, setIsReporter],
                ["Interviewer", isInterviewer, setIsInterviewer],
                ["Station Supervisor", isSupervisor, setIsSupervisor],
                ["Coder", isCoder, setIsCoder],
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
            <Text style={styles.primaryBtnText}>Add to Station Roster</Text>
          </Pressable>

          <View style={styles.divider} />
          <Text style={styles.sectionTitle}>Editable Designation List Setting</Text>
          <View style={styles.formRow}>
            <TextInput
              value={newDesignation}
              onChangeText={setNewDesignation}
              placeholder="Add custom designation (e.g. Block Nodal Officer)"
              style={[styles.input, { flex: 1 }]}
            />
            <Pressable onPress={() => void handleAddDesignation()} style={styles.secondaryBtn}>
              <Text style={styles.secondaryBtnText}>Add Designation</Text>
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
