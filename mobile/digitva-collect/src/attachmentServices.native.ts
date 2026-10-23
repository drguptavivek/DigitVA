/**
 * The phone's attachment controls for the questionnaire: record, photograph, pick, play, remove. Capture logic is
 * in src/attachmentCapture.ts; this file binds it to expo-audio, expo-image-picker, expo-image-manipulator and
 * expo-document-picker, and owns the permission dialogs. Rules: docs/policy/phone-attachments.md.
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
import * as DocumentPicker from "expo-document-picker";
import { ImageManipulator, SaveFormat } from "expo-image-manipulator";
import * as ImagePicker from "expo-image-picker";
import { useMemo } from "react";
import { Alert, Linking, Platform } from "react-native";
import {
  WHO_VA_ATTACHMENT_POLICY,
  type AttachmentCandidate,
  type ImageEncodingOptions,
  type WhoVaPlatformServices,
} from "@drguptavivek/who-2022-va";

import { AttachmentAudioPlayer } from "./AttachmentAudioPlayer";
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
import { fileSize, readBytes, removeFile, writePlaybackCopy } from "./mediaFiles";

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

export async function ensureCamera(): Promise<boolean> {
  let permission = await ImagePicker.getCameraPermissionsAsync();
  if (!permission.granted && permission.canAskAgain) permission = await ImagePicker.requestCameraPermissionsAsync();
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
 * The platform services for one interview. Capture needs an unlocked store and a case the server knows
 * (`canAttach`); without them no service is offered and the questionnaire keeps its "not available" notes.
 */
export function useAttachmentServices(context: AttachmentServicesContext): WhoVaPlatformServices {
  const recorder = useAudioRecorder(VOICE);
  const { db, draftId, projectId, canAttach } = context;
  return useMemo<WhoVaPlatformServices>(() => {
    if (!db || !draftId || !canAttach) return {};
    const env: CaptureEnv = {
      db, draftId, projectId, newId: randomUUID, now: Date.now, readBytes, fileSize, removeFile, writePlaybackCopy,
    };
    return {
      AudioPlayer: AttachmentAudioPlayer,
      startAudioRecording: (question) =>
        startAudioRecording({
          ...env,
          recorder,
          ensureMicrophone,
          setRecordingMode: (on) => setAudioModeAsync({ allowsRecording: on, playsInSilentMode: on }),
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
  }, [db, draftId, projectId, canAttach, recorder]);
}
