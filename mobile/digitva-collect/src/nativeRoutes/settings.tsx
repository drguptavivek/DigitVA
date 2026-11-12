/**
 * Phone Settings, in sections: Account, Devices, Phone (mode and app language), Display, Security, Coding, Permissions, Diagnostics,
 * Backup, Collect Plus, Help & support, About. Sync lives on the Sync tab and sheet only, and the Local / Online / My
 * coded cases rows on Home and Interviews. The
 * enrolled server is shown read-only and changed only by re-enrolling (src/reEnrolConfirm.ts). Active or demo
 * switches between the phone's two enrolments (docs/policy/public-demo.md section 10.1). The questionnaire's own
 * language is chosen in the form's menu. Account also has Delete my account and the privacy and data-requests
 * links (docs/policy/public-privacy-and-data-requests.md section 8): on the Demo slot it deletes the account at
 * once after the password; otherwise it sends a deletion request the programme team confirms.
 * Server controls belong only to the selected server account; standalone ignores retained enrolment. A standalone
 * account's Account section also has Enrol this phone, and an unlocked one gets Export and backup (export, back up,
 * restore: src/standalone/DataActions.tsx), which moved off the standalone home (digitva-axim).
 */
import { useRouter } from "expo-router";

import { goHome } from "../goHome";
import { useEffect, useRef, useState, type ReactNode } from "react";
import Constants from "expo-constants";
import { canUseBiometricAuthentication } from "expo-secure-store";
import { Alert, Linking, Platform, Text, View } from "react-native";
import { platformLabel } from "../platformLabel";

import { ApiError, type AccessSummary, type AccountDevice } from "../api";
import { decommissionMyDevice, deleteDemoAccount, listMyDevices, refreshAccessSummary, requestAccountDeletion, type Slot } from "../auth";
import { useAppState } from "../AppState";
import type { Db } from "../drafts";
import { isUnlocked, openInterviewerDb } from "../interviewerDb";
import { DataActions } from "../standalone/DataActions";
import { dataActionsAllowed } from "../standalone/export";
import StandaloneConsentNoticeSettings from "../standalone/StandaloneConsentNoticeSettings";
import { APP_VERSION } from "../appVersion";
import { isPlayDistribution, isPlusVariant } from "../appVariant";
import { iosAppStoreId } from "../platformFamily";
import { canUseOfflineCoding } from "../codingCapabilities";
import { readDevicePermissions, requestDevicePermission, type DevicePermissionName, type DevicePermissionState } from "../devicePermissions.native";
import { IDLE_LOCK_MS } from "../autoLock";
import { exportErrors } from "../errorExport";
import { t } from "../i18n";
import { useShell } from "../nativeShell/shellContext";
import { confirmReEnrol, reEnrolDevice } from "../reEnrolConfirm";
import { useToast } from "../toast";
import { checkForUpdate, checkServerCompatibility, type CompatibilityResult, type UpdateResult } from "../updateCheck";
import { Button, Card, errorText, FieldHint, ListRow, Notice, PasswordInput, Screen, SegmentedControl, Separator, TextLink, ThemedSwitch, useUiStyles } from "../ui";
import { UiLanguageRow } from "../ui/LanguagePicker";
import { roleLabelKey } from "../web/roleHome";
import { displayProjectName } from "../projectName";
import { TelemetrySettings } from "../TelemetrySettings";
import { setIcd11DorisEnabled, useIcd11DorisPreference } from "../icd11DorisPreference";
import { biometricText, useBiometricKind } from "../UnlockOffer";
import { spacing, useTheme } from "../theme";
import { biometricEnabled, screenLockAvailable, screenLockEnabled, turnOffBiometric, turnOffScreenLock } from "../vault";

/** A switch at the end of a Settings row; the row's label names it. */
function RowSwitch({ label, hint, value, disabled, onChange, testID }: { label: string; hint?: string; value: boolean; disabled?: boolean; onChange(next: boolean): void; testID?: string }) {
  return <ThemedSwitch testID={testID} accessibilityRole="switch" accessibilityLabel={label} accessibilityHint={hint} value={value} disabled={disabled} onValueChange={onChange} />;
}

