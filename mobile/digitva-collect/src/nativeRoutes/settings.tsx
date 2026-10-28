/**
 * Phone Settings, in sections: Account, Active or demo, Language, Security, Sync, Help & support, About. The
 * enrolled server is shown read-only and changed only by re-enrolling (src/reEnrolConfirm.ts). Active or demo
 * switches between the phone's two enrolments (docs/policy/public-demo.md section 10.1). The questionnaire's own
 * language is chosen in the form's menu. Account also has Delete my account and the privacy and data-requests
 * links (docs/policy/public-privacy-and-data-requests.md section 8): on the Demo slot it deletes the account at
 * once after the password; otherwise it sends a deletion request the programme team confirms.
 * Server controls belong only to the selected server account; standalone ignores retained enrolment.
 */
import { useRouter } from "expo-router";
import { useEffect, useState, type ReactNode } from "react";
import Constants from "expo-constants";
import { canUseBiometricAuthentication } from "expo-secure-store";
import { Alert, Linking, Switch, Text, TextInput, View } from "react-native";

import { ApiError, type AccessSummary, type AccountDevice } from "../api";
import { decommissionMyDevice, deleteDemoAccount, listMyDevices, refreshAccessSummary, requestAccountDeletion, type Slot } from "../auth";
import { useAppState } from "../AppState";
import type { Db } from "../drafts";
import { isUnlocked, openInterviewerDb } from "../interviewerDb";
import { DataActions } from "../standalone/DataActions";
import StandaloneConsentNoticeSettings from "../standalone/StandaloneConsentNoticeSettings";
import { APP_VERSION } from "../appVersion";
import { isPlayDistribution, isPlusVariant } from "../appVariant";
import { canUseOfflineCoding } from "../codingCapabilities";
import { readDevicePermissions, requestDevicePermission, type DevicePermissionName, type DevicePermissionState } from "../devicePermissions.native";
import { IDLE_LOCK_MS } from "../autoLock";
import { exportErrors } from "../errorExport";
import { t, UI_LOCALES } from "../i18n";
import { clock, useShell } from "../nativeShell/shellContext";
import { confirmReEnrol, reEnrolDevice } from "../reEnrolConfirm";
import { useToast } from "../toast";
import { checkForUpdate, type UpdateResult } from "../updateCheck";
import { Button, errorText, Screen, useUiStyles } from "../ui";
import { CodingCaseChips } from "../ui/CodingCaseChips";
import { TelemetrySettings } from "../TelemetrySettings";
import { setIcd11DorisEnabled, useIcd11DorisPreference } from "../icd11DorisPreference";
import { biometricEnabled, screenLockAvailable, screenLockEnabled, turnOffBiometric, turnOffScreenLock } from "../vault";

function Section({ title, children }: { title: string; children: ReactNode }) {
  const styles = useUiStyles();
  return (
    <View style={styles.card}>
      <Text accessibilityRole="header" style={styles.headline}>{title}</Text>
      {children}
    </View>
  );
}

