/**
 * The device list, the permissions check and the backup database behind Settings (settings.tsx), moved out of
 * its component unchanged. Each hook keeps the state, effects and handlers of its section; the component keeps
 * the rows. Effect order in the component is the order these hooks are called.
 */
import { Linking } from "react-native";
import { useEffect, useState } from "react";

import type { AccessSummary, AccountDevice } from "../api";
import { decommissionMyDevice, listMyDevices, refreshAccessSummary } from "../auth";
import type { useAppState } from "../AppState";
import type { Db } from "../drafts";
import { readDevicePermissions, requestDevicePermission, type DevicePermissionName, type DevicePermissionState } from "../devicePermissions.native";
import { openInterviewerDb } from "../interviewerDb";
import { t } from "../i18n";
import { isPlusVariant } from "../appVariant";
import { dataActionsAllowed } from "../standalone/export";
import { errorText } from "../ui";

type Account = ReturnType<typeof useAppState>["accounts"][number];

/** This account's enrolled phones: listed on mount and when the server or account changes, refreshed or removed on request. */
export function useDevices({ server, account, lockNow, reload }: { server: string | undefined; account: Account | undefined; lockNow(): Promise<boolean>; reload(): Promise<void> }) {
  const [devices, setDevices] = useState<AccountDevice[]>();
  const [devicesBusy, setDevicesBusy] = useState(false);
  const [deviceBusyId, setDeviceBusyId] = useState<string>();
  const [devicesError, setDevicesError] = useState("");
  useEffect(() => {
    let active = true;
    const userId = account?.user_id;
    if (!server || !userId || account?.needs_sign_in) {
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
  }, [server, account?.user_id, account?.needs_sign_in]);
  async function retryDevices() {
    const userId = account?.user_id;
    if (!server || !userId || account?.needs_sign_in) return;
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
    if (!server || !account) return;
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
  return { devices, devicesBusy, deviceBusyId, devicesError, retryDevices, removeDevice };
}

/**
 * The phone's camera and microphone permissions (read on mount, requested only on an explicit press) and the
 * cached project access (read only by the explicit check; cleared when the server changes).
 */
export function usePermissions({ server, userId, offline, standalone, reload }: { server: string | undefined; userId: string | undefined; offline: boolean; standalone: boolean | undefined; reload(): Promise<void> }) {
  const [devicePermissions, setDevicePermissions] = useState<Record<DevicePermissionName, DevicePermissionState>>();
  const [accessSummary, setAccessSummary] = useState<AccessSummary>();
  const [permissionsBusy, setPermissionsBusy] = useState(false);
  const [permissionsError, setPermissionsError] = useState("");
  const [permissionsMessage, setPermissionsMessage] = useState("");
  useEffect(() => {
    setAccessSummary(undefined);
  }, [server]);
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
  async function checkPermissions() {
    setPermissionsBusy(true);
    setPermissionsError("");
    try {
      setDevicePermissions(await readDevicePermissions());
      if (offline || standalone) {
        setAccessSummary(undefined);
        setPermissionsMessage(t("permissionsOffline"));
      } else if (!server || !userId) {
        setAccessSummary(undefined);
        setPermissionsMessage(t("permissionsStatusUnknown"));
      } else {
        const refreshed = await refreshAccessSummary(userId);
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
  return { devicePermissions, accessSummary, permissionsBusy, permissionsError, permissionsMessage, checkPermissions, enableDevicePermission, openDeviceSettings };
}

/**
 * Encrypted backup of unsent work for an enrolled account (Plus), and export, backup and restore of a standalone
 * account's records; each needs the unlocked interviewer database.
 */
export function useBackup(account: Account | undefined, unlocked: boolean) {
  const [backupDb, setBackupDb] = useState<Db>();
  const standaloneData = unlocked && dataActionsAllowed(account);
  const backupUserId = account && unlocked && (standaloneData || (isPlusVariant() && !account.standalone)) ? account.user_id : undefined;
  useEffect(() => {
    setBackupDb(undefined);
    if (backupUserId) void openInterviewerDb(backupUserId).then(setBackupDb).catch(() => undefined);
  }, [backupUserId]);
  return { backupDb, backupUserId, standaloneData };
}
