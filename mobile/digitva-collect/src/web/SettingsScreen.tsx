import { useEffect, useMemo, useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import {
  ApiError,
  fetchStationEnrolmentFile,
  fetchStationFacility,
  fetchStationSettings,
  getLocalStationLaunchToken,
  saveStationFacility,
  saveStationSettings,
  type StationCodingMode,
  type StationFacility,
  type StationSettings,
} from "../api";
import { useAppState } from "../AppState";
import { t, type StringKey } from "../i18n";
import {
  exportStationBundle,
  fetchStationRoster,
  heldBackRecords,
  importBundleReceipt,
  importStationConfig,
  type StationRosterSnapshot,
} from "../roster";
import { Button, useUiStyles } from "../ui";
import { fontSize, palette, radius, ui, useTheme, type UiTokens } from "../theme";
import { WebShell } from "./common";
import { ContextualHelpBanner } from "./ContextualHelp";
import { StationActorBar, StationRosterScreen } from "./StationRosterScreen";

/** Records kept out of the data file, each with the station's reason; they stay for a later file. */
function heldBackText(held: { client_id: string; reason: string }[]): string {
  return `${t("stationBundleHeldBack", { count: held.length })} ${held.map((h) => `${h.client_id}: ${h.reason}`).join("; ")}`;
}

const FACILITY_FIELDS: { key: keyof StationFacility; label: StringKey; multiline?: boolean }[] = [
  { key: "name", label: "facilityName" },
  { key: "code", label: "facilityCode" },
  { key: "type", label: "facilityType" },
  { key: "address", label: "facilityAddress", multiline: true },
  { key: "district", label: "facilityDistrict" },
  { key: "state", label: "facilityState" },
];
const CODING_MODE_LABELS: Record<StationCodingMode, StringKey> = {
  icd11_doris: "codingModeIcd11Doris",
  icd10: "codingModeIcd10",
};
const EMPTY_FACILITY: StationFacility = { name: "", code: "", type: "", address: "", district: "", state: "" };

export default function SettingsScreen() {
  const { bootstrap, reload } = useAppState();
  const styles = useUiStyles();
  const theme = useTheme();
  const [rosterSnapshot, setRosterSnapshot] = useState<StationRosterSnapshot | null>(null);
  const [stationConfigText, setStationConfigText] = useState("");
  const [receiptText, setReceiptText] = useState("");
  const [enrolmentText, setEnrolmentText] = useState<string | null>(null);
  const [transferBusy, setTransferBusy] = useState(false);
  const [transferStatus, setTransferStatus] = useState<string | null>(null);
  const [transferError, setTransferError] = useState<string | null>(null);
  const [rosterRefreshKey, setRosterRefreshKey] = useState(0);
  const [facility, setFacility] = useState<StationFacility>(EMPTY_FACILITY);
  const [facilityBusy, setFacilityBusy] = useState(false);
  const [facilityStatus, setFacilityStatus] = useState<string | null>(null);
  const [facilityError, setFacilityError] = useState<string | null>(null);
  const [settings, setSettings] = useState<StationSettings | null>(null);
  const [enabledModules, setEnabledModules] = useState<string[]>([]);
  const [codingMode, setCodingMode] = useState<StationCodingMode | null>("icd11_doris");
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [modulesNote, setModulesNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [codingNote, setCodingNote] = useState<{ ok: boolean; text: string } | null>(null);
  const facilityStyles = useMemo(() => createFacilityStyles(theme.ui), [theme.ui]);
  // The station (roster, .dvb transfer) exists only in the desktop edition, which injects a
  // per-launch token; the server app has no /station/* routes.
  const isStation = Boolean(getLocalStationLaunchToken());

  useEffect(() => {
    if (!bootstrap || !isStation) return;
    let active = true;
    void fetchStationRoster(bootstrap.csrf).then((snap) => {
      if (active) setRosterSnapshot(snap);
    });
    return () => {
      active = false;
    };
  }, [bootstrap, isStation, rosterRefreshKey]);

  useEffect(() => {
    if (!bootstrap || !isStation) return;
    let active = true;
    void fetchStationFacility(bootstrap.csrf)
      .then((f) => {
        if (active) setFacility(f);
      })
      .catch(() => {
        if (active) setFacilityError(t("facilityLoadFailed"));
      });
    return () => {
      active = false;
    };
    // Load once per mount: a fresh `bootstrap` object must not overwrite edits in progress.
  }, [Boolean(bootstrap), isStation]);

  function applySettings(next: StationSettings) {
    setSettings(next);
    setEnabledModules(next.modules.filter((m) => m.enabled).map((m) => m.code));
    setCodingMode(next.coding_mode);
  }

  useEffect(() => {
    if (!bootstrap || !isStation) return;
    let active = true;
    void fetchStationSettings(bootstrap.csrf)
      .then((next) => {
        if (active) applySettings(next);
      })
      .catch(() => {
        if (active) setModulesNote({ ok: false, text: t("settingsLoadFailed") });
      });
    return () => {
      active = false;
    };
    // Load once per mount, as the facility details: a fresh `bootstrap` must not reset choices.
    // A config import can lock modules, so it reloads them (rosterRefreshKey).
  }, [Boolean(bootstrap), isStation, rosterRefreshKey]);

  async function handleSaveSettings(
    change: { enabled_modules?: string[]; coding_mode?: StationCodingMode },
    setNote: (note: { ok: boolean; text: string } | null) => void,
    saved: StringKey,
    failed: StringKey,
  ) {
    if (!bootstrap || settingsBusy) return;
    setSettingsBusy(true);
    setNote(null);
    try {
      applySettings(await saveStationSettings(change, bootstrap.csrf));
      setNote({ ok: true, text: t(saved) });
      void reload?.();
    } catch {
      setNote({ ok: false, text: t(failed) });
    } finally {
      setSettingsBusy(false);
    }
  }

  async function handleSaveFacility() {
    if (!bootstrap || facilityBusy) return;
    if (!facility.name.trim()) {
      setFacilityStatus(null);
      setFacilityError(t("facilityNameRequired"));
      return;
    }
    setFacilityBusy(true);
    setFacilityError(null);
    setFacilityStatus(null);
    try {
      setFacility(await saveStationFacility(facility, bootstrap.csrf));
      setFacilityStatus(t("facilitySaved"));
      setRosterRefreshKey((k) => k + 1);
      void reload?.();
    } catch {
      setFacilityError(t("facilitySaveFailed"));
    } finally {
      setFacilityBusy(false);
    }
  }

  const isProvisioned = rosterSnapshot?.station_mode === "provisioned";

  async function handleImportStationConfig() {
    if (!bootstrap || transferBusy) return;
    const trimmed = stationConfigText.trim();
    if (!trimmed) {
      setTransferError(t("stationConfigPasteFirst"));
      return;
    }
    setTransferBusy(true);
    setTransferError(null);
    setTransferStatus(null);
    try {
      const res = await importStationConfig(trimmed, bootstrap.csrf);
      setRosterSnapshot(res.roster);
      setStationConfigText("");
      setRosterRefreshKey((k) => k + 1);
      void reload?.();
      setTransferStatus(
        [
          t("stationConfigImported", { id: res.station_config_id || t("stationVerifiedId") }),
          res.custodian ? t("stationConfigCustodianNote", { name: res.custodian.name }) : "",
          res.purged_ids.length > 0 ? t("stationConfigPurgedNote", { count: res.purged_ids.length }) : "",
        ]
          .filter(Boolean)
          .join(" "),
      );
    } catch {
      setTransferError(t("stationConfigImportFailed"));
    } finally {
      setTransferBusy(false);
    }
  }

  // Saves the file through the web view's download; the JSON also shows below for copying,
  // in case the shell has no download handler.
  async function handleDownloadEnrolmentFile() {
    if (!bootstrap || transferBusy) return;
    setTransferBusy(true);
    setTransferError(null);
    setTransferStatus(null);
    try {
      const file = await fetchStationEnrolmentFile(bootstrap.csrf);
      const text = JSON.stringify(file, null, 2);
      setEnrolmentText(text);
      if (typeof document !== "undefined" && typeof URL.createObjectURL === "function") {
        const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
        const link = document.createElement("a");
        link.href = url;
        link.download = "digitva-station-enrolment.json";
        link.click();
        URL.revokeObjectURL(url);
      }
      setTransferStatus(t("stationEnrolmentSaved", { deviceId: file.device_id }));
    } catch {
      setTransferError(t("stationEnrolmentFailed"));
    } finally {
      setTransferBusy(false);
    }
  }

  async function handleExportBundle() {
    if (!bootstrap || transferBusy || !isProvisioned) return;
    setTransferBusy(true);
    setTransferError(null);
    setTransferStatus(null);
    try {
      const res = await exportStationBundle(bootstrap.csrf);
      setTransferStatus(
        t("stationBundleExported", { filename: res.filename, bundleId: res.bundle_id, count: res.record_count }),
      );
      const held = heldBackRecords(res.records_held_back);
      if (held.length) setTransferError(heldBackText(held));
    } catch (error) {
      const held = error instanceof ApiError ? heldBackRecords(error.payload?.records_held_back) : [];
      setTransferError(held.length ? heldBackText(held) : t("stationBundleExportFailed"));
    } finally {
      setTransferBusy(false);
    }
  }

  async function handleImportReceipt() {
    if (!bootstrap || transferBusy) return;
    const trimmed = receiptText.trim();
    if (!trimmed) {
      setTransferError(t("stationReceiptPasteFirst"));
      return;
    }
    setTransferBusy(true);
    setTransferError(null);
    setTransferStatus(null);
    try {
      const res = await importBundleReceipt(trimmed, bootstrap.csrf);
      setReceiptText("");
      setTransferStatus(
        `${t("stationReceiptApplied", {
          bundleId: res.bundle_id || t("stationVerifiedId"),
          deleted: res.acknowledged_deleted_count,
          purged: res.purged_ids.length,
        })} ${t("stationReceiptOutcomes", {
          accepted: res.accepted_count,
          pending: res.pending_count,
          refused: res.rejected_count,
        })}`,
      );
    } catch {
      setTransferError(t("stationReceiptFailed"));
    } finally {
      setTransferBusy(false);
    }
  }

  return (
    <WebShell title={t("navSettings")}>
      <ContextualHelpBanner screen="settings" />
      <Text style={styles.headline}>{t("appearance")}</Text>
      <View style={styles.row}>
        <Button kind={theme.preference === "system" ? "primary" : "secondary"} label={t("themeSystem")} onPress={() => void theme.setPreference("system")} />
        <Button kind={theme.preference === "light" ? "primary" : "secondary"} label={t("themeLight")} onPress={() => void theme.setPreference("light")} />
        <Button kind={theme.preference === "dark" ? "primary" : "secondary"} label={t("themeDark")} onPress={() => void theme.setPreference("dark")} />
      </View>
      {bootstrap && isStation ? (
        <>
          <StationActorBar
            key={`actor-bar-${rosterRefreshKey}`}
            csrf={bootstrap.csrf}
            onActorSwitched={() => {
              setRosterRefreshKey((k) => k + 1);
              void reload?.();
            }}
          />

          <View style={facilityStyles.card} testID="station-facility-card">
            <Text style={facilityStyles.title}>{t("facilityTitle")}</Text>
            {FACILITY_FIELDS.map(({ key, label, multiline }) => (
              <View key={key} style={facilityStyles.field}>
                <Text style={facilityStyles.label}>{t(label)}</Text>
                <TextInput
                  value={facility[key]}
                  onChangeText={(text) => setFacility((f) => ({ ...f, [key]: text }))}
                  multiline={multiline}
                  accessibilityLabel={t(label)}
                  placeholderTextColor={theme.ui.mutedForeground}
                  style={[facilityStyles.input, multiline && facilityStyles.inputMultiline]}
                  testID={`facility-${key}-input`}
                />
              </View>
            ))}
            {facilityStatus ? <Text style={facilityStyles.status}>{facilityStatus}</Text> : null}
            {facilityError ? <Text style={facilityStyles.error}>{facilityError}</Text> : null}
            <View style={facilityStyles.actions}>
              <Button
                kind="primary"
                label={t("facilitySave")}
                disabled={facilityBusy}
                onPress={() => void handleSaveFacility()}
              />
            </View>
          </View>

          {settings ? (
            <View style={facilityStyles.card} testID="station-modules-card">
              <Text style={facilityStyles.title}>{t("modulesTitle")}</Text>
              <Text style={facilityStyles.label}>
                {settings.modules_locked ? t("settingsSetByProject") : t("modulesHelp")}
              </Text>
              {settings.modules.map((module) => {
                const checked = enabledModules.includes(module.code);
                return (
                  <Pressable
                    key={module.code}
                    accessibilityRole="checkbox"
                    accessibilityState={{ checked, disabled: settings.modules_locked }}
                    accessibilityLabel={module.label}
                    disabled={settings.modules_locked}
                    onPress={() =>
                      setEnabledModules((codes) =>
                        checked ? codes.filter((c) => c !== module.code) : [...codes, module.code],
                      )
                    }
                    style={facilityStyles.choice}
                    testID={`module-${module.code}`}
                  >
                    <View style={[facilityStyles.box, checked && facilityStyles.boxOn]} />
                    <Text style={facilityStyles.choiceText}>{module.label}</Text>
                  </Pressable>
                );
              })}
              {modulesNote ? (
                <Text style={modulesNote.ok ? facilityStyles.status : facilityStyles.error}>{modulesNote.text}</Text>
              ) : null}
              {settings.modules_locked ? null : (
                <View style={facilityStyles.actions}>
                  <Button
                    kind="primary"
                    label={t("modulesSave")}
                    disabled={settingsBusy}
                    onPress={() =>
                      void handleSaveSettings({ enabled_modules: enabledModules }, setModulesNote, "modulesSaved", "modulesSaveFailed")
                    }
                  />
                </View>
              )}
            </View>
          ) : modulesNote ? (
            <Text style={facilityStyles.error}>{modulesNote.text}</Text>
          ) : null}

          {settings ? (
            <View style={facilityStyles.card} testID="station-coding-mode-card">
              <Text style={facilityStyles.title}>{t("codingModeTitle")}</Text>
              <Text style={facilityStyles.label}>
                {settings.coding_mode_locked ? t("settingsSetByProject") : t("codingModeHelp")}
              </Text>
              {settings.coding_mode === null ? (
                <Text style={facilityStyles.status} testID="coding-done-on-server">{t("codingDoneOnServer")}</Text>
              ) : settings.available_coding_modes.map((mode) => {
                const selected = codingMode === mode;
                return (
                  <Pressable
                    key={mode}
                    accessibilityRole="radio"
                    accessibilityState={{ selected, disabled: settings.coding_mode_locked }}
                    accessibilityLabel={t(CODING_MODE_LABELS[mode])}
                    disabled={settings.coding_mode_locked}
                    onPress={() => setCodingMode(mode)}
                    style={facilityStyles.choice}
                    testID={`coding-mode-${mode}`}
                  >
                    <View style={[facilityStyles.box, facilityStyles.radio, selected && facilityStyles.boxOn]} />
                    <Text style={facilityStyles.choiceText}>{t(CODING_MODE_LABELS[mode])}</Text>
                  </Pressable>
                );
              })}
              {codingNote ? (
                <Text style={codingNote.ok ? facilityStyles.status : facilityStyles.error}>{codingNote.text}</Text>
              ) : null}
              {settings.coding_mode_locked ? null : (
                <View style={facilityStyles.actions}>
                  <Button
                    kind="primary"
                    label={t("codingModeSave")}
                    disabled={settingsBusy}
                    onPress={() =>
                      void handleSaveSettings({ coding_mode: codingMode ?? undefined }, setCodingNote, "codingModeSaved", "codingModeSaveFailed")
                    }
                  />
                </View>
              )}
            </View>
          ) : null}

          <StationRosterScreen
            key={`roster-screen-${rosterRefreshKey}`}
            csrf={bootstrap.csrf}
            onActorSwitched={() => {
              setRosterRefreshKey((k) => k + 1);
              void reload?.();
            }}
          />

          <View style={localStyles.transferSection} testID="station-bundle-transfer-card">
            <Text style={localStyles.sectionTitle}>{t("stationTransferTitle")}</Text>

            {transferStatus ? (
              <View style={localStyles.statusBox}>
                <Text style={localStyles.statusText}>{transferStatus}</Text>
              </View>
            ) : null}

            {transferError ? (
              <View style={localStyles.errorBox}>
                <Text style={localStyles.errorText}>{transferError}</Text>
              </View>
            ) : null}

            {!isProvisioned ? (
              <View style={localStyles.block}>
                <Text style={localStyles.blockTitle}>{t("stationEnrolmentStepTitle")}</Text>
                <Text style={localStyles.helperText}>{t("stationEnrolmentStepHelp")}</Text>
                <Pressable
                  disabled={transferBusy}
                  onPress={() => void handleDownloadEnrolmentFile()}
                  style={localStyles.actionBtn}
                  testID="download-station-enrolment-btn"
                >
                  <Text style={localStyles.actionBtnText}>{t("stationEnrolmentButton")}</Text>
                </Pressable>
                {enrolmentText ? (
                  <TextInput
                    value={enrolmentText}
                    editable={false}
                    multiline
                    style={localStyles.textArea}
                    testID="station-enrolment-text"
                  />
                ) : null}
              </View>
            ) : null}

            <View style={localStyles.block}>
              <Text style={localStyles.blockTitle}>{t("stationConfigStepTitle")}</Text>
              <Text style={localStyles.helperText}>{t("stationConfigStepHelp")}</Text>
              <TextInput
                value={stationConfigText}
                onChangeText={setStationConfigText}
                placeholder='{"station_config_format_version":1,"station_config_id":"..."}\n{"sig":"..."}'
                multiline
                style={localStyles.textArea}
              />
              <Pressable
                disabled={transferBusy}
                onPress={() => void handleImportStationConfig()}
                style={localStyles.actionBtn}
                testID="import-station-config-btn"
              >
                <Text style={localStyles.actionBtnText}>{t("stationConfigImportButton")}</Text>
              </Pressable>
            </View>

            <View style={localStyles.block}>
              <Text style={localStyles.blockTitle}>{t("stationBundleStepTitle")}</Text>
              {!isProvisioned ? (
                <Text style={localStyles.sandboxDisableNote}>{t("stationBundleSandboxNote")}</Text>
              ) : (
                <Text style={localStyles.helperText}>{t("stationBundleStepHelp")}</Text>
              )}
              <Pressable
                disabled={transferBusy || !isProvisioned}
                onPress={() => void handleExportBundle()}
                style={[
                  localStyles.actionBtn,
                  !isProvisioned && localStyles.actionBtnDisabled,
                ]}
                testID="export-dvb-bundle-btn"
              >
                <Text style={localStyles.actionBtnText}>
                  {t(isProvisioned ? "stationBundleExportButton" : "stationBundleExportButtonSandbox")}
                </Text>
              </Pressable>
            </View>

            <View style={localStyles.block}>
              <Text style={localStyles.blockTitle}>{t("stationReceiptStepTitle")}</Text>
              <Text style={localStyles.helperText}>{t("stationReceiptStepHelp")}</Text>
              <TextInput
                value={receiptText}
                onChangeText={setReceiptText}
                placeholder='{"bundle_id":"...","outcomes":[...],"purge":[...]}\n{"sig":"..."}'
                multiline
                style={localStyles.textArea}
              />
              <Pressable
                disabled={transferBusy}
                onPress={() => void handleImportReceipt()}
                style={localStyles.actionBtn}
                testID="import-dvb-receipt-btn"
              >
                <Text style={localStyles.actionBtnText}>{t("stationReceiptImportButton")}</Text>
              </Pressable>
            </View>
          </View>
        </>
      ) : null}
      <Text style={localStyles.helperText} testID="icd11-citation">{t("icd11Citation")}</Text>
    </WebShell>
  );
}

// Theme-aware (unlike the older station cards below, which hardcode the light palette).
function createFacilityStyles(tokens: UiTokens) {
  return StyleSheet.create({
    card: {
      backgroundColor: tokens.card,
      borderWidth: 1,
      borderColor: tokens.border,
      borderRadius: radius.lg,
      padding: 16,
      marginVertical: 12,
      gap: 12,
    },
    title: { fontSize: fontSize.input, fontWeight: "700", color: tokens.cardForeground },
    field: { gap: 4 },
    label: { fontSize: fontSize.caption, fontWeight: "600", color: tokens.mutedForeground },
    input: {
      borderWidth: 1,
      borderColor: tokens.input,
      borderRadius: radius.md,
      paddingHorizontal: 10,
      paddingVertical: 8,
      fontSize: fontSize.body,
      color: tokens.foreground,
      backgroundColor: tokens.background,
    },
    inputMultiline: { minHeight: 68, textAlignVertical: "top" },
    actions: { flexDirection: "row" },
    choice: { flexDirection: "row", alignItems: "center", gap: 10, minHeight: 32 },
    choiceText: { fontSize: fontSize.body, color: tokens.foreground },
    box: {
      width: 18,
      height: 18,
      borderWidth: 2,
      borderColor: tokens.input,
      borderRadius: 4,
      backgroundColor: tokens.background,
    },
    radio: { borderRadius: radius.full },
    boxOn: { backgroundColor: tokens.primary, borderColor: tokens.primary },
    status: { color: tokens.success, fontSize: fontSize.body, fontWeight: "600" },
    error: { color: tokens.destructiveText, fontSize: fontSize.body },
  });
}

const localStyles = StyleSheet.create({
  transferSection: {
    backgroundColor: palette.light.surface,
    borderWidth: 1,
    borderColor: palette.light.border,
    borderRadius: radius.lg,
    padding: 16,
    marginVertical: 12,
    gap: 14,
  },
  sectionTitle: {
    fontSize: fontSize.input,
    fontWeight: "700",
    color: palette.light.text,
  },
  block: {
    borderTopWidth: 1,
    borderTopColor: palette.light.border,
    paddingTop: 12,
    gap: 8,
  },
  blockTitle: {
    fontSize: fontSize.body,
    fontWeight: "700",
    color: palette.light.text,
  },
  helperText: {
    fontSize: fontSize.caption,
    color: palette.light.textMuted,
  },
  sandboxDisableNote: {
    fontSize: fontSize.caption,
    fontWeight: "600",
    color: palette.light.warning,
  },
  textArea: {
    borderWidth: 1,
    borderColor: palette.light.border,
    borderRadius: radius.md,
    padding: 10,
    minHeight: 68,
    fontSize: fontSize.caption,
    backgroundColor: palette.light.background,
  },
  actionBtn: {
    alignSelf: "flex-start",
    backgroundColor: palette.light.accent,
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: radius.md,
  },
  actionBtnDisabled: {
    backgroundColor: palette.light.disabled,
  },
  actionBtnText: {
    color: palette.light.onAccent,
    fontSize: fontSize.body,
    fontWeight: "700",
  },
  statusBox: {
    backgroundColor: ui.light.chart[2].tint,
    borderColor: ui.light.chart[2].bar,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: 10,
  },
  statusText: {
    color: palette.light.success,
    fontSize: fontSize.body,
    fontWeight: "600",
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
