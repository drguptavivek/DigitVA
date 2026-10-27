/**
 * Export, backup and restore actions on the standalone home. Rendered only for a standalone account
 * (dataActionsAllowed); an enrolled account never sees them. The policy warning is shown before every action.
 */
import * as DocumentPicker from "expo-document-picker";
import { useEffect, useState } from "react";
import { Switch, Text, TextInput, View } from "react-native";

import { ConfirmDialog } from "../ConfirmDialog";
import type { Db } from "../drafts";
import { t } from "../i18n";
import { Button, errorText, useUiStyles } from "../ui";
import { BackupError, backupAndShare, passphraseValid, restoreBackup } from "./backup";
import { exportAndShare, type ExportFormat } from "./export";
import { sweepExportLeftovers } from "./shareFile";

type Panel = "export" | "backup" | "restore" | null;

export function DataActions({ db, userId, onChanged }: { db: Db; userId: string; onChanged: () => void }) {
  const styles = useUiStyles();
  const [panel, setPanel] = useState<Panel>(null);
  const [omit, setOmit] = useState(true);
  const [pass, setPass] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [pendingFile, setPendingFile] = useState<{ uri: string; count: number } | null>(null);

  useEffect(sweepExportLeftovers, []);

  const open = (next: Panel) => { setPanel(next); setPass(""); setAgain(""); setMessage(""); };

  async function run(work: () => Promise<string>) {
    setBusy(true);
    setMessage("");
    try {
      setMessage(await work());
    } catch (caught) {
      if (caught instanceof BackupError) {
        setMessage(caught.code === "passphrase_short" ? t("dataPassphraseShort") : caught.code === "unsupported_backup" ? t("dataRestoreUnsupported") : t("dataRestoreBad"));
      } else {
        setMessage(errorText(caught));
      }
    } finally {
      setBusy(false);
    }
  }

  const doExport = (format: ExportFormat) => run(async () => {
    const count = await exportAndShare(db, userId, format, omit);
    return count === 0 ? t("dataExportNone") : t("dataExported", { count });
  });

  const doBackup = () => {
    if (!passphraseValid(pass)) return setMessage(t("dataPassphraseShort"));
    if (pass !== again) return setMessage(t("dataPassphraseMismatch"));
    return run(async () => {
      await backupAndShare(db, userId, pass);
      onChanged();
      setPass(""); setAgain("");
      return t("dataBackupDone");
    });
  };

  const doRestore = (uri: string, confirm: boolean) => run(async () => {
    try {
      const result = await restoreBackup(db, userId, uri, pass, confirm);
      setPendingFile(null);
      onChanged();
      return t("dataRestoreDone", { restored: result.restored, skipped: result.skipped });
    } catch (caught) {
      if (caught instanceof BackupError && caught.code === "newer_local") {
        setPendingFile({ uri, count: caught.count });
        return "";
      }
      throw caught;
    }
  });

  const pickAndRestore = async () => {
    if (!passphraseValid(pass)) return setMessage(t("dataPassphraseShort"));
    const picked = await DocumentPicker.getDocumentAsync({ type: "*/*", multiple: false, copyToCacheDirectory: true });
    if (picked.canceled || !picked.assets[0]) return undefined;
    return doRestore(picked.assets[0].uri, false);
  };

  return (
    <View style={[styles.card, { gap: 8 }]}>
      <Button kind="secondary" label={t("dataExport")} onPress={() => open("export")} />
      <Button kind="secondary" label={t("dataBackup")} onPress={() => open("backup")} />
      <Button kind="secondary" label={t("dataRestore")} onPress={() => open("restore")} />
      {panel ? <Text style={styles.muted}>{t("dataWarning")}</Text> : null}
      {panel === "export" ? (
        <>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <Switch value={omit} onValueChange={setOmit} accessibilityLabel={t("dataExportOmit")} />
            <Text style={[styles.text, { flex: 1 }]}>{t("dataExportOmit")}</Text>
          </View>
          <Button label={t("dataExportCsv")} loading={busy} onPress={() => void doExport("csv")} />
          <Button label={t("dataExportJson")} loading={busy} onPress={() => void doExport("json")} />
        </>
      ) : null}
      {panel === "backup" || panel === "restore" ? (
        <>
          <TextInput style={styles.input} value={pass} onChangeText={setPass} secureTextEntry autoCapitalize="none" autoCorrect={false} accessibilityLabel={t("dataPassphrase")} placeholder={t("dataPassphrase")} />
          {panel === "backup" ? (
            <>
              <TextInput style={styles.input} value={again} onChangeText={setAgain} secureTextEntry autoCapitalize="none" autoCorrect={false} accessibilityLabel={t("dataPassphraseConfirm")} placeholder={t("dataPassphraseConfirm")} />
              <Button label={t("dataBackup")} loading={busy} onPress={() => void doBackup()} />
            </>
          ) : (
            <Button label={t("dataRestorePick")} loading={busy} onPress={() => void pickAndRestore()} />
          )}
        </>
      ) : null}
      {message ? <Text accessibilityRole="alert" style={styles.text}>{message}</Text> : null}
      {panel ? <Button kind="secondary" label={t("dataClose")} onPress={() => open(null)} /> : null}
      {pendingFile ? (
        <ConfirmDialog
          title={t("dataRestoreNewerTitle")}
          message={t("dataRestoreNewer", { count: pendingFile.count })}
          confirmLabel={t("dataRestoreReplace")}
          destructive
          onConfirm={() => void doRestore(pendingFile.uri, true)}
          onCancel={() => setPendingFile(null)}
        />
      ) : null}
    </View>
  );
}
