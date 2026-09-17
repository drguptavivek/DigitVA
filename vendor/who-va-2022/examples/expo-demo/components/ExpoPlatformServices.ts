import { DateTimePickerAndroid } from "@react-native-community/datetimepicker";
import {
  RecordingPresets,
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
  useAudioRecorder
} from "expo-audio";
import * as DocumentPicker from "expo-document-picker";
import * as FileSystem from "expo-file-system/legacy";
import * as ImagePicker from "expo-image-picker";
import { ImageManipulator, SaveFormat } from "expo-image-manipulator";
import { useMemo } from "react";
import { Platform } from "react-native";

import {
  AttachmentProcessingError,
  WHO_VA_ATTACHMENT_POLICY,
  type AttachmentCandidate,
  type AttachmentReference,
  type AttachmentSelection,
  type ImageAttachmentPolicy,
  type InstrumentQuestion,
  type ProcessedImageAttachmentReference,
  type RetainedPdfAttachmentReference,
  type SubmissionData,
  type WhoVaPlatformServices
} from "@drguptavivek/who-2022-va";
import type { ImageEncodingOptions } from "@drguptavivek/who-2022-va";
import { processNativeImageAttachment } from "@drguptavivek/who-2022-va/native";

const ATTACHMENT_DIR = `${FileSystem.documentDirectory ?? ""}who-va-attachments/`;

function dateFromIso(value: string | undefined): Date {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value ?? "");
  if (!match) return new Date();
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
}

