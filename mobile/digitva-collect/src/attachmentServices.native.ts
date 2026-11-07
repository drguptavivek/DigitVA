/**
 * The phone's attachment controls for the questionnaire: record, photograph, scan, pick, view, play, remove. Capture
 * logic is in src/attachmentCapture.ts; this file binds it to expo-audio, expo-image-picker, expo-image-manipulator,
 * expo-document-picker and the document scanner, and owns the permission dialogs. Rules:
 * docs/policy/phone-attachments.md.
 */
import {
  RecordingPresets,
  getRecordingPermissionsAsync,
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
  useAudioRecorder,
  type RecordingOptions,
} from "expo-audio";
import { randomUUID } from "expo-crypto";
import * as Device from "expo-device";
import * as DocumentPicker from "expo-document-picker";
import { ImageManipulator, SaveFormat } from "expo-image-manipulator";
import * as ImagePicker from "expo-image-picker";
import { useMemo } from "react";
import { Alert, AppState, Image, Linking, Platform } from "react-native";
import {
  WHO_VA_ATTACHMENT_POLICY,
  type AttachmentCandidate,
  type ImageEncodingOptions,
  type WhoVaPlatformServices,
} from "@drguptavivek/who-2022-va";

import { AttachmentAudioPlayer } from "./AttachmentAudioPlayer";
import { AttachmentImageViewer } from "./AttachmentImageViewer";
import {
  notAllowed,
  removeStored,
  resolveStored,
  startAudioRecording,
  storeImage,
  storePdf,
  type CaptureEnv,
} from "./attachmentCapture";
import type { AttachmentServicesContext } from "./attachmentServices";
import { t } from "./i18n";
import { fileSize, readBytes, removeFile, writeCaptureFile, writePlaybackCopy } from "./mediaFiles";
import { SHARPNESS_SAMPLE_WIDTH, jpegSharpness } from "./sharpness";

export type { AttachmentServicesContext };

/** Voice only (`quality=voice-only` on the question): mono AAC at 32 kbps, about 0.25 MB a minute. */
const VOICE: RecordingOptions = { ...RecordingPresets.HIGH_QUALITY, sampleRate: 22050, numberOfChannels: 1, bitRate: 32000 };

const policy = WHO_VA_ATTACHMENT_POLICY.image;
/** A camera frame above the policy's input limits is scaled down first, so a 50 MP photograph is not refused. */
const PRE_SCALE_LONG_SIDE = 4096;

/** Wait for the interviewer's answer to a plain dialog. */
function confirm(title: string, body: string, ok: string, cancel: string): Promise<boolean> {
  return new Promise((resolve) => {
    Alert.alert(title, body, [
      { text: cancel, style: "cancel", onPress: () => resolve(false) },
      { text: ok, onPress: () => resolve(true) },
    ], { cancelable: true, onDismiss: () => resolve(false) });
  });
}

const offerSettings = (title: string, body: string) =>
  Alert.alert(title, body, [
    { text: t("cancel"), style: "cancel" },
    { text: t("attachOpenSettings"), onPress: () => void Linking.openSettings() },
  ]);

/** Explain once, ask, and on a refusal point to the app's settings. Throws NotAllowedError when still refused. */
export async function ensureMicrophone(): Promise<void> {
  let permission = await getRecordingPermissionsAsync();
  if (!permission.granted && permission.canAskAgain) {
    if (!(await confirm(t("attachMicTitle"), t("attachMicBody"), t("attachContinue"), t("cancel")))) {
      throw notAllowed("microphone_declined");
    }
    permission = await requestRecordingPermissionsAsync();
  }
  if (!permission.granted) {
    offerSettings(t("attachMicDeniedTitle"), t("attachMicDeniedBody"));
    throw notAllowed("microphone_denied");
  }
}

/** Recording mode while a take is open; afterwards playback mode, which still sounds with the phone on silent. */
export const setRecordingMode = (on: boolean) => setAudioModeAsync({ allowsRecording: on, playsInSilentMode: true });

/** Leaving the foreground (background, a call or the system sheet that comes with one) pauses the take. */
export function watchInterruptions(onInterrupt: () => void): () => void {
  const subscription = AppState.addEventListener("change", (state) => {
    if (state !== "active") onInterrupt();
  });
  return () => subscription.remove();
}

