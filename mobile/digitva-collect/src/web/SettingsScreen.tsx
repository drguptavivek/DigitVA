import { useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { useAppState } from "../AppState";
import { t } from "../i18n";
import {
  exportStationBundle,
  fetchStationRoster,
  importBundleReceipt,
  importStationConfig,
  type StationRosterSnapshot,
} from "../roster";
import { Button, useUiStyles } from "../ui";
import { fontSize, palette, radius, ui, useTheme } from "../theme";
import { WebShell } from "./common";
import { ContextualHelpBanner } from "./ContextualHelp";
import { StationActorBar, StationRosterScreen } from "./StationRosterScreen";

export default function SettingsScreen() {
  const { bootstrap, reload } = useAppState();
  const styles = useUiStyles();
  const theme = useTheme();
  const [rosterSnapshot, setRosterSnapshot] = useState<StationRosterSnapshot | null>(null);
  const [stationConfigText, setStationConfigText] = useState("");
  const [receiptText, setReceiptText] = useState("");
  const [transferBusy, setTransferBusy] = useState(false);
  const [transferStatus, setTransferStatus] = useState<string | null>(null);
  const [transferError, setTransferError] = useState<string | null>(null);
  const [rosterRefreshKey, setRosterRefreshKey] = useState(0);

  useEffect(() => {
    if (!bootstrap) return;
    let active = true;
    void fetchStationRoster(bootstrap.csrf).then((snap) => {
      if (active) setRosterSnapshot(snap);
    });
    return () => {
      active = false;
    };
  }, [bootstrap, rosterRefreshKey]);

  const isProvisioned = rosterSnapshot?.station_mode === "provisioned";

  async function handleImportStationConfig() {
    if (!bootstrap || transferBusy) return;
    const trimmed = stationConfigText.trim();
    if (!trimmed) {
      setTransferError("Paste the two-line signed .station-config content before importing.");
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
      const purgeNote =
        res.purged_ids.length > 0
          ? ` Purged ${res.purged_ids.length} withdrawn/closed record ID(s).`
          : "";
      const custodianNote = res.custodian ? ` Custodian: ${res.custodian.name}.` : "";
      setTransferStatus(
        `Imported signed station config ${res.station_config_id || "(verified)"}.${custodianNote}${purgeNote}`,
      );
    } catch {
      setTransferError(
        "Station config import failed. Verify the two-line signature and custodian onboarding.",
      );
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
        `Exported signed bundle ${res.filename} (bundle_id: ${res.bundle_id}, ${res.record_count} record(s)).`,
      );
    } catch {
      setTransferError(
        "Could not export .dvb bundle. Ensure this station is onboarded with a valid signing key and non-expired station config.",
      );
    } finally {
      setTransferBusy(false);
    }
  }

  async function handleImportReceipt() {
    if (!bootstrap || transferBusy) return;
    const trimmed = receiptText.trim();
    if (!trimmed) {
      setTransferError("Paste the signed .dvb receipt content before importing.");
      return;
    }
    setTransferBusy(true);
    setTransferError(null);
    setTransferStatus(null);
    try {
      const res = await importBundleReceipt(trimmed, bootstrap.csrf);
      setReceiptText("");
      setTransferStatus(
        `Applied signed receipt for bundle ${res.bundle_id || "(verified)"}: deleted ${res.acknowledged_deleted_count} acknowledged record(s) and purged ${res.purged_ids.length} withdrawn/closed ID(s).`,
      );
    } catch {
      setTransferError(
        "Bundle receipt verification failed. Ensure the receipt signature and bundle ID match this station.",
      );
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
      {bootstrap ? (
        <>
          <StationActorBar
            key={`actor-bar-${rosterRefreshKey}`}
            csrf={bootstrap.csrf}
            onActorSwitched={() => {
              setRosterRefreshKey((k) => k + 1);
              void reload?.();
            }}
          />

          <View style={localStyles.transferSection} testID="station-bundle-transfer-card">
            <Text style={localStyles.sectionTitle}>
              Offline Station Provisioning &amp; Sealed Bundle Transfer (.dvb)
            </Text>

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

            <View style={localStyles.block}>
              <Text style={localStyles.blockTitle}>
                1. Import Signed Station Config (.station-config)
              </Text>
              <Text style={localStyles.helperText}>
                Paste the two-line signed station config file exported by an admin or project data manager. Applies the verified custodian, read-only station roster, project consent config, sealed PII field set, and purge list.
              </Text>
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
                <Text style={localStyles.actionBtnText}>Import Signed Station Config</Text>
              </Pressable>
            </View>

            <View style={localStyles.block}>
              <Text style={localStyles.blockTitle}>
                2. Export Signed &amp; Sealed Bundle (.dvb)
              </Text>
              {!isProvisioned ? (
                <Text style={localStyles.sandboxDisableNote}>
                  Disabled in Standalone Sandbox mode: Sandbox data is local-only and never ingestable into a server project. Import a signed Station Config with a verified custodian first.
                </Text>
              ) : (
                <Text style={localStyles.helperText}>
                  Exports unacknowledged registrations, consents, interviews, coding results, and station supervisor corrections into a signed, sealed .dvb archive for courier upload.
                </Text>
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
                  {isProvisioned
                    ? "Export Signed .dvb Bundle"
                    : "Export .dvb Bundle (Provisioned Stations Only)"}
                </Text>
              </Pressable>
            </View>

            <View style={localStyles.block}>
              <Text style={localStyles.blockTitle}>
                3. Import Signed Bundle Receipt &amp; Apply Purge List
              </Text>
              <Text style={localStyles.helperText}>
                Paste the signed receipt returned after central server bundle ingestion. Deletes acknowledged records (accepted, duplicate, superseded) from local storage and purges any withdrawn consent or closed case UUIDs in the purge list.
              </Text>
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
                <Text style={localStyles.actionBtnText}>Import Signed .dvb Receipt</Text>
              </Pressable>
            </View>
          </View>

          <StationRosterScreen
            key={`roster-screen-${rosterRefreshKey}`}
            csrf={bootstrap.csrf}
            onActorSwitched={() => {
              setRosterRefreshKey((k) => k + 1);
              void reload?.();
            }}
          />
        </>
      ) : null}
    </WebShell>
  );
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