function isoFromDate(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function pickAndroidDate(
  _question: InstrumentQuestion,
  _data: SubmissionData,
  currentValue?: string
): Promise<string | undefined> {
  if (Platform.OS !== "android") return Promise.resolve(undefined);
  return new Promise((resolve) => {
    DateTimePickerAndroid.open({
      mode: "date",
      value: dateFromIso(currentValue),
      onValueChange: (_event, selectedDate) => {
        resolve(isoFromDate(selectedDate));
      },
      onDismiss: () => {
        resolve(undefined);
      },
      onNeutralButtonPress: () => {
        resolve(undefined);
      }
    });
  });
}

function nameFromUri(uri: string, fallback: string): string {
  const lastSegment = uri.split(/[/?#]/).filter(Boolean).at(-1);
  return lastSegment ? decodeURIComponent(lastSegment) : fallback;
}

function selectedImage(asset: ImagePicker.ImagePickerAsset, fallbackName: string): AttachmentSelection {
  return {
    uri: asset.uri,
    name: asset.fileName ?? nameFromUri(asset.uri, fallbackName),
    mimeType: asset.mimeType ?? "image/jpeg",
    width: asset.width,
    height: asset.height
  };
}

function base64ToBytes(value: string): Uint8Array {
  const decoded = globalThis.atob(value);
  const bytes = new Uint8Array(decoded.length);
  for (let index = 0; index < decoded.length; index += 1) bytes[index] = decoded.charCodeAt(index);
  return bytes;
}

async function ensureAttachmentDir(): Promise<void> {
  if (!FileSystem.documentDirectory) throw new Error("Expo document storage is unavailable.");
  await FileSystem.makeDirectoryAsync(ATTACHMENT_DIR, { intermediates: true });
}

async function readBytes(uri: string): Promise<Uint8Array> {
  const value = await FileSystem.readAsStringAsync(uri, { encoding: FileSystem.EncodingType.Base64 });
  return base64ToBytes(value);
}

function attachmentUri(value: AttachmentCandidate): string {
  return value.uri;
}

function extensionForAudioUri(uri: string | null): string {
  const name = uri ? nameFromUri(uri, "") : "";
  const extension = /\.(m4a|mp4|aac|caf|wav|webm|3gp)$/i.exec(name)?.[1];
  return extension?.toLowerCase() ?? "m4a";
}

async function persistFile(temporaryUri: string, name: string): Promise<string> {
  await ensureAttachmentDir();
  const durableUri = `${ATTACHMENT_DIR}${name}`;
  await FileSystem.copyAsync({ from: temporaryUri, to: durableUri });
  return durableUri;
}

async function captureImage(): Promise<AttachmentCandidate | undefined> {
  const permission = await ImagePicker.requestCameraPermissionsAsync();
  if (!permission.granted) return undefined;
  const result = await ImagePicker.launchCameraAsync({
    mediaTypes: ["images"],
    quality: 1,
    exif: false
  });
  if (result.canceled) return undefined;
  const asset = result.assets[0];
  return asset ? selectedImage(asset, "camera-image.jpg") : undefined;
}

async function selectImage(): Promise<AttachmentCandidate | undefined> {
  const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
  if (!permission.granted) return undefined;
  const result = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ["images"],
    quality: 1,
    exif: false
  });
  if (result.canceled) return undefined;
  const asset = result.assets[0];
  return asset ? selectedImage(asset, "selected-image.jpg") : undefined;
}

async function selectFile(
  _question: InstrumentQuestion,
  _data: SubmissionData,
  acceptedMimeTypes: string[]
): Promise<AttachmentCandidate | undefined> {
  const result = await DocumentPicker.getDocumentAsync({
    type: acceptedMimeTypes.length > 0 ? acceptedMimeTypes : "*/*",
    multiple: false,
    copyToCacheDirectory: true
  });
  if (result.canceled) return undefined;
  const asset = result.assets[0];
  if (!asset) return undefined;
  const selection = {
    uri: asset.uri,
    name: asset.name,
    mimeType: asset.mimeType,
    size: asset.size
  };
  if (
    acceptedMimeTypes.includes("application/pdf") &&
    (asset.mimeType === "application/pdf" || asset.name.toLowerCase().endsWith(".pdf"))
  ) {
    return retainPdf(selection);
  }
  return selection;
}

async function processImage(
  selection: AttachmentCandidate,
  policy: ImageAttachmentPolicy
): Promise<ProcessedImageAttachmentReference> {
  const uri = attachmentUri(selection);
  const name = typeof selection.name === "string" ? selection.name : "image.jpg";
  return processNativeImageAttachment(
    { uri, name },
    {
      async getSize(sourceUri) {
        const info = await FileSystem.getInfoAsync(sourceUri);
        if (!info.exists || info.isDirectory) throw new Error("Selected file is unavailable.");
        return info.size;
      },
      read: readBytes,
      async inspect(sourceUri) {
        const width =
          "width" in selection && typeof selection.width === "number" ? selection.width : undefined;
        const height =
          "height" in selection && typeof selection.height === "number" ? selection.height : undefined;
        const mimeType = selection.mimeType === "image/png" ? "image/png" : "image/jpeg";
        if (width && height) return { mimeType, width, height };
        throw new Error("Native image dimensions were unavailable.");
      },
      async encodeJpeg(sourceUri, options: ImageEncodingOptions) {
        const context = ImageManipulator.manipulate(sourceUri);
        try {
          context.resize({ width: options.width, height: options.height });
          const image = await context.renderAsync();
          try {
            const result = await image.saveAsync({ compress: options.quality, format: SaveFormat.JPEG });
            return result.uri;
          } finally {
            image.release();
          }
        } finally {
          context.release();
        }
      },
      persist: persistFile,
      async remove(sourceUri) {
        await FileSystem.deleteAsync(sourceUri, { idempotent: true });
      }
    },
    { policy }
  );
}

async function retainPdf(selection: AttachmentCandidate): Promise<RetainedPdfAttachmentReference> {
  const uri = attachmentUri(selection);
  const mimeType = typeof selection.mimeType === "string" ? selection.mimeType : undefined;
  const originalName = typeof selection.name === "string" ? selection.name : nameFromUri(uri, "document.pdf");
  if (mimeType !== "application/pdf" && !originalName.toLowerCase().endsWith(".pdf")) {
    throw new AttachmentProcessingError("pdf-type-not-allowed");
  }
  const info = await FileSystem.getInfoAsync(uri);
  const selectedSize = typeof selection.size === "number" ? selection.size : undefined;
  const size = info.exists && !info.isDirectory ? info.size : selectedSize;
  if (!size || size > WHO_VA_ATTACHMENT_POLICY.pdf.maxInputBytes) {
    throw new AttachmentProcessingError("pdf-input-too-large");
  }
  const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  const name = `${id}.pdf`;
  const durableUri = await persistFile(uri, name);
  return {
    id,
    uri: durableUri,
    name,
    originalName,
    mimeType: "application/pdf",
    size,
    originalRetained: true,
    processed: false,
    serverSideValidationRequired: true
  };
}

export function useExpoWhoVaPlatformServices(): WhoVaPlatformServices {
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);

  return useMemo(
    () => ({
      pickDate: pickAndroidDate,
      captureImage,
      selectImage,
      processImage,
      selectFile,
      async startAudioRecording(): Promise<
        Awaited<ReturnType<NonNullable<WhoVaPlatformServices["startAudioRecording"]>>>
      > {
        const permission = await requestRecordingPermissionsAsync();
        if (!permission.granted) throw new Error("Microphone permission was denied.");
        await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
        await recorder.prepareToRecordAsync();
        recorder.record();
        const startedAt = Date.now();
        return {
          async stop() {
            await recorder.stop();
            await setAudioModeAsync({ allowsRecording: false });
            if (!recorder.uri) throw new Error("No audio recording URI was returned.");
            const extension = extensionForAudioUri(recorder.uri);
            const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
            const name = `${id}.${extension}`;
            const durableUri = await persistFile(recorder.uri, name);
            const info = await FileSystem.getInfoAsync(durableUri);
            return {
              id,
              uri: durableUri,
              name,
              originalName: name,
              mimeType: extension === "webm" ? "audio/webm" : "audio/mp4",
              size: info.exists && !info.isDirectory ? info.size : 0,
              durationMs: Math.max(0, Date.now() - startedAt),
              processed: true
            };
          },
          async cancel() {
            await setAudioModeAsync({ allowsRecording: false }).catch(() => undefined);
            if (recorder.isRecording) await recorder.stop().catch(() => undefined);
            if (recorder.uri) {
              await FileSystem.deleteAsync(recorder.uri, { idempotent: true }).catch(() => undefined);
            }
          }
        };
      },
      async removeAttachment(value: AttachmentReference) {
        const uri = attachmentUri(value);
        if (uri?.startsWith(FileSystem.documentDirectory ?? "file://")) {
          await FileSystem.deleteAsync(uri, { idempotent: true });
        }
      }
    }),
    [recorder]
  );
}
