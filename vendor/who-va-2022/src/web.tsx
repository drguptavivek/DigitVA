/**
 * React web package entry point, binding the shared UI to react-native-web and
 * browser adapters for navigation, drafts, audio, and attachments.
 */
import React from "react";
import {
  Image as WebImage,
  Pressable as WebPressable,
  ScrollView as WebScrollView,
  Text as WebText,
  TextInput as WebTextInput,
  View as WebView
} from "react-native-web";

import {
  createWhoVaForm,
  type WhoVaNavigationAdapter,
  type WhoVaNavigationState
} from "./ui/create-who-va-form.js";
import { createLocalStorageDraftStore } from "./draft.js";
import { loadWhoVa2022Instrument } from "./instrument-loader.js";
import { createWhoVaQuestionControls, type WhoVaPlatformServices } from "./ui/question-controls.js";
import type { AttachmentCandidate, WhoVaDraftStore } from "./types.js";
import {
  createIndexedDbWebAttachmentStore,
  cleanupOrphanedWebAttachments,
  loadWebAttachmentBlob,
  processWebImageAttachment,
  storeWebPdfAttachment,
  resolveWebAttachmentUri
} from "./web-attachments.js";
import { startWebAudioRecording } from "./web-audio.js";
import { applyWebTheme } from "./ui/web-theme.js";

function themedPrimitive(Component: React.ElementType, displayName: string): React.ElementType {
  const ThemedPrimitive = React.forwardRef<unknown, Record<string, unknown>>(
    ({ style, contentContainerStyle, ...props }, ref) => (
      <Component
        {...props}
        ref={ref}
        style={applyWebTheme(style)}
        contentContainerStyle={applyWebTheme(contentContainerStyle)}
      />
    )
  );
  ThemedPrimitive.displayName = displayName;
  return ThemedPrimitive;
}

const View = themedPrimitive(WebView, "WhoVaWebView");
const Text = themedPrimitive(WebText, "WhoVaWebText");
const TextInput = themedPrimitive(WebTextInput, "WhoVaWebTextInput");
const Pressable = themedPrimitive(WebPressable, "WhoVaWebPressable");
const ScrollView = themedPrimitive(WebScrollView, "WhoVaWebScrollView");
const Image = themedPrimitive(WebImage, "WhoVaWebImage");
const Svg = React.forwardRef<SVGSVGElement, React.SVGProps<SVGSVGElement>>((props, ref) => (
  <svg {...props} ref={ref} />
));
Svg.displayName = "WhoVaWebSvg";
const SvgCircle = React.forwardRef<SVGCircleElement, React.SVGProps<SVGCircleElement>>((props, ref) => (
  <circle {...props} ref={ref} />
));
SvgCircle.displayName = "WhoVaWebSvgCircle";
const SvgPath = React.forwardRef<SVGPathElement, React.SVGProps<SVGPathElement>>((props, ref) => (
  <path {...props} ref={ref} />
));
SvgPath.displayName = "WhoVaWebSvgPath";

const navigationStateKey = "__whoVaFormNavigation";

function readBrowserNavigationState(): WhoVaNavigationState | undefined {
  if (typeof window === "undefined") return undefined;
  const historyState = window.history.state;
  if (historyState == null || typeof historyState !== "object") return undefined;
  const state = (historyState as Record<string, unknown>)[navigationStateKey];
  if (state == null || typeof state !== "object") return undefined;
  const candidate = state as Partial<WhoVaNavigationState>;
  if (
    typeof candidate.instrumentId !== "string" ||
    typeof candidate.draftId !== "string" ||
    typeof candidate.currentSection !== "string" ||
    (candidate.view !== "form" && candidate.view !== "preview")
  )
    return undefined;
  return {
    instrumentId: candidate.instrumentId,
    draftId: candidate.draftId,
    currentSection: candidate.currentSection,
    view: candidate.view
  };
}

function browserHistoryEnvelope(state: WhoVaNavigationState): Record<string, unknown> {
  const current = window.history.state;
  return {
    ...(current != null && typeof current === "object" ? (current as Record<string, unknown>) : {}),
    [navigationStateKey]: {
      instrumentId: state.instrumentId,
      draftId: state.draftId,
      currentSection: state.currentSection,
      view: state.view
    }
  };
}

const browserNavigation: WhoVaNavigationAdapter = {
  read: readBrowserNavigationState,
  replace(state) {
    if (typeof window === "undefined") return;
    window.history.replaceState(browserHistoryEnvelope(state), "");
  },
  push(state) {
    if (typeof window === "undefined") return;
    window.history.pushState(browserHistoryEnvelope(state), "");
  },
  back() {
    if (typeof window !== "undefined") window.history.back();
  },
  subscribe(listener) {
    if (typeof window === "undefined") return () => undefined;
    const handlePopState = () => listener(readBrowserNavigationState());
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }
};

export * from "./core.js";
export {
  WHO_VA_2022_LANGUAGES,
  loadWhoVa2022Instrument,
  loadWhoVa2022Language
} from "./instrument-loader.js";
export type { WhoVaFormProps, WhoVaPlatformServices } from "./ui/create-who-va-form.js";

interface WebDateInputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "onChange" | "style"> {
  accessibilityLabel?: string;
  onChangeText: (value: string) => void;
  style?: unknown;
  testID?: string;
}