/**
 * Settings > Display: Text size (Small 0.9 / Medium 1.0 / Large 1.2, times the phone's font size, capped at 2.0)
 * and High contrast. Both are device-local UI preferences (src/preferences.ts), never sent to the server; High
 * contrast starts on when the phone asks for more contrast, and the user's choice wins from then on.
 */
function DisplaySection() {
  const { textSize, setTextSize, highContrast, setHighContrast } = useTheme();
  return (
    <Card grouped label={t("settingsDisplay")} footer={t("textSizeNote")}>
      <LabelledRow label={t("textSize")}>
        <SegmentedControl
          compact
          testID="text-size"
          accessibilityLabel={t("textSize")}
          options={[{ value: "small", label: t("textSizeSmall") }, { value: "medium", label: t("textSizeMedium") }, { value: "large", label: t("textSizeLarge") }]}
          value={textSize}
          onChange={(next) => void setTextSize(next)}
        />
      </LabelledRow>
      <Separator />
      <ListRow label={t("highContrast")} trailing={<RowSwitch testID="high-contrast" label={t("highContrast")} hint={t("highContrastNote")} value={highContrast} onChange={(on) => void setHighContrast(on)} />} />
    </Card>
  );
}

/** A row holding a control wider than a switch (a 36pt segmented control): 48pt, the card's padding. */
const rowStyle = { minHeight: 48, flexDirection: "row" as const, alignItems: "center" as const, justifyContent: "space-between" as const, gap: spacing.sm, paddingHorizontal: spacing.md, paddingVertical: spacing.xs };

/** "Text size · Small | Medium | Large": the row's label, then its compact control at most 240pt wide. */
function LabelledRow({ label, children }: { label: string; children: ReactNode }) {
  const styles = useUiStyles();
  return (
    <View style={rowStyle}>
      <Text style={[styles.text, { flexShrink: 1 }]}>{label}</Text>
      <View style={{ flex: 1, maxWidth: 240 }}>{children}</View>
    </View>
  );
}

