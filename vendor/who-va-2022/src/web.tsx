/**
 * React web package entry point, binding the shared UI to react-native-web and
 * browser adapters for navigation, drafts, audio, and attachments.
 */
import React from "react";
import {
  ar,
  ca,
  cs,
  da,
  DatePickerModal,
  de,
  el,
  en,
  enGB,
  es,
  fi,
  fr,
  he,
  hi,
  id,
  it,
  ja,
  ko,
  nl,
  noNO,
  pl,
  pt,
  registerTranslation,
  ro,
  ru,
  sv,
  th,
  tr,
  ukUA,
  zh,
  zhTW
} from "react-native-paper-dates";
import { MD3LightTheme, PaperProvider } from "react-native-paper";
import { SafeAreaProvider } from "react-native-safe-area-context";
import {
  Image as WebImage,
  Modal as WebModal,
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
import { prefersReducedMotion } from "./ui/form-presentation.js";
import { applyWebTheme } from "./ui/web-theme.js";
import { isValidIsoDate } from "./date.js";

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
export const WebAudioPlayer: React.ComponentType<{
  uri: string;
  accessibilityLabel: string;
  onError: () => void;
}> = ({ uri, accessibilityLabel, onError }) => (
  <audio
    controls
    preload="metadata"
    src={uri}
    aria-label={accessibilityLabel}
    onError={onError}
    style={{ display: "block", width: "100%", maxWidth: 640 }}
  />
);
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

interface WebDateInputHandle {
  showPicker: () => void;
}

interface WebDateInputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "onChange" | "style"> {
  accessibilityLabel?: string;
  locale?: string;
  onChangeText: (value: string) => void;
  style?: unknown;
  testID?: string;
}

const datePickerTranslations: Record<string, typeof en> = {
  ar,
  ca,
  cs,
  da,
  de,
  el,
  en,
  "en-GB": enGB,
  es,
  fi,
  fr,
  he,
  hi,
  id,
  it,
  ja,
  ko,
  nl,
  "no-NO": noNO,
  no: noNO,
  pl,
  pt,
  ro,
  ru,
  sv,
  th,
  tr,
  uk: ukUA,
  "uk-UA": ukUA,
  zh,
  "zh-TW": zhTW
};

/** Draw the date picker's known Paper icons locally so web never needs an icon font. */
function webDatePickerIcon({
  name,
  color,
  size,
  testID
}: {
  name: string;
  color?: string;
  size: number;
  direction?: "ltr" | "rtl" | "auto";
  testID?: string;
}) {
  const path = name.includes("left")
    ? "M15 18l-6-6 6-6"
    : name.includes("right")
      ? "M9 18l6-6-6-6"
      : name.includes("close")
        ? "M18 6L6 18M6 6l12 12"
        : name.includes("calendar")
          ? "M7 3v3m10-3v3M4 9h16M5 5h14a1 1 0 011 1v14H4V6a1 1 0 011-1zm2 8h2m3 0h2m3 0h1m-11 4h2m3 0h2"
          : name.includes("pencil") || name.includes("edit")
            ? "M4 16.5V20h3.5L19 8.5 15.5 5 4 16.5zM13.5 7l3.5 3.5"
            : "M7 12l5 5 5-5";
  return (
    <svg
      aria-hidden="true"
      data-testid={testID}
      focusable="false"
      height={size}
      viewBox="0 0 24 24"
      width={size}
    >
      <path
        d={path}
        fill="none"
        stroke={color ?? "currentColor"}
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
      />
    </svg>
  );
}

/** Copy host date-field colors and font into the modal portal, outside the form's CSS scope. */
function webDatePickerTheme(input: HTMLInputElement | null) {
  const computed = input && typeof window !== "undefined" ? window.getComputedStyle(input) : undefined;
  const token = (name: string, fallback: string) => computed?.getPropertyValue(name).trim() || fallback;
  const surface = token("--who-2022-web-color-surface", "#ffffff");
  const ink = token("--who-2022-web-color-ink", "#1f2937");
  const brand = token("--who-2022-web-color-brand", "#1b4f9c");
  const brandDeep = token("--who-2022-web-color-brand-deep", "#004687");
  const brandSoft = token("--who-2022-web-color-brand-soft", "#eaf1fa");
  const border = token("--who-2022-web-color-border", "#e2e8f0");
  const muted = token("--who-2022-web-color-muted", "#667085");
  const fontFamily = computed?.fontFamily || "system-ui, sans-serif";
  const fonts = Object.fromEntries(
    Object.entries(MD3LightTheme.fonts).map(([name, style]) => [name, { ...style, fontFamily }])
  ) as typeof MD3LightTheme.fonts;
  return {
    ...MD3LightTheme,
    fonts,
    colors: {
      ...MD3LightTheme.colors,
      primary: brand,
      onPrimary: surface,
      primaryContainer: brandSoft,
      onPrimaryContainer: brandDeep,
      secondary: brand,
      onSecondary: surface,
      surface,
      surfaceVariant: surface,
      onSurface: ink,
      onSurfaceVariant: muted,
      outline: border,
      outlineVariant: border,
      backdrop: "rgba(31, 41, 55, 0.45)",
      elevation: {
        ...MD3LightTheme.colors.elevation,
        level0: surface,
        level1: surface,
        level2: surface,
        level3: surface,
        level4: surface,
        level5: surface
      }
    }
  };
}

/** Convert a canonical ISO date to a local-noon date for the browser picker; invalid values return undefined. */
function webDateFromIso(value: string | undefined): Date | undefined {
  if (!value || !isValidIsoDate(value)) return undefined;
  return new Date(`${value}T12:00:00`);
}

/** Serialize a browser-picked local date without shifting it across time zones. */
function webDateToIso(value: Date): string {
  const year = String(value.getFullYear()).padStart(4, "0");
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

const WebDateInput = React.forwardRef<WebDateInputHandle, WebDateInputProps>(function WebDateInput(
  {
    accessibilityLabel,
    disabled,
    locale = "en",
    max,
    min,
    onChangeText,
    readOnly,
    style,
    testID,
    value,
    ...props
  },
  ref
) {
  const [calendarOpen, setCalendarOpen] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const selectedDate = webDateFromIso(typeof value === "string" ? value : undefined);
  const minDate = typeof min === "string" ? webDateFromIso(min) : undefined;
  const maxDate = typeof max === "string" ? webDateFromIso(max) : undefined;
  React.useImperativeHandle(
    ref,
    () => ({
      showPicker() {
        if (disabled || readOnly) return;
        const language = locale.split(/[-_]/, 1)[0] ?? "en";
        registerTranslation(locale, datePickerTranslations[locale] ?? datePickerTranslations[language] ?? en);
        setCalendarOpen(true);
      }
    }),
    [disabled, locale, readOnly]
  );
  const themed = applyWebTheme(style);
  const flattenedStyle = (Array.isArray(themed) ? themed.flat(Infinity) : [themed])
    .filter((entry): entry is Record<string, unknown> => typeof entry === "object" && entry !== null)
    .reduce<Record<string, unknown>>((result, entry) => Object.assign(result, entry), {});
  const { paddingHorizontal, paddingVertical, ...rest } = flattenedStyle;
  return (
    <>
      <input
        {...props}
        ref={inputRef}
        disabled={disabled}
        max={max}
        min={min}
        readOnly={readOnly}
        type="date"
        aria-label={accessibilityLabel}
        data-testid={testID}
        style={
          {
            borderStyle: "solid",
            boxSizing: "border-box",
            font: "inherit",
            fontSize: 16,
            lineHeight: "24px",
            margin: 0,
            paddingBlock: paddingVertical,
            paddingInline: paddingHorizontal,
            ...rest
          } as React.CSSProperties
        }
        onChange={(event) => onChangeText(event.currentTarget.value)}
        value={value}
      />
      {calendarOpen ? (
        <SafeAreaProvider>
          <PaperProvider theme={webDatePickerTheme(inputRef.current)} settings={{ icon: webDatePickerIcon }}>
            <DatePickerModal
              {...(selectedDate ? { date: selectedDate } : {})}
              label={accessibilityLabel ?? ""}
              locale={locale}
              mode="single"
              validRange={{
                ...(minDate ? { startDate: minDate } : {}),
                ...(maxDate ? { endDate: maxDate } : {})
              }}
              onConfirm={({ date: selectedDate }) => {
                setCalendarOpen(false);
                if (selectedDate) onChangeText(webDateToIso(selectedDate));
              }}
              onDismiss={() => setCalendarOpen(false)}
              visible
            />
          </PaperProvider>
        </SafeAreaProvider>
      ) : null}
    </>
  );
});

interface WebSelectProps {
  accessibilityLabel?: string;
  disabled?: boolean;
  emptyOptionLabel?: string;
  onValueChange: (value: string) => void;
  options: ReadonlyArray<{ value: string; label: string }>;
  style?: unknown;
  testID?: string;
  value: string;
}

/** A native <select>, themed like the inputs; used for the month of a date. */
const WebSelect = React.forwardRef<HTMLSelectElement, WebSelectProps>(function WebSelect(
  { accessibilityLabel, disabled, emptyOptionLabel, onValueChange, options, style, testID, value },
  ref
) {
  const themed = applyWebTheme(style);
  const flattenedStyle = (Array.isArray(themed) ? themed.flat(Infinity) : [themed])
    .filter((entry): entry is Record<string, unknown> => typeof entry === "object" && entry !== null)
    .reduce<Record<string, unknown>>((result, entry) => Object.assign(result, entry), {});
  return (
    <select
      aria-label={accessibilityLabel}
      data-testid={testID}
      disabled={disabled}
      onChange={(event) => onValueChange(event.currentTarget.value)}
      ref={ref}
      style={{ background: "transparent", font: "inherit", ...flattenedStyle } as React.CSSProperties}
      value={value}
    >
      <option value="">{emptyOptionLabel ?? ""}</option>
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
});

function scrollToWebQuestion(questionNode: unknown) {
  if (typeof HTMLElement === "undefined" || !(questionNode instanceof HTMLElement)) return;
  questionNode.scrollIntoView?.({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
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
    Select: WebSelect,
    PartialSelect: WebSelect,
    Pressable,
    ScrollView,
    Image,
    AudioPlayer: WebAudioPlayer,
    Modal: WebModal,
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
  Select: WebSelect,
  PartialSelect: WebSelect,
  Pressable,
  AudioPlayer: WebAudioPlayer,
  Image
});
export type { WhoVaQuestionControlProps } from "./ui/question-controls.js";
