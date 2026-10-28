import {
  getRecordingPermissionsAsync,
  requestRecordingPermissionsAsync,
} from "expo-audio";
import * as ImagePicker from "expo-image-picker";

export type DevicePermissionName = "camera" | "microphone";

export interface DevicePermissionState {
  granted: boolean;
  canAskAgain: boolean;
}

function stateOf(permission: { granted: boolean; canAskAgain: boolean }): DevicePermissionState {
  return { granted: permission.granted, canAskAgain: permission.canAskAgain };
}

export async function readDevicePermissions(): Promise<Record<DevicePermissionName, DevicePermissionState>> {
  const [camera, microphone] = await Promise.all([
    ImagePicker.getCameraPermissionsAsync(),
    getRecordingPermissionsAsync(),
  ]);
  return { camera: stateOf(camera), microphone: stateOf(microphone) };
}

export async function requestDevicePermission(name: DevicePermissionName): Promise<DevicePermissionState> {
  const permission = name === "camera"
    ? await ImagePicker.requestCameraPermissionsAsync()
    : await requestRecordingPermissionsAsync();
  return stateOf(permission);
}