/**
 * False on the iOS simulator: UIImagePickerController raises an uncatchable NSInvalidArgumentException for a
 * camera source there, so this must run before launchCameraAsync. (expo-camera's isAvailableAsync is web-only.)
 * An Android emulator has a virtual camera, so only iOS is gated.
 */
export async function ensureCamera(): Promise<boolean> {
  if (Platform.OS === "ios" && !Device.isDevice) {
    Alert.alert(t("attachCameraUnavailableTitle"), t("attachCameraUnavailableBody"));
    return false;
  }
  let permission = await ImagePicker.getCameraPermissionsAsync();
  if (!permission.granted && permission.canAskAgain) {
    if (!(await confirm(t("attachCameraTitle"), t("attachCameraBody"), t("attachContinue"), t("cancel")))) return false;
    permission = await ImagePicker.requestCameraPermissionsAsync();
  }
  if (!permission.granted) offerSettings(t("attachCameraDeniedTitle"), t("attachCameraDeniedBody"));
  return permission.granted;
}

/**
 * Android 12 and older cannot show the gallery without the storage permission (images only, capped at API 32 in
 * plugins/with-android-legacy-gallery.js); Android 13+ and iOS use the system photo picker and ask nothing.
 */
export async function ensureGallery(): Promise<boolean> {
  if (Platform.OS !== "android" || Number(Platform.Version) > 32) return true;
  let permission = await ImagePicker.getMediaLibraryPermissionsAsync();
  if (!permission.granted && permission.canAskAgain) {
    if (!(await confirm(t("attachGalleryTitle"), t("attachGalleryBody"), t("attachContinue"), t("cancel")))) return false;
    permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
  }
  if (!permission.granted) offerSettings(t("attachGalleryDeniedTitle"), t("attachGalleryDeniedBody"));
  return permission.granted;
}

function selectionOf(asset: ImagePicker.ImagePickerAsset | DocumentPicker.DocumentPickerAsset): AttachmentCandidate {
  const image = asset as ImagePicker.ImagePickerAsset;
  return {
    uri: asset.uri,
    name: ("fileName" in asset ? asset.fileName : undefined) ?? ("name" in asset ? asset.name : undefined) ?? "image.jpg",
    mimeType: asset.mimeType ?? "image/jpeg",
    ...("width" in asset ? { width: image.width, height: image.height } : {}),
  };
}

/** Re-encode a JPEG at most `PRE_SCALE_LONG_SIDE` on its long side; the vendor pipeline then applies the policy. */
async function encodeJpeg(uri: string, options: ImageEncodingOptions): Promise<string> {
  const context = ImageManipulator.manipulate(uri);
  try {
    context.resize({ width: options.width, height: options.height });
    const image = await context.renderAsync();
    try {
      return (await image.saveAsync({ compress: options.quality, format: SaveFormat.JPEG })).uri;
    } finally {
      image.release();
    }
  } finally {
    context.release();
  }
}

async function preScale(candidate: AttachmentCandidate): Promise<AttachmentCandidate> {
  const { width, height } = candidate as { width?: number; height?: number };
  if (!width || !height) return candidate;
  const oversized = Math.max(width, height) > policy.maxInputWidthOrHeight || width * height > policy.maxPixels;
  if (!oversized) return candidate;
  const scale = PRE_SCALE_LONG_SIDE / Math.max(width, height);
  const target = { width: Math.max(1, Math.round(width * Math.min(1, scale))), height: Math.max(1, Math.round(height * Math.min(1, scale))) };
  let uri: string;
  try {
    uri = await encodeJpeg(candidate.uri, { ...target, quality: 0.9, background: "#ffffff" });
  } finally {
    removeFile(candidate.uri); // success or failure, nothing else will ever hold the picker's file
  }
  return { ...candidate, uri, mimeType: "image/jpeg", ...target };
}

/**
 * Scan one page with the phone's document scanner: VisionKit on iOS, ML Kit on Android (needs Google Play services
 * and fetches its module on first use). It finds the edges, crops and straightens the page on the phone. Throws when
 * there is no scanner (no Play services, a build without the module), so the control falls back to the camera; a
 * cancel is undefined. The page comes back as base64 and is written to the app cache by us: the plugin's file mode
 * writes to the iOS Documents folder, which the media sweep cannot reach. Then it is pre-scaled like a camera frame.
 */