/** "digitva.causeofdeathindia.com": a server address without its scheme. */
const serverHost = (server: string) => server.replace(/^https?:\/\//, "").replace(/\/$/, "");

export default function NativeSettings() {
  const bioKind = useBiometricKind();
  const appStoreId = iosAppStoreId();
  const router = useRouter();
  const toast = useToast();
  const shell = useShell();
  const { device, accounts, slot, switchSlot, lockNow, reload } = useAppState();
  const styles = useUiStyles();
  const [biometricUsers, setBiometricUsers] = useState<Set<string>>(new Set());
  const [screenLockUsers, setScreenLockUsers] = useState<Set<string>>(new Set());
  const [screenLockPossible, setScreenLockPossible] = useState(false);
  const [optionsVersion, setOptionsVersion] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [checking, setChecking] = useState(false);
  const [checkingCompatibility, setCheckingCompatibility] = useState(false);
  const [update, setUpdate] = useState<UpdateResult>();
  const [compatibility, setCompatibility] = useState<CompatibilityResult>();
  const serverGeneration = useRef(0);
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
  // Project access is read only after the PIN unlocks an account; before that Settings shows the phone's own permissions.
  const unlocked = Boolean(account && isUnlocked(account.user_id));
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
    serverGeneration.current += 1;
    setUpdate(undefined);
    setCompatibility(undefined);
    setChecking(false);
    setCheckingCompatibility(false);
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
  // Encrypted backup of unsent work for an enrolled account (Plus), and export, backup and restore of a standalone
  // account's records; each needs the unlocked interviewer database.
  const [backupDb, setBackupDb] = useState<Db>();
  const standaloneData = unlocked && dataActionsAllowed(account);
  const backupUserId = account && unlocked && (standaloneData || (isPlusVariant() && !account.standalone)) ? account.user_id : undefined;
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
      // The PIN screen goes on a fresh stack: Back must not reach the pre-lock screens.
      goHome(router);
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
      goHome(router);
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
      goHome(router, slot === "demo" ? "/demo" : "/enrol");
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
    const server = shell.server;
    const generation = serverGeneration.current;
    setChecking(true);
    try {
      const result = await checkForUpdate(server);
      if (generation === serverGeneration.current && shell.server === server) setUpdate(result);
    } finally {
      if (generation === serverGeneration.current) setChecking(false);
    }
  }
  async function checkCompatibilityNow() {
    if (!shell.server) return;
    const server = shell.server;
    const generation = serverGeneration.current;
    setCheckingCompatibility(true);
    try {
      const result = await checkServerCompatibility(server);
      if (generation === serverGeneration.current && shell.server === server) setCompatibility(result);
    } finally {
      if (generation === serverGeneration.current) setCheckingCompatibility(false);
    }
  }
  /** iOS: the row shows only when the App Store id is configured (DIGITVA_IOS_APP_STORE_ID, app.config.js). */
  async function openAppStoreListing(appStoreId: string) {
    setError("");
    await Linking.openURL(`itms-apps://apps.apple.com/app/id${appStoreId}`).catch(() => setError(t("errGeneric")));
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
      goHome(router);
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
  const activeProject = accessSummary?.projects.find((project) => project.project_id === device?.project_id);
  const projectCollectionAccess = activeProject ? activeProject.actions.interview.length > 0 : undefined;
  const projectCodingAccess = activeProject
    ? activeProject.grants.some((grant) => grant.active && grant.codes === true && (grant.role === "coder" || grant.role === "coding_tester"))
    : undefined;
  const bioLabel = biometricText("biometricEnable", bioKind);
  const securityRows = [
    ...(biometricAvailable ? accounts.filter((item) => biometricUsers.has(item.user_id) || !item.signed_out).map((item) => ({
      key: `biometric-${item.user_id}`,
      label: bioLabel,
      name: item.name,
      on: biometricUsers.has(item.user_id),
      // Turning it on unlocks with the PIN, which a signed-out profile gets only after signing in again.
      change: (on: boolean) => (on ? void requestBiometric(item.user_id) : void turnOff(turnOffBiometric, item.user_id)),
    })) : []),
    ...accounts.filter((item) => screenLockUsers.has(item.user_id) || (screenLockPossible && !item.signed_out)).map((item) => ({
      key: `screen-lock-${item.user_id}`,
      label: t("screenLockEnable"),
      name: item.name,
      on: screenLockUsers.has(item.user_id),
      change: (on: boolean) => (on ? void requestScreenLock(item.user_id) : void turnOff(turnOffScreenLock, item.user_id)),
    })),
  ];
  const autoLockMinutes = t("settingsAutoLockMinutes", { minutes: Math.round(IDLE_LOCK_MS / 60_000) });
  const deleteNote = account && canDelete ? t(slot === "demo" ? "deleteAccountDemoNote" : "deleteAccountStaffNote") : undefined;
  const permissionProject = activeProject?.project_name ?? (shell.server && device ? device.project_name : undefined);
  const accessRows = unlocked && !account?.standalone;
  // Camera and Microphone are value rows; while not allowed the row asks again, or opens the phone's settings once
  // the phone will not ask, and shows a chevron. The card keeps every row's chevron slot so the values share one edge.
  const devicePermissionRow = (name: DevicePermissionName) => {
    const state = devicePermissions?.[name];
    const label = t(name === "camera" ? "permissionsCameraLabel" : "permissionsMicrophoneLabel");
    const value = devicePermissionStatus(state);
    if (!state || state.granted) return <ListRow testID={`permission-${name}`} label={label} value={value} />;
    const action = state.canAskAgain ? t(name === "camera" ? "permissionsEnableCamera" : "permissionsEnableMicrophone") : t("permissionsOpenSettings");
    return (
      <ListRow
        testID={`permission-${name}`}
        label={label}
        value={value}
        accessibilityLabel={`${label}, ${value}. ${action}`}
        disabled={permissionsBusy}
        onPress={state.canAskAgain ? () => void enableDevicePermission(name) : openDeviceSettings}
      />
    );
  };
  // The account's phone roles, as the Account sheet's chips name them ("Interviewer · Death reporter").
  const roleText = account ? [account.collection_access ? "interviewer" : "", account.registration_access ? "death_reporter" : ""].filter(Boolean).map((role) => t(roleLabelKey(role))).join(" · ") : "";
  const plusRows = [
    account?.reviewing_access && shell.userId ? <ListRow key="review" label={t("reviewCases")} onPress={() => router.push({ pathname: "/reviewing", params: { userId: shell.userId } })} /> : null,
    account && shell.userId && canUseOfflineCoding(account) ? <ListRow key="engine" label={t("offlineEngineCheck")} onPress={() => router.push({ pathname: "/engine-check", params: { userId: shell.userId } })} /> : null,
    <ListRow key="profile" label={t("offlineProfileTitle")} onPress={() => router.push(shell.userId ? { pathname: "/offline-profile", params: { userId: shell.userId } } : "/offline-profile")} />,
  ].filter((row) => row !== null);
  const withSeparators = (rows: React.ReactElement[]) => rows.flatMap((row, index) => (index < rows.length - 1 ? [row, <Separator key={`sep-${row.key}`} />] : [row]));
  // The one status line of the compatibility check, once it has run: the error colour when it failed.
  const compatibilityLine = !compatibility ? undefined
    : compatibility.status === "compatible" ? (compatibility.buildRevision ? t("serverCompatibleWith", { version: compatibility.buildRevision.slice(0, 8) }) : t("serverCompatibleAny"))
    : compatibility.status === "mismatch" ? t("serverCompatibilityMismatch") : t("serverUnreachable");
  return (
    <Screen title={t("settings")}>
      {/* Mockup grammar: a section label above each grouped card of rows, the explanation as the card's footer. */}
      <View style={{ gap: spacing.md }}>
      <Card grouped label={t("settingsAccount")} footer={deleteNote}>
        {account ? <ListRow label={account.name} value={roleText || undefined} /> : accounts.map((item, index) => (
          <View key={item.user_id}>{index ? <Separator /> : null}<ListRow label={item.name} /></View>
        ))}
        {account?.standalone ? <><Separator /><ListRow label={t("standaloneEnrol")} onPress={() => router.push("/enrol")} /></> : null}
        {unlocked && shell.userId ? <><Separator /><ListRow label={t("profileAccessTitle")} onPress={() => router.push({ pathname: "/profile-access", params: { userId: shell.userId } })} /></> : null}
        {shell.server && device ? (
          <>
            <Separator />
            <ListRow label={t("enrolledServer")} value={serverHost(shell.server)} mono />
            <Separator />
            {/* Middle-ellipsised; a tap shows the whole ID (for support), which can be selected there. */}
            <ListRow
              label={t("deviceIdLabel")}
              value={device.device_id}
              mono
              chevron={false}
              accessibilityLabel={`${t("deviceIdLabel")}, ${device.device_id}`}
              onPress={() => Alert.alert(t("deviceIdLabel"), device.device_id)}
              onLongPress={() => Alert.alert(t("deviceIdLabel"), device.device_id)}
            />
            <Separator />
            <ListRow label={t("privacyPolicy")} onPress={() => void Linking.openURL(`${shell.server}/privacy`).catch(() => undefined)} />
            <Separator />
            <ListRow label={t("dataRequests")} onPress={() => void Linking.openURL(`${shell.server}/data-requests`).catch(() => undefined)} />
          </>
        ) : null}
        {account ? <><Separator /><ListRow testID="auto-lock" label={t("settingsAutoLock")} value={autoLockMinutes} /></> : null}
        {account && canDelete ? (
          <>
            <Separator />
            <ListRow label={t("deleteAccount")} tone="destructive" chevron={false} disabled={busy} onPress={() => pressDeleteAccount(account.user_id)} />
            {deletePassword !== undefined ? (
              <View style={{ gap: spacing.xs, paddingHorizontal: spacing.md, paddingBottom: spacing.md }}>
                <Text style={styles.muted}>{t("deleteAccountPasswordPrompt")}</Text>
                <PasswordInput
                  onCard
                  accessibilityLabel={t("password")}
                  value={deletePassword}
                  onChangeText={setDeletePassword}
                  autoComplete="current-password"
                />
              </View>
            ) : null}
          </>
        ) : null}
      </Card>
      {deleteMessage ? <Notice tone="success">{deleteMessage}</Notice> : null}
      {account?.standalone ? (
        <Card label={t("standaloneConsentNoticeTitle")}>
          <StandaloneConsentNoticeSettings />
        </Card>
      ) : null}
      {shell.server && account && !account.needs_sign_in ? (
        <Card
          grouped
          label={t("settingsSectionDevices")}
          footer={devices ? t("devicesCount", { count: devices.length }) : undefined}
        >
          {devicesBusy && !devices ? <ListRow label={t("devicesLoading")} /> : null}
          {devices?.length === 0 ? <ListRow label={t("devicesNone")} /> : null}
          {devices?.map((item, index) => (
            <View key={item.device_id}>
              {index ? <Separator /> : null}
              {/* This phone is titled "This phone", its model on the second line, so the title never wraps beside the link.
                  Signing this phone out keeps its data, so that link is primary; removing another phone is red. */}
              <ListRow
                testID={`device-${item.device_id}`}
                label={item.current ? t("deviceCurrent") : item.name || platformLabel(item.platform)}
                secondary={[item.current ? item.name : "", platformLabel(item.platform), item.app_version].filter(Boolean).join(" · ")}
                trailing={(
                  <TextLink
                    tone={item.current ? undefined : "destructive"}
                    label={deviceBusyId === item.device_id ? t("devicesLoading") : t(item.current ? "deviceRemoveCurrent" : "deviceRemoveShort")}
                    accessibilityLabel={item.current ? `${t("deviceRemoveCurrent")}: ${t("deviceCurrent")}` : `${t("deviceDecommission")}: ${item.name || platformLabel(item.platform)}`}
                    disabled={devicesBusy || deviceBusyId !== undefined}
                    onPress={() => confirmDeviceRemoval(item)}
                  />
                )}
              />
            </View>
          ))}
          {/* The card's refresh is its last row, an action row like Export errors. */}
          {devices !== undefined || devicesBusy ? <Separator /> : null}
          <ListRow
            label={t(devices ? "devicesRefresh" : "devicesRetry")}
            action
            disabled={devicesBusy || deviceBusyId !== undefined}
            onPress={() => void retryDevices()}
          />
        </Card>
      ) : null}
      {devicesError ? <Notice tone="error">{devicesError}</Notice> : null}
      {/* One PHONE card: the mode (not on a standalone account) and the app language, one footer for both. */}
      <Card grouped label={t("settingsPhone")} footer={t(account?.standalone ? "questionnaireLanguageNote" : "settingsPhoneNote")}>
        {!account?.standalone ? (
          <>
            <LabelledRow label={t("settingsSlot")}>
              <SegmentedControl
                compact
                accessibilityLabel={t("settingsSlot")}
                options={[{ value: "active", label: t("slotActive") }, { value: "demo", label: t("slotDemo") }]}
                value={slot}
                disabled={busy}
                onChange={(option) => {
                  if (option !== slot) void chooseSlot(option);
                }}
              />
            </LabelledRow>
            <Separator />
          </>
        ) : null}
        <UiLanguageRow testID="app-language" label={t("appLanguage")} />
      </Card>
      <DisplaySection />
      {securityRows.length ? (
        <Card grouped label={t("settingsSecurity")}>
          {securityRows.map((row, index) => (
            <View key={row.key}>
              {index ? <Separator /> : null}
              <ListRow
                label={row.label}
                secondary={accounts.length > 1 ? row.name : undefined}
                trailing={<RowSwitch label={accounts.length > 1 ? `${row.label}: ${row.name}` : row.label} value={row.on} disabled={busy} onChange={row.change} />}
              />
            </View>
          ))}
        </Card>
      ) : null}
      {error ? <Notice tone="error">{error}</Notice> : null}
      <Card
        grouped
        label={t("settingsSectionCoding")}
        footer={t(account?.standalone ? "icd11DorisPreferenceScopeStandalone" : isPlusVariant() ? "icd11DorisPreferenceScope" : "icd11DorisPreferenceScopeOnline")}
      >
        <ListRow
          label={t("codingOnPhone")}
          trailing={<RowSwitch label={t("codingOnPhone")} value={icd11DorisPreference.enabled} disabled={!icd11DorisPreference.ready} onChange={(value) => void changeIcd11DorisPreference(value)} />}
        />
      </Card>
      {icd11DorisError ? <Notice tone="error">{icd11DorisError}</Notice> : null}
      <Card
        grouped
        chevronSlot
        label={t("settingsSectionPermissions")}
        footer={accessRows && permissionProject ? t("permissionsFooter", { project: displayProjectName(permissionProject) }) : undefined}
      >
        {accessRows ? (
          <>
            <ListRow label={t("permissionsCollectionLabel")} value={accessStatus(activeProject ? projectCollectionAccess : account?.collection_access)} />
            <Separator />
            <ListRow label={t("permissionsCodingLabel")} value={accessStatus(activeProject ? projectCodingAccess : account?.coding_access)} />
            <Separator />
          </>
        ) : null}
        {devicePermissionRow("camera")}
        <Separator />
        {devicePermissionRow("microphone")}
        {accessRows ? (
          <>
            <Separator />
            <ListRow label={t("permissionsRefreshNow")} accessibilityLabel={t("permissionsCheck")} action disabled={permissionsBusy} onPress={() => void checkPermissions()} />
          </>
        ) : null}
      </Card>
      {permissionsMessage ? <FieldHint>{permissionsMessage}</FieldHint> : null}
      {permissionsError ? <Notice tone="error">{permissionsError}</Notice> : null}
      {/* The switch row last, so the footer under the card describes it. Export has a busy state: the row waits. */}
      <Card grouped label={t("settingsSectionDiagnostics")} footer={t("telemetryDescription")}>
        <ListRow label={t("exportErrors")} action disabled={exporting} onPress={() => void shareErrors()} />
        <Separator />
        <TelemetrySettings />
      </Card>
      {backupDb && backupUserId ? (
        standaloneData ? (
          <Card grouped label={t("standaloneDataSection")}>
            <DataActions db={backupDb} userId={backupUserId} onChanged={() => undefined} />
          </Card>
        ) : (
          <Card grouped label={t("settingsBackup")} footer={t("dataBackupUnsentNote")}>
            <DataActions db={backupDb} userId={backupUserId} exportAllowed={false} onChanged={() => undefined} />
          </Card>
        )
      ) : null}
      {isPlusVariant() ? <Card grouped label={t("collectPlusSection")}>{withSeparators(plusRows)}</Card> : null}
      <Card grouped label={t("settingsHelp")}>
        <ListRow label={t("helpGuide")} onPress={() => shell.openSheet("help")} />
        <Separator />
        <ListRow label={t("faqOpenList")} onPress={() => shell.openSheet("help")} />
      </Card>
      <Card grouped label={t("settingsAbout")}>
        <ListRow label={t("appVersionRowLabel")} value={isPlusVariant() ? t("appVersionValueVariant", { version: APP_VERSION, variant: "Plus" }) : APP_VERSION} />
        {shell.server ? (
          <>
            <Separator />
            <ListRow
              label={t("serverCompatibilityCheck")}
              secondary={compatibilityLine}
              secondaryTone={compatibility && compatibility.status !== "compatible" ? "destructive" : undefined}
              action
              disabled={checkingCompatibility}
              onPress={() => void checkCompatibilityNow()}
            />
          </>
        ) : null}
        <Separator />
        <ListRow label={t("openSourceLicensesTitle")} onPress={() => router.push("/open-source-licenses")} />
        {Platform.OS === "ios" ? (
          // iOS is updated only by the App Store (docs/policy/ios-client.md); no row until its listing id is known.
          appStoreId ? (
            <>
              <Separator />
              <ListRow label={t("updateCheck")} secondary={t("updateAppStore")} action onPress={() => void openAppStoreListing(appStoreId)} />
            </>
          ) : null
        ) : isPlayDistribution() ? (
          // Play's Device and Network Abuse policy forbids updating outside Play; send users to this build's listing.
          <>
            <Separator />
            <ListRow label={t("updateCheck")} secondary={t("updatePlayStore")} action onPress={() => void openPlayListing()} />
          </>
        ) : shell.server ? (
          <>
            <Separator />
            <ListRow
              label={t("updateCheck")}
              secondary={update ? (update.status === "available" ? t("updateAvailable", { version: update.version }) : update.status === "current" ? t("updateCurrent") : t("updateUnknown")) : undefined}
              action
              disabled={checking}
              onPress={() => void checkNow()}
            />
          </>
        ) : null}
      </Card>
      {update?.status === "available" && !isPlayDistribution() && Platform.OS !== "ios" ? <Button label={t("updateDownload")} onPress={() => void Linking.openURL(update.url).catch(() => undefined)} /> : null}
      {shell.server ? (
        <Card grouped>
          <ListRow label={t("reEnrol")} tone="destructive" chevron={false} disabled={busy} onPress={requestReEnrol} />
        </Card>
      ) : null}
      </View>
    </Screen>
  );
}