export default function NativeSettings() {
  const router = useRouter();
  const toast = useToast();
  const shell = useShell();
  const { device, accounts, slot, switchSlot, uiLocale, chooseUiLocale, lockNow, reload } = useAppState();
  const styles = useUiStyles();
  const [biometricUsers, setBiometricUsers] = useState<Set<string>>(new Set());
  const [screenLockUsers, setScreenLockUsers] = useState<Set<string>>(new Set());
  const [screenLockPossible, setScreenLockPossible] = useState(false);
  const [optionsVersion, setOptionsVersion] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [checking, setChecking] = useState(false);
  const [update, setUpdate] = useState<UpdateResult>();
  const [devicePermissions, setDevicePermissions] = useState<Record<DevicePermissionName, DevicePermissionState>>();
  const [accessSummary, setAccessSummary] = useState<AccessSummary>();
  const [permissionsBusy, setPermissionsBusy] = useState(false);
  const [permissionsError, setPermissionsError] = useState("");
  const [permissionsMessage, setPermissionsMessage] = useState("");
  const [devices, setDevices] = useState<AccountDevice[]>();
  const [devicesBusy, setDevicesBusy] = useState(false);
  const [deviceBusyId, setDeviceBusyId] = useState<string>();
  const [devicesError, setDevicesError] = useState("");
  /** Delete my account: undefined = closed; on the Demo slot, the password field is open. */
  const [deletePassword, setDeletePassword] = useState<string>();
  const [deleteMessage, setDeleteMessage] = useState("");
  const icd11DorisPreference = useIcd11DorisPreference();
  const [icd11DorisError, setIcd11DorisError] = useState("");
  useEffect(() => {
    let active = true;
    void Promise.all(accounts.map(async (account) => [account.user_id, await biometricEnabled(account.user_id)] as const))
      .then((entries) => {
        if (active) setBiometricUsers(new Set(entries.filter(([, enabled]) => enabled).map(([userId]) => userId)));
      })
      .catch(() => {
        if (!active) return;
        setBiometricUsers(new Set());
        setError(t("errGeneric"));
      });
    void Promise.all(accounts.map(async (account) => [account.user_id, await screenLockEnabled(account.user_id)] as const))
      .then((entries) => {
        if (active) setScreenLockUsers(new Set(entries.filter(([, enabled]) => enabled).map(([userId]) => userId)));
      })
      .catch(() => undefined);
    void screenLockAvailable().then((ok) => active && setScreenLockPossible(ok)).catch(() => undefined);
    return () => {
      active = false;
    };
  }, [accounts, optionsVersion]);
  const biometricAvailable = canUseBiometricAuthentication();
  const account = accounts.find((item) => item.user_id === shell.userId);
  useEffect(() => {
    let active = true;
    const userId = account?.user_id;
    if (!shell.server || !userId || account?.needs_sign_in) {
      setDevices(undefined);
      setDevicesError("");
      return () => { active = false; };
    }
    setDevicesBusy(true);
    void listMyDevices(userId).then((listed) => {
      if (!active) return;
      setDevices(listed);
      setDevicesError("");
    }).catch((caught) => {
      if (active) setDevicesError(errorText(caught));
    }).finally(() => {
      if (active) setDevicesBusy(false);
    });
    return () => { active = false; };
  }, [shell.server, account?.user_id, account?.needs_sign_in]);
  useEffect(() => {
    setUpdate(undefined);
    setAccessSummary(undefined);
  }, [shell.server]);
  useEffect(() => {
    let active = true;
    void readDevicePermissions().then((permissions) => {
      if (active) setDevicePermissions(permissions);
    }).catch((caught) => {
      if (active) setPermissionsError(errorText(caught));
    });
    return () => {
      active = false;
    };
  }, []);
  // Encrypted backup of unsent work for an enrolled account (Plus); the standalone home has its own actions.
  const [backupDb, setBackupDb] = useState<Db>();
  const backupUserId = isPlusVariant() && account && !account.standalone && isUnlocked(account.user_id) ? account.user_id : undefined;
  useEffect(() => {
    setBackupDb(undefined);
    if (backupUserId) void openInterviewerDb(backupUserId).then(setBackupDb).catch(() => undefined);
  }, [backupUserId]);
  async function requestBiometric(userId: string) {
    setBusy(true);
    setError("");
    try {
      if (!(await lockNow())) {
        setError(t("errGeneric"));
        return;
      }
      router.push({ pathname: "/unlock", params: { userId, enableBiometric: "1" } });
    } catch {
      setError(t("errGeneric"));
    } finally {
      setBusy(false);
    }
  }
  /** Turn the screen-lock option on (needs the PIN, as fingerprint does) or either option off. */
  async function requestScreenLock(userId: string) {
    setBusy(true);
    setError("");
    try {
      if (!(await lockNow())) {
        setError(t("errGeneric"));
        return;
      }
      router.push({ pathname: "/unlock", params: { userId, enableScreenLock: "1" } });
    } catch {
      setError(t("errGeneric"));
    } finally {
      setBusy(false);
    }
  }
  async function turnOff(turnOffOption: (userId: string) => Promise<void>, userId: string) {
    setError("");
    try {
      await turnOffOption(userId);
      setOptionsVersion((n) => n + 1);
    } catch {
      setError(t("errGeneric"));
    }
  }
  async function reEnrol() {
    setBusy(true);
    setError("");
    try {
      await reEnrolDevice(accounts, lockNow);
      await reload();
      // Settings sits above Home, so Home's redirect to /enrol would not run. Demo re-enrols
      // through Try the demo: a QR enrolment there would fill the Active slot instead.
      router.replace(slot === "demo" ? "/demo" : "/enrol");
    } catch (caught) {
      setError(caught instanceof Error && caught.message === "unsent_work" ? t("reEnrolBlocked") : t("errGeneric"));
    } finally {
      setBusy(false);
    }
  }
  function requestReEnrol() {
    setError("");
    confirmReEnrol(accounts, () => void reEnrol()).catch(() => setError(t("errGeneric")));
  }
  async function chooseSlot(next: Slot) {
    setBusy(true);
    setError("");
    try {
      if (!(await switchSlot?.(next))) setError(t("errGeneric"));
    } catch {
      setError(t("errGeneric"));
    } finally {
      setBusy(false);
    }
  }
  async function changeIcd11DorisPreference(enabled: boolean) {
    setIcd11DorisError("");
    try {
      await setIcd11DorisEnabled(enabled);
    } catch {
      setIcd11DorisError(t("icd11DorisPreferenceSaveError"));
    }
  }
  async function shareErrors() {
    setExporting(true);
    try {
      const count = await exportErrors();
      toast.show(count ? { kind: "success", text: t("exportErrorsShared", { count }) } : { kind: "info", text: t("exportErrorsNone") });
    } catch (caught) {
      toast.show({ kind: "error", text: errorText(caught) });
    } finally {
      setExporting(false);
    }
  }
  async function checkNow() {
    if (!shell.server) return;
    setChecking(true);
    try {
      setUpdate(await checkForUpdate(shell.server));
    } finally {
      setChecking(false);
    }
  }
  async function openPlayListing() {
    setError("");
    const packageName = Constants.expoConfig?.android?.package;
    if (!packageName) {
      setError(t("errGeneric"));
      return;
    }
    const listing = `https://play.google.com/store/apps/details?id=${encodeURIComponent(packageName)}`;
    try {
      await Linking.openURL(`market://details?id=${encodeURIComponent(packageName)}`);
    } catch {
      try {
        await Linking.openURL(listing);
      } catch {
        setError(t("errGeneric"));
      }
    }
  }
  function accessStatus(value: boolean | undefined): string {
    return value === true ? t("permissionsStatusAllowed") : value === false ? t("permissionsStatusUnavailable") : t("permissionsStatusUnknown");
  }
  function devicePermissionStatus(value: DevicePermissionState | undefined): string {
    if (!value) return t("permissionsStatusUnknown");
    if (value.granted) return t("permissionsStatusAllowed");
    return value.canAskAgain ? t("permissionsStatusNotGranted") : t("permissionsStatusBlocked");
  }
  async function checkPermissions() {
    setPermissionsBusy(true);
    setPermissionsError("");
    try {
      setDevicePermissions(await readDevicePermissions());
      if (shell.sync.offline || account?.standalone) {
        setAccessSummary(undefined);
        setPermissionsMessage(t("permissionsOffline"));
      } else if (!shell.server || !shell.userId) {
        setAccessSummary(undefined);
        setPermissionsMessage(t("permissionsStatusUnknown"));
      } else {
        const refreshed = await refreshAccessSummary(shell.userId);
        if (!refreshed) {
          setAccessSummary(undefined);
          setPermissionsMessage(t("permissionsOffline"));
        } else {
          setAccessSummary(refreshed);
          setPermissionsMessage("");
          await reload();
        }
      }
    } catch (caught) {
      setPermissionsError(errorText(caught));
    } finally {
      setPermissionsBusy(false);
    }
  }
  async function enableDevicePermission(name: DevicePermissionName) {
    setPermissionsBusy(true);
    setPermissionsError("");
    try {
      const permission = await requestDevicePermission(name);
      setDevicePermissions((current) => ({ ...(current ?? { camera: permission, microphone: permission }), [name]: permission }));
    } catch (caught) {
      setPermissionsError(errorText(caught));
    } finally {
      setPermissionsBusy(false);
    }
  }
  function openDeviceSettings() {
    void Linking.openSettings().catch((caught) => setPermissionsError(errorText(caught)));
  }
  async function retryDevices() {
    const userId = account?.user_id;
    if (!shell.server || !userId || account?.needs_sign_in) return;
    setDevicesBusy(true);
    setDevicesError("");
    try {
      setDevices(await listMyDevices(userId));
    } catch (caught) {
      setDevicesError(errorText(caught));
    } finally {
      setDevicesBusy(false);
    }
  }
  async function removeDevice(deviceToRemove: AccountDevice) {
    if (!shell.server || !account) return;
    setDeviceBusyId(deviceToRemove.device_id);
    setDevicesError("");
    try {
      if (deviceToRemove.current && !(await lockNow())) {
        setDevicesError(t("errGeneric"));
        return;
      }
      const result = await decommissionMyDevice(account.user_id, deviceToRemove.device_id);
      if (result.current) {
        setDevices((current) => current?.filter((item) => item.device_id !== deviceToRemove.device_id));
        await reload();
      } else {
        // Removing another phone changes no local session or encrypted data; just refresh this list.
        setDevices(await listMyDevices(account.user_id));
      }
    } catch (caught) {
      setDevicesError(errorText(caught));
    } finally {
      setDeviceBusyId(undefined);
    }
  }
  function confirmDeviceRemoval(deviceToRemove: AccountDevice) {
    Alert.alert(t("deviceDecommission"), t("deviceDecommissionConfirm"), [
      { text: t("cancel"), style: "cancel" },
      { text: t("deviceDecommission"), style: "destructive", onPress: () => void removeDevice(deviceToRemove) },
    ]);
  }
  /** The refusal a demo self-delete shows, by the server's code and guard reason. */
  function deleteErrorText(caught: unknown): string {
    if (!(caught instanceof ApiError)) return errorText(caught);
    if (caught.code === "wrong_password") return t("deleteAccountWrongPassword");
    if (caught.code !== "deletion_refused") return errorText(caught);
    const reason = caught.payload?.reason;
    if (reason === "shared_case") return t("deleteAccountRefusedShared");
    if (reason === "grant_outside_demo" || reason === "not_demo_project") return t("deleteAccountRefusedOutside");
    return t("deleteAccountRefusedUnavailable");
  }
  async function deleteDemo(userId: string, password: string) {
    setBusy(true);
    setError("");
    try {
      if (!(await lockNow())) {
        setError(t("errGeneric"));
        return;
      }
      await deleteDemoAccount(userId, password);
      toast.show({ kind: "success", text: t("deleteAccountDone") });
      setDeletePassword(undefined);
      await reload();
      router.replace("/");
    } catch (caught) {
      setError(deleteErrorText(caught));
    } finally {
      setBusy(false);
    }
  }
  async function requestDeletion(userId: string) {
    setBusy(true);
    setError("");
    try {
      await requestAccountDeletion(userId);
      setDeleteMessage(t("deleteAccountRequestSent"));
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  }
  /** Demo: open the password field, then confirm; staff: confirm, then send the request. */
  function pressDeleteAccount(userId: string) {
    setError("");
    if (slot !== "demo") {
      Alert.alert(t("deleteAccount"), t("deleteAccountStaffConfirm"), [
        { text: t("cancel"), style: "cancel" },
        { text: t("deleteAccountSend"), onPress: () => void requestDeletion(userId) },
      ]);
      return;
    }
    if (deletePassword === undefined) {
      setDeletePassword("");
      return;
    }
    if (!deletePassword) {
      setError(t("deleteAccountWrongPassword"));
      return;
    }
    const password = deletePassword;
    Alert.alert(t("deleteAccount"), t("deleteAccountDemoConfirm"), [
      { text: t("cancel"), style: "cancel" },
      { text: t("deleteAccountDelete"), style: "destructive", onPress: () => void deleteDemo(userId, password) },
    ]);
  }
  const canDelete = shell.server && account && !account.needs_sign_in;
  const { sync } = shell;
  const activeProject = accessSummary?.projects.find((project) => project.project_id === device?.project_id);
  const projectCollectionAccess = activeProject ? activeProject.actions.interview.length > 0 : undefined;
  const projectCodingAccess = activeProject
    ? activeProject.grants.some((grant) => grant.active && grant.codes === true && (grant.role === "coder" || grant.role === "coding_tester"))
    : undefined;
  return (
    <Screen title={t("settings")}>
      <Section title={t("settingsAccount")}>
        {account ? <Text style={styles.text}>{account.name}</Text> : accounts.map((item) => <Text key={item.user_id} style={styles.text}>{item.name}</Text>)}
        {account && shell.userId ? <Button kind="secondary" label={t("profileAccessTitle")} onPress={() => router.push({ pathname: "/profile-access", params: { userId: shell.userId } })} /> : null}
        {shell.server && device ? (
          <>
            <Text style={styles.muted}>{t("enrolledServer")}</Text>
            <Text style={styles.text} selectable>{shell.server}</Text>
            <Text style={styles.muted}>{t("deviceLabel")}</Text>
            <Text style={styles.text} selectable>{device.device_id}</Text>
            <Button kind="secondary" label={t("privacyPolicy")} onPress={() => void Linking.openURL(`${shell.server}/privacy`).catch(() => undefined)} />
            <Button kind="secondary" label={t("dataRequests")} onPress={() => void Linking.openURL(`${shell.server}/data-requests`).catch(() => undefined)} />
          </>
        ) : null}
        {account && canDelete ? (
          <>
            <Text style={styles.muted}>{t(slot === "demo" ? "deleteAccountDemoNote" : "deleteAccountStaffNote")}</Text>
            {deletePassword !== undefined ? (
              <>
                <Text style={styles.muted}>{t("deleteAccountPasswordPrompt")}</Text>
                <TextInput
                  style={styles.input}
                  accessibilityLabel={t("password")}
                  value={deletePassword}
                  onChangeText={setDeletePassword}
                  secureTextEntry
                  autoCapitalize="none"
                  autoCorrect={false}
                  autoComplete="current-password"
                />
              </>
            ) : null}
            <Button kind="danger" label={t("deleteAccount")} loading={busy} disabled={busy} onPress={() => pressDeleteAccount(account.user_id)} />
            {deleteMessage ? <Text style={styles.text}>{deleteMessage}</Text> : null}
          </>
        ) : null}
      </Section>
      {account?.standalone ? (
        <Section title={t("standaloneConsentNoticeTitle")}>
          <StandaloneConsentNoticeSettings />
        </Section>
      ) : null}
      {shell.server && account && !account.needs_sign_in ? (
        <Section title={t("devicesTitle")}>
          {devices ? <Text style={styles.muted}>{t("devicesCount", { count: devices.length })}</Text> : null}
          {devicesBusy && !devices ? <Text style={styles.muted}>{t("devicesLoading")}</Text> : null}
          {devices?.length === 0 ? <Text style={styles.muted}>{t("devicesNone")}</Text> : null}
          {devices?.map((item) => (
            <View key={item.device_id} style={{ gap: 8 }}>
              <Text style={styles.text}>{item.name || item.platform}{item.current ? ` · ${t("deviceCurrent")}` : ""}</Text>
              <Text style={styles.muted}>{`${item.platform} · ${item.app_version ?? ""}`}</Text>
              <Button
                kind="danger"
                label={t("deviceDecommission")}
                loading={deviceBusyId === item.device_id}
                disabled={devicesBusy || deviceBusyId !== undefined}
                onPress={() => confirmDeviceRemoval(item)}
              />
            </View>
          ))}
          {devicesError ? <Text accessibilityRole="alert" style={styles.error}>{devicesError}</Text> : null}
          <Button
            kind="secondary"
            label={t(devices ? "devicesRefresh" : "devicesRetry")}
            loading={devicesBusy}
            disabled={devicesBusy || deviceBusyId !== undefined}
            onPress={() => void retryDevices()}
          />
        </Section>
      ) : null}
      {!account?.standalone ? (
        <Section title={t("settingsSlot")}>
          {(["active", "demo"] as const).map((option) => (
            <Button
              key={option}
              kind={option === slot ? "primary" : "secondary"}
              label={t(option === "active" ? "slotActive" : "slotDemo")}
              disabled={busy}
              onPress={() => {
                if (option !== slot) void chooseSlot(option);
              }}
            />
          ))}
          <Text style={styles.muted}>{t("slotNote")}</Text>
        </Section>
      ) : null}
      <Section title={t("settingsLanguage")}>
        <Text style={styles.muted}>{t("appLanguage")}</Text>
        {UI_LOCALES.map((locale) => (
          <Button
            key={locale.code}
            kind={locale.code === uiLocale ? "primary" : "secondary"}
            label={locale.label}
            onPress={() => void chooseUiLocale(locale.code)}
          />
        ))}
        <Text style={styles.muted}>{t("questionnaireLanguageNote")}</Text>
      </Section>
      <Section title={t("settingsSecurity")}>
        <Text style={styles.text}>{t("autoLockInfo", { minutes: Math.round(IDLE_LOCK_MS / 60_000) })}</Text>
        {biometricAvailable && accounts.map((item) => biometricUsers.has(item.user_id) ? (
          <View key={`biometric-on-${item.user_id}`} style={{ gap: 8 }}>
            <Text style={styles.muted}>{`${t("biometricOn")}: ${item.name}`}</Text>
            <Button kind="secondary" label={`${t("biometricOff")}: ${item.name}`} onPress={() => void turnOff(turnOffBiometric, item.user_id)} />
          </View>
        ) : item.signed_out ? null : (
          // Turning it on unlocks with the PIN, which a signed-out profile gets only after signing in again.
          <Button
            key={`biometric-${item.user_id}`}
            kind="secondary"
            label={`${t("biometricEnable")}: ${item.name}`}
            loading={busy}
            disabled={busy}
            onPress={() => void requestBiometric(item.user_id)}
          />
        ))}
        {accounts.map((item) => screenLockUsers.has(item.user_id) ? (
          <View key={`screen-lock-on-${item.user_id}`} style={{ gap: 8 }}>
            <Text style={styles.muted}>{`${t("screenLockOn")}: ${item.name}`}</Text>
            <Button kind="secondary" label={`${t("screenLockOff")}: ${item.name}`} onPress={() => void turnOff(turnOffScreenLock, item.user_id)} />
          </View>
        ) : screenLockPossible && !item.signed_out ? (
          <Button
            key={`screen-lock-${item.user_id}`}
            kind="secondary"
            label={`${t("screenLockEnable")}: ${item.name}`}
            loading={busy}
            disabled={busy}
            onPress={() => void requestScreenLock(item.user_id)}
          />
        ) : null)}
      </Section>
      <Section title={t("icd11DorisPreferenceSection")}>
        <Text style={styles.text}>{t("icd11DorisPreferenceDescription")}</Text>
        <Text style={styles.muted}>{t("icd11DorisPreferenceScope")}</Text>
        <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
          <Text style={[styles.text, { flex: 1 }]}>{t("icd11DorisPreferenceTitle")}</Text>
          <Switch
            accessibilityLabel={t("icd11DorisPreferenceTitle")}
            value={icd11DorisPreference.enabled}
            disabled={!icd11DorisPreference.ready}
            onValueChange={(value) => void changeIcd11DorisPreference(value)}
          />
        </View>
        {icd11DorisError ? <Text accessibilityRole="alert" style={styles.error}>{icd11DorisError}</Text> : null}
      </Section>
      <Section title={t("settingsPermissions")}>
        <Text style={styles.muted}>{t("permissionsHint")}</Text>
        <Text style={styles.text}>{t("permissionsCollectionAccess", { status: accessStatus(activeProject ? projectCollectionAccess : account?.collection_access) })}</Text>
        <Text style={styles.text}>{t("permissionsCodingAccess", { status: accessStatus(activeProject ? projectCodingAccess : account?.coding_access) })}</Text>
        {activeProject ? <Text style={styles.muted}>{t("permissionsProject", { project: activeProject.project_name })}</Text> : shell.server && device ? <Text style={styles.muted}>{t("permissionsProjectCached", { project: device.project_name })}</Text> : null}
        <Text style={styles.text}>{t("permissionsCamera", { status: devicePermissionStatus(devicePermissions?.camera) })}</Text>
        {devicePermissions?.camera && !devicePermissions.camera.granted ? (
          <Button
            kind="secondary"
            label={devicePermissions?.camera?.canAskAgain ? t("permissionsEnableCamera") : t("permissionsOpenSettings")}
            loading={permissionsBusy}
            disabled={permissionsBusy}
            onPress={() => devicePermissions?.camera?.canAskAgain ? void enableDevicePermission("camera") : openDeviceSettings()}
          />
        ) : null}
        <Text style={styles.text}>{t("permissionsMicrophone", { status: devicePermissionStatus(devicePermissions?.microphone) })}</Text>
        {devicePermissions?.microphone && !devicePermissions.microphone.granted ? (
          <Button
            kind="secondary"
            label={devicePermissions?.microphone?.canAskAgain ? t("permissionsEnableMicrophone") : t("permissionsOpenSettings")}
            loading={permissionsBusy}
            disabled={permissionsBusy}
            onPress={() => devicePermissions?.microphone?.canAskAgain ? void enableDevicePermission("microphone") : openDeviceSettings()}
          />
        ) : null}
        {permissionsMessage ? <Text style={styles.muted}>{permissionsMessage}</Text> : null}
        {permissionsError ? <Text accessibilityRole="alert" style={styles.error}>{permissionsError}</Text> : null}
        <Button
          kind="secondary"
          label={t("permissionsCheck")}
          loading={permissionsBusy}
          disabled={permissionsBusy}
          onPress={() => void checkPermissions()}
        />
      </Section>
      <Section title={t("telemetryTitle")}>
        <TelemetrySettings />
      </Section>
      {account && !account.standalone ? (
        <Section title={t("tabSync")}>
          <Text style={styles.text}>{sync.lastAt ? t("syncChipSynced", { time: clock(sync.lastAt) }) : t("syncChipNever")}</Text>
          <Text style={styles.text}>{sync.work === undefined ? t("syncUnsentUnknown") : t("syncUnsentScoped", { count: sync.work.unsent })}</Text>
          <Button label={t("sendNow")} loading={sync.busy} disabled={sync.busy || !shell.userId} onPress={() => void shell.sendNow()} />
        </Section>
      ) : null}
      {backupDb && backupUserId ? (
        <Section title={t("settingsBackup")}>
          <Text style={styles.muted}>{t("dataBackupUnsentNote")}</Text>
          <DataActions db={backupDb} userId={backupUserId} exportAllowed={false} onChanged={() => undefined} />
        </Section>
      ) : null}
      {isPlusVariant() ? (
        <Section title="Collect Plus (experimental)">
          {account?.coding_access && shell.userId ? <CodingCaseChips userId={shell.userId} canLocal={isPlusVariant() && canUseOfflineCoding(account)} offline={sync.offline} /> : null}
          {account?.reviewing_access && shell.userId ? <Button kind="secondary" label={t("reviewCases")} onPress={() => router.push({ pathname: "/reviewing", params: { userId: shell.userId } })} /> : null}
          {account && shell.userId && canUseOfflineCoding(account) ? <Button kind="secondary" label="Offline engine check" onPress={() => router.push({ pathname: "/engine-check", params: { userId: shell.userId } })} /> : null}
          <Button kind="secondary" label="Offline profile" onPress={() => router.push("/offline-profile")} />
        </Section>
      ) : null}
      <Section title={t("settingsHelp")}>
        <Button kind="secondary" label={t("helpGuide")} onPress={() => shell.openSheet("help")} />
        <Button kind="secondary" label={t("faqOpenList")} onPress={() => shell.openSheet("help")} />
        <Button kind="secondary" label={t("exportErrors")} loading={exporting} disabled={exporting} onPress={() => void shareErrors()} />
      </Section>
      <Section title={t("settingsAbout")}>
        <Text style={styles.text}>{t("appVersionLabel", { version: APP_VERSION })}</Text>
        <Button kind="secondary" label={t("openSourceLicensesTitle")} onPress={() => router.push("/open-source-licenses")} />
        {isPlayDistribution() ? (
          // Play's Device and Network Abuse policy forbids updating outside Play; send users to this build's listing.
          <>
            <Text style={styles.muted}>{t("updatePlayStore")}</Text>
            <Button kind="secondary" label={t("updateCheck")} onPress={() => void openPlayListing()} />
          </>
        ) : shell.server ? (
          <>
            {update ? <Text style={styles.muted}>{update.status === "available" ? t("updateAvailable", { version: update.version }) : update.status === "current" ? t("updateCurrent") : t("updateUnknown")}</Text> : null}
            {update?.status === "available" ? <Button label={t("updateDownload")} onPress={() => void Linking.openURL(update.url).catch(() => undefined)} /> : null}
            <Button kind="secondary" label={t("updateCheck")} loading={checking} disabled={checking} onPress={() => void checkNow()} />
          </>
        ) : null}
        <Button kind="secondary" label={t("home")} onPress={() => router.back()} />
      </Section>
      {error ? <Text style={styles.error}>{error}</Text> : null}
      {shell.server ? <Button kind="danger" label={t("reEnrol")} loading={busy} disabled={busy} onPress={requestReEnrol} /> : null}
    </Screen>
  );
}