export async function scanDocument(): Promise<AttachmentCandidate | undefined> {
  // VisionKit asks for the camera itself; ask first with our explanation, as the camera button does.
  if (Platform.OS === "ios" && !(await ensureCamera())) return undefined;
  // Loaded here, not at the top: a build without the native module throws on load, and that must mean "use the camera".
  const scanner = require("react-native-document-scanner-plugin") as typeof import("react-native-document-scanner-plugin");
  const result = await scanner.default.scanDocument({
    maxNumDocuments: 1,
    croppedImageQuality: 90,
    responseType: scanner.ResponseType.Base64,
  });
  const page = result.status === scanner.ScanDocumentResponseStatus.Cancel ? undefined : result.scannedImages?.[0];
  if (!page) return undefined;
  const uri = writeCaptureFile(randomUUID(), page);
  try {
    const { width, height } = await Image.getSize(uri);
    return await preScale({ uri, name: "scan.jpg", mimeType: "image/jpeg", width, height });
  } catch (error) {
    removeFile(uri);
    throw error;
  }
}

/**
 * Sharpness of a just-captured image (src/sharpness.ts) from a ~512 px copy, which is deleted at once. On the phone
 * only; nothing is sent anywhere.
 */
export async function checkSharpness(uri: string): Promise<{ score: number; blurry: boolean }> {
  const context = ImageManipulator.manipulate(uri);
  let sample: string | undefined;
  try {
    context.resize({ width: SHARPNESS_SAMPLE_WIDTH });
    const image = await context.renderAsync();
    try {
      sample = (await image.saveAsync({ compress: 0.9, format: SaveFormat.JPEG })).uri;
    } finally {
      image.release();
    }
    return jpegSharpness(await readBytes(sample));
  } finally {
    context.release();
    removeFile(sample);
  }
}

/**
 * The platform services for one interview. Capture needs an unlocked store; without it no service is offered and
 * the questionnaire keeps its "not available" notes. Direct starts (no case) attach too: the upload names the server
 * draft by the interview's id (src/attachmentUpload.ts).
 */
export function useAttachmentServices(context: AttachmentServicesContext): WhoVaPlatformServices {
  const recorder = useAudioRecorder(VOICE);
  const { db, draftId, projectId } = context;
  return useMemo<WhoVaPlatformServices>(() => {
    if (!db || !draftId) return {};
    const env: CaptureEnv = {
      db, draftId, projectId, newId: randomUUID, now: Date.now, readBytes, fileSize, removeFile, writePlaybackCopy,
    };
    return {
      AudioPlayer: AttachmentAudioPlayer,
      ImageViewer: AttachmentImageViewer,
      scanDocument,
      checkSharpness,
      startAudioRecording: (question) =>
        startAudioRecording({
          ...env,
          recorder,
          ensureMicrophone,
          setRecordingMode,
          watchInterruptions,
        }, question),
      async captureImage() {
        if (!(await ensureCamera())) return undefined;
        const result = await ImagePicker.launchCameraAsync({ mediaTypes: ["images"], quality: 1, exif: false });
        const asset = result.canceled ? undefined : result.assets[0];
        return asset ? preScale(selectionOf(asset)) : undefined;
      },
      async selectImage() {
        if (!(await ensureGallery())) return undefined;
        const result = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 1, exif: false });
        const asset = result.canceled ? undefined : result.assets[0];
        return asset ? preScale(selectionOf(asset)) : undefined;
      },
      processImage: (selection, imagePolicy, question) => storeImage(env, question, selection, imagePolicy, encodeJpeg),
      async selectFile(question, _data, acceptedMimeTypes) {
        const result = await DocumentPicker.getDocumentAsync({ type: acceptedMimeTypes, multiple: false, copyToCacheDirectory: true });
        const asset = result.canceled ? undefined : result.assets[0];
        if (!asset) return undefined;
        const isPdf = asset.mimeType === "application/pdf" || asset.name.toLowerCase().endsWith(".pdf");
        if (isPdf) return storePdf(env, question, { uri: asset.uri, name: asset.name });
        return preScale({ ...selectionOf(asset), size: asset.size });
      },
      resolveAttachmentUri: (reference) => resolveStored(env, reference),
      releaseAttachmentUri: (uri) => removeFile(uri),
      removeAttachment: (reference) => removeStored(env, reference),
    };
  }, [db, draftId, projectId, recorder]);
}