function WebDateInput({ accessibilityLabel, onChangeText, style, testID, ...props }: WebDateInputProps) {
  const flattenedStyle = (Array.isArray(style) ? style.flat(Infinity) : [style])
    .filter((entry): entry is Record<string, unknown> => typeof entry === "object" && entry !== null)
    .reduce<Record<string, unknown>>((result, entry) => Object.assign(result, entry), {});
  return (
    <input
      {...props}
      type="date"
      aria-label={accessibilityLabel}
      data-testid={testID}
      style={flattenedStyle as React.CSSProperties}
      onChange={(event) => onChangeText(event.currentTarget.value)}
    />
  );
}

function scrollToWebQuestion(questionNode: unknown) {
  if (typeof HTMLElement === "undefined" || !(questionNode instanceof HTMLElement)) return;
  questionNode.scrollIntoView?.({ behavior: "smooth", block: "start" });
  questionNode
    .querySelector<HTMLElement>(
      'input, textarea, select, button, [role="radio"], [role="checkbox"], [role="button"]'
    )
    ?.focus({ preventScroll: true });
}

function selectWebFile(accept: string, capture = false): Promise<File | undefined> {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = accept;
    if (capture) input.setAttribute("capture", "environment");
    input.addEventListener(
      "change",
      () => {
        const file = input.files?.[0];
        if (!file) {
          resolve(undefined);
          return;
        }
        resolve(file);
      },
      { once: true }
    );
    input.addEventListener("cancel", () => resolve(undefined), { once: true });
    input.click();
  });
}

const webAttachmentStore = createIndexedDbWebAttachmentStore();

/** Loads a stored attachment as a Blob so fetch/FormData can upload it without base64 conversion. */
export function loadWhoVaWebAttachmentBlob(reference: { id: string }): Promise<Blob | undefined> {
  return loadWebAttachmentBlob(reference, webAttachmentStore);
}

/** Removes binaries no longer referenced by the supplied drafts or answer values. */
export function cleanupWhoVaWebAttachments(references: Iterable<unknown>): Promise<number> {
  return cleanupOrphanedWebAttachments(references, webAttachmentStore);
}

async function selectAndProcessWebImage(capture = false): Promise<AttachmentCandidate | undefined> {
  const file = await selectWebFile("image/jpeg,image/png", capture);
  return file ? processWebImageAttachment(file, { store: webAttachmentStore }) : undefined;
}

const webAttachmentPlatform: WhoVaPlatformServices = {
  startAudioRecording: async () => startWebAudioRecording({ store: webAttachmentStore }),
  captureImage: async () => selectAndProcessWebImage(true),
  selectImage: async () => selectAndProcessWebImage(),
  selectFile: async (_question, _data, acceptedMimeTypes) => {
    const file = await selectWebFile(acceptedMimeTypes.join(","));
    if (!file) return undefined;
    const imageSelected =
      acceptedMimeTypes.includes("image/jpeg") &&
      (file.type === "image/jpeg" || file.type === "image/png" || /\.(?:jpe?g|png)$/i.test(file.name));
    if (imageSelected) return processWebImageAttachment(file, { store: webAttachmentStore });
    if (acceptedMimeTypes.includes("application/pdf"))
      return storeWebPdfAttachment(file, { store: webAttachmentStore });
    return undefined;
  },
  resolveAttachmentUri: async (attachment) => {
    if (
      attachment == null ||
      Array.isArray(attachment) ||
      typeof attachment !== "object" ||
      typeof attachment.id !== "string"
    )
      return undefined;
    return resolveWebAttachmentUri({ id: attachment.id }, webAttachmentStore);
  },
  releaseAttachmentUri: (uri) => {
    if (uri.startsWith("blob:")) URL.revokeObjectURL(uri);
  },
  removeAttachment: async (attachment) => {
    if (
      attachment != null &&
      !Array.isArray(attachment) &&
      typeof attachment === "object" &&
      typeof attachment.id === "string"
    ) {
      await webAttachmentStore.remove(attachment.id);
    }
  }
};

export interface InsecureWhoVaBrowserDefaults {
  draftStore: WhoVaDraftStore;
  platform: WhoVaPlatformServices;
}

/**
 * Explicitly opts a demo or low-risk prototype into plaintext localStorage and
 * unencrypted IndexedDB. Production hosts should inject protected adapters.
 */
export function createInsecureWhoVaBrowserDefaults(): InsecureWhoVaBrowserDefaults {
  return {
    draftStore: createLocalStorageDraftStore(),
    platform: webAttachmentPlatform
  };
}

export {
  cleanupOrphanedWebAttachments,
  createBrowserImageTranscoder,
  createIndexedDbWebAttachmentStore,
  processWebImageAttachment,
  storeWebPdfAttachment,
  loadWebAttachmentBlob,
  resolveWebAttachmentUri
} from "./web-attachments.js";
export { startWebAudioRecording } from "./web-audio.js";
export type * from "./web-audio.js";

export const WhoVaForm = createWhoVaForm(
  {
    View,
    Text,
    TextInput,
    DateInput: WebDateInput,
    Pressable,
    ScrollView,
    Image,
    Svg,
    SvgCircle,
    SvgPath,
    navigation: browserNavigation,
    scrollToQuestion: scrollToWebQuestion
  },
  loadWhoVa2022Instrument
);

export const WhoVaQuestionControls = createWhoVaQuestionControls({
  View,
  Text,
  TextInput,
  DateInput: WebDateInput,
  Pressable,
  Image
});
export type { WhoVaQuestionControlProps } from "./ui/question-controls.js";
