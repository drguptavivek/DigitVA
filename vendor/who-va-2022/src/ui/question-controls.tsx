/**
 * Factory and registry for reusable questionnaire controls, with host-injected
 * primitives and services for dates, audio, images, and files.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";

import {
  AttachmentProcessingError,
  WHO_VA_ATTACHMENT_POLICY,
  isProcessedImageAttachment,
  isRetainedPdfAttachment,
  type ImageAttachmentPolicy
} from "../attachments.js";
import { validateAnswer } from "../engine/validation.js";
import { NATIONAL_ID_FIELD } from "../national-id.js";
import type {
  AnswerValue,
  AttachmentCandidate,
  AttachmentReference,
  InstrumentQuestion,
  ProcessedImageAttachmentReference,
  SubmissionData,
  ValidationIssue
} from "../types.js";
import { columnLayout, formatGrouped, hasAppearance, rangeParameters, rangeValues } from "./appearance.js";
import {
  dateFormatPlaceholder,
  formatDdMmmYyyy,
  formatDisplayDate,
  isoFromParts,
  localizedMonthNames,
  parseDisplayDate
} from "./date-value.js";
import { ENGLISH_UI_MESSAGES, type WhoVaUiMessages } from "../i18n.js";
import {
  asciiDigits,
  attachmentDetails,
  attachmentErrorMessage,
  attachmentMimeType,
  attachmentReference,
  constraintBounds,
  languageChoiceLabel,
  numericUnit,
  localized,
  localizedRich,
  questionControlStyles,
  questionLabel
} from "./question-control-support.js";
import { englishAlongside, plainText } from "./localize.js";
import { defaultFormTheme as T, useFormTheme } from "./theme.js";

/** Tabler "calendar" outline (24 grid, stroke 2): the same line-icon family as the app header, drawn in the glyph colour. Only rendered where the web date input exists. */
const CALENDAR_ICON = React.createElement(
  "svg",
  { width: 22, height: 22, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round", focusable: "false", style: { display: "block" } },
  React.createElement("path", { d: "M4 7a2 2 0 0 1 2 -2h12a2 2 0 0 1 2 2v12a2 2 0 0 1 -2 2h-12a2 2 0 0 1 -2 -2v-12z" }),
  React.createElement("path", { d: "M16 3v4" }),
  React.createElement("path", { d: "M8 3v4" }),
  React.createElement("path", { d: "M4 11h16" }),
);

export { questionControlStyles } from "./question-control-support.js";

export interface WhoVaPlatformServices {
  captureAudio?: (question: InstrumentQuestion, data: SubmissionData) => Promise<AttachmentReference>;
  startAudioRecording?: (
    question: InstrumentQuestion,
    data: SubmissionData
  ) => Promise<WhoVaAudioRecordingSession>;
  pickDate?: (
    question: InstrumentQuestion,
    data: SubmissionData,
    currentValue?: string
  ) => Promise<string | undefined>;
  captureImage?: (
    question: InstrumentQuestion,
    data: SubmissionData
  ) => Promise<AttachmentCandidate | undefined>;
  selectImage?: (
    question: InstrumentQuestion,
    data: SubmissionData
  ) => Promise<AttachmentCandidate | undefined>;
  processImage?: (
    selection: AttachmentCandidate,
    policy: ImageAttachmentPolicy,
    question: InstrumentQuestion,
    data: SubmissionData
  ) => Promise<ProcessedImageAttachmentReference>;
  selectFile?: (
    question: InstrumentQuestion,
    data: SubmissionData,
    acceptedMimeTypes: string[]
  ) => Promise<AttachmentCandidate | undefined>;
  /**
   * Open a drawing surface for the `draw` and `signature` appearances and
   * return the resulting image. The host owns the canvas, as it owns the
   * camera and the recorder.
   */
  captureDrawing?: (
    question: InstrumentQuestion,
    data: SubmissionData,
    mode: "draw" | "signature"
  ) => Promise<AttachmentCandidate | undefined>;
  /**
   * Scan a paper document: edge detection, crop and perspective correction on the phone, one page. Offered as the
   * primary button on document questions; a rejection (no scanner on this phone) falls back to `captureImage`.
   */
  scanDocument?: (
    question: InstrumentQuestion,
    data: SubmissionData
  ) => Promise<AttachmentCandidate | undefined>;
  /**
   * Score a just-captured image's sharpness, on the phone, before it is processed. `blurry` makes the control
   * offer a retake; it never blocks saving, and a failure counts as sharp.
   */
  checkSharpness?: (uri: string) => Promise<{ score: number; blurry: boolean }>;
  /** Opens a stored photo full screen (pinch-zoom, pan, rotate); without it the control shows a plain enlarged view. */
  ImageViewer?: React.ComponentType<WhoVaImageViewerProps>;
  /** Return an ODK geopoint string: "latitude longitude altitude accuracy". */
  captureLocation?: (question: InstrumentQuestion, data: SubmissionData) => Promise<string | undefined>;
  /** Return the scanned barcode value, or undefined when the user cancels. */
  scanBarcode?: (question: InstrumentQuestion, data: SubmissionData) => Promise<string | undefined>;
  /** Plays a saved recording where the primitives supply no player (a native host brings its own). */
  AudioPlayer?: React.ComponentType<{ uri: string; accessibilityLabel: string; onError: () => void }>;
  resolveAttachmentUri?: (attachment: AttachmentReference) => Promise<string | undefined>;
  releaseAttachmentUri?: (uri: string) => void;
  removeAttachment?: (attachment: AttachmentReference) => Promise<void>;
}

/** The full-screen photo viewer a host supplies. Rotation is view-only: the stored image is never changed. */
export interface WhoVaImageViewerProps {
  uri: string;
  accessibilityLabel: string;
  rotateLabel: string;
  closeLabel: string;
  onClose: () => void;
}

/** What a recorder that can pause reports: recorded time (pauses excluded) and the take's limit, if it has one. */
export interface WhoVaAudioRecordingState {
  elapsedMs: number;
  paused: boolean;
  limitMs?: number;
}

export interface WhoVaAudioRecordingSession {
  stop(): Promise<AttachmentReference>;
  cancel(): void | Promise<void>;
  /** Optional: a host whose recorder can pause offers all three; the control then shows Pause / Resume and the remaining time. */
  pause?(): void | Promise<void>;
  resume?(): void | Promise<void>;
  /** Polled while recording. The host may also pause by itself (the app went to the background); this reports it. */
  getState?(): WhoVaAudioRecordingState;
}

export interface WhoVaQuestionControlProps {
  question: InstrumentQuestion;
  value: AnswerValue | undefined;
  data: SubmissionData;
  locale: string;
  /** Show the English beneath translated choice labels (`show-english`). */
  showEnglish?: boolean | undefined;
  messages?: WhoVaUiMessages;
  issues: ValidationIssue[];
  platform?: WhoVaPlatformServices | undefined;
  onAnswer: (value: AnswerValue | undefined) => void;
  onDraftIssue?: ((questionName: string, issue: ValidationIssue | undefined) => void) | undefined;
  /**
   * How many columns a short choice list may use where it sits: 2 on a
   * compact form, 3 on a medium one, 4 on a wide one. Unset, lists stay one
   * choice per row.
   */
  choiceColumns?: number | undefined;
}

export interface WhoVaQuestionControlPrimitives {
  View: React.ElementType;
  Text: React.ElementType;
  TextInput: React.ElementType;
  DateInput?: React.ElementType | undefined;
  /** A native select (web); see WhoVaPrimitiveSet.Select. */
  Select?: React.ElementType | undefined;
  /** Select primitive reserved for partial date selectors. */
  PartialSelect?: React.ElementType | undefined;
  Pressable: React.ElementType;
  /** Plays a resolved saved audio attachment. */
  AudioPlayer?:
    | React.ComponentType<{
        uri: string;
        accessibilityLabel: string;
        onError: () => void;
      }>
    | undefined;
  Image?: React.ElementType | undefined;
  /** Holds the plain full-screen photo view when the host has no ImageViewer; without it the view is an overlay. */
  Modal?: React.ElementType | undefined;
  /** Draw the red delete icon; without them a text glyph stands in. */
  Svg?: React.ElementType | undefined;
  SvgPath?: React.ElementType | undefined;
  /**
   * Renders ODK's inline markup in choice labels. Optional: without it labels
   * fall back to the tag-stripped text, which is what they were before.
   */
  RichText?: React.ComponentType<{ source: string }> | undefined;
  platform?: WhoVaPlatformServices | undefined;
}

const EMPTY_SELECTED_VALUES: readonly string[] = [];

export function incompleteDateIssue(
  question: InstrumentQuestion,
  draft: string | undefined,
  locale: string,
  messages: WhoVaUiMessages = ENGLISH_UI_MESSAGES
): ValidationIssue | undefined {
  if (question.control !== "date" || !draft) return undefined;
  if (hasAppearance(question, "year")) {
    return /^\d{4}$/.test(draft)
      ? undefined
      : { question: question.name, code: "type", message: messages.fourDigitYear };
  }
  return parseDisplayDate(draft, locale)
    ? undefined
    : {
        question: question.name,
        code: "type",
        message: messages.invalidDate(dateFormatPlaceholder(locale), formatDisplayDate("2026-07-17", locale))
      };
}

/**
 * The ISO dates a date question's constraint states outright, for the
 * picker's min/max: `. <= today()` and literal `date('1915-01-01')`. A bound
 * on another answer is left open, and the engine still validates every value.
 */
export function dateBounds(question: InstrumentQuestion): { min?: string; max?: string } {
  const source = question.constraint?.source ?? "";
  const bounds: { min?: string; max?: string } = {};
  const today = new globalThis.Date();
  const todayIso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  for (const match of source.matchAll(
    /\.\s*(<=|<|>=|>)\s*(today\(\)|date\(date\('(\d{4}-\d{2}-\d{2})'\)\)|date\('(\d{4}-\d{2}-\d{2})'\))/g
  )) {
    const [, operator, , nested, literal] = match;
    const iso = nested ?? literal ?? todayIso;
    if ((operator === "<=" || operator === "<") && !bounds.max) bounds.max = iso;
    if ((operator === ">=" || operator === ">") && !bounds.min) bounds.min = iso;
  }
  return bounds;
}

/** Commits that buffered controls (the national ID) hold back until blur. */
const pendingFlushes = new Set<() => void>();

/**
 * Commit every buffered, still-focused answer now. A native Next, Save or
 * Submit tap does not blur the focused TextInput, so the form calls this
 * before it advances, saves, navigates or submits.
 */
export function flushPendingAnswers(): void {
  for (const flush of [...pendingFlushes]) flush();
}

export function createWhoVaQuestionControls(primitives: WhoVaQuestionControlPrimitives) {
  const {
    View,
    Text: PrimitiveText,
    TextInput: HostTextInput,
    DateInput,
    Select,
    PartialSelect,
    Pressable,
    AudioPlayer,
    Image,
    Modal,
    Svg,
    SvgPath
  } = primitives;
  const RichText = primitives.RichText;

  /**
   * The host TextInput with the Petrol focus ring: with a host theme, while focused the field's edge takes the
   * primary colour (`inputFocused`), then the caller's own onFocus/onBlur run. A part with no edge (a date part)
   * shows none. Without a host theme the host TextInput gets the props untouched.
   */
  const TextInput: React.ElementType = React.forwardRef(function FocusRingInput(
    props: { style?: unknown; onFocus?: (event: unknown) => void; onBlur?: (event: unknown) => void; [prop: string]: unknown },
    ref: React.Ref<unknown>
  ) {
    const [focused, setFocused] = useState(false);
    const petrol = useFormTheme() !== undefined;
    if (!petrol) return <HostTextInput {...props} ref={ref} />;
    return (
      <HostTextInput
        {...props}
        ref={ref}
        style={[props.style, focused && questionControlStyles.inputFocused]}
        onFocus={(event: unknown) => {
          setFocused(true);
          props.onFocus?.(event);
        }}
        onBlur={(event: unknown) => {
          setFocused(false);
          props.onBlur?.(event);
        }}
      />
    );
  });

  /**
   * A choice label, with its markup rendered when a renderer is supplied, and
   * with the English on a muted line beneath it when `showEnglish` is set.
   */
  function ChoiceLabel({
    choice,
    locale,
    showEnglish
  }: {
    choice: NonNullable<InstrumentQuestion["choices"]>[number];
    locale: string;
    showEnglish?: boolean | undefined;
  }) {
    const label = RichText ? (
      <RichText source={localizedRich(choice.label, locale, choice.value)} />
    ) : (
      <>{localized(choice.label, locale, choice.value)}</>
    );
    const english = showEnglish ? englishAlongside(choice.label, locale) : "";
    if (!english) return label;
    return (
      <>
        {/* Two languages in one label: each part names its own, so a screen reader switches voice. */}
        <PrimitiveText lang={locale} accessibilityLanguage={locale}>
          {label}
        </PrimitiveText>
        {"\n"}
        <PrimitiveText lang="en" accessibilityLanguage="en" style={questionControlStyles.choiceEnglish}>
          {RichText ? <RichText source={english} /> : plainText(english)}
        </PrimitiveText>
      </>
    );
  }

  // Material Design icons (as react-icons ships them: MdDelete, MdRotateRight, MdPhotoCamera, MdCollections,
  // MdAttachFile, MdDocumentScanner, MdClose, MdMic, MdStop, MdPause), Apache-2.0.
  const ICON_PATHS = {
    delete: "M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z",
    rotate:
      "M15.55 5.55L11 1v3.07C7.06 4.56 4 7.92 4 12s3.05 7.44 7 7.93v-2.02c-2.84-.48-5-2.94-5-5.91s2.16-5.43 5-5.91V10l4.55-4.45zM19.93 11c-.17-1.39-.72-2.73-1.62-3.89l-1.42 1.42c.54.75.88 1.6 1.02 2.47h2.02zM13 17.9v2.02c1.39-.17 2.74-.71 3.9-1.61l-1.44-1.44c-.75.54-1.59.89-2.46 1.03zm3.89-2.42l1.42 1.41c.9-1.16 1.45-2.5 1.62-3.89h-2.02c-.14.87-.48 1.72-1.02 2.48z",
    camera: [
      "M12 15.2a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4z",
      "M9 2 7.17 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2h-3.17L15 2H9zm3 15c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5z"
    ],
    gallery:
      "M22 16V4c0-1.1-.9-2-2-2H8c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2zm-11-4 2.03 2.71L16 11l4 5H8l3-4zM2 6v14c0 1.1.9 2 2 2h14v-2H4V6H2z",
    attach:
      "M16.5 6v11.5c0 2.21-1.79 4-4 4s-4-1.79-4-4V5c0-1.38 1.12-2.5 2.5-2.5s2.5 1.12 2.5 2.5v10.5c0 .55-.45 1-1 1s-1-.45-1-1V6H10v9.5c0 1.38 1.12 2.5 2.5 2.5s2.5-1.12 2.5-2.5V5c0-2.21-1.79-4-4-4S7 2.79 7 5v12.5c0 3.04 2.46 5.5 5.5 5.5s5.5-2.46 5.5-5.5V6h-1.5z",
    calendar: "M20 3h-1V1h-2v2H7V1H5v2H4c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 18H4V8h16v13z",
    scan: "M7 3H4v3H2V1h5v2zm15 3V1h-5v2h3v3h2zM7 21H4v-3H2v5h5v-2zm13-3v3h-3v2h5v-5h-2zm-1 0c0 1.1-.9 2-2 2H7c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2v12zM15 8H9v2h6V8zm0 3H9v2h6v-2zm0 3H9v2h6v-2z",
    close: "M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z",
    mic: "M12 14c1.66 0 2.99-1.34 2.99-3L15 5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c0 3-2.54 5.1-5.3 5.1S6.7 14 6.7 11H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c3.28-.48 6-3.3 6-6.72h-1.7z",
    stop: "M6 6h12v12H6z",
    pause: "M6 19h4V5H6v14zm8-14v14h4V5h-4z"
  } as const;
  type IconName = keyof typeof ICON_PATHS;
  /** What a host without SVG shows instead of an icon. */
  const ICON_FALLBACK: Record<IconName, string> = {
    delete: "🗑",
    rotate: "↻",
    camera: "📷",
    gallery: "🖼",
    attach: "📎",
    calendar: "📅",
    scan: "⎚",
    close: "✕",
    mic: "🎤",
    stop: "■",
    pause: "⏸"
  };

  /** One icon, decorative: the button around it carries the name. */
  function Glyph({ icon, color, size = 24 }: { icon: IconName; color: string; size?: number }) {
    if (!Svg || !SvgPath) return <PrimitiveText style={{ color, fontSize: size - 2 }}>{ICON_FALLBACK[icon]}</PrimitiveText>;
    const paths: readonly string[] = typeof ICON_PATHS[icon] === "string" ? [ICON_PATHS[icon] as string] : ICON_PATHS[icon];
    return (
      <Svg width={size} height={size} viewBox="0 0 24 24" fill={color} aria-hidden="true" focusable="false">
        {paths.map((d) => (
          <SvgPath key={d} d={d} />
        ))}
      </Svg>
    );
  }

  /** A text button's content with its icon in front; the text alone where the host draws no SVG. */
  function IconLabel({ icon, color, children }: { icon: IconName; color: string; children: React.ReactNode }) {
    if (!Svg || !SvgPath) return <>{children}</>;
    return (
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, maxWidth: "100%" }}>
        <Glyph icon={icon} color={color} size={20} />
        {children}
      </View>
    );
  }

  /**
   * One button of an attachment action row: icon and label, 48 tall, sharing the row's width equally with its
   * neighbours. `primary` is filled; the rest are tint-filled secondaries.
   */
  function ActionButton({
    icon,
    label,
    primary = false,
    invalid = false,
    disabled = false,
    busy = false,
    testID,
    describedBy,
    onPress
  }: {
    icon?: IconName | undefined;
    label: string;
    primary?: boolean;
    invalid?: boolean;
    disabled?: boolean | undefined;
    busy?: boolean;
    testID?: string | undefined;
    describedBy?: string | undefined;
    onPress: () => void;
  }) {
    const text = (
      <PrimitiveText
        style={[
          primary ? questionControlStyles.buttonText : questionControlStyles.buttonTextSecondary,
          questionControlStyles.actionButtonText
        ]}
      >
        {label}
      </PrimitiveText>
    );
    return (
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ disabled: Boolean(disabled), busy }}
        aria-describedby={describedBy}
        aria-invalid={invalid || undefined}
        testID={testID}
        disabled={disabled}
        style={[
          questionControlStyles.button,
          questionControlStyles.actionButton,
          !primary && questionControlStyles.buttonSecondary,
          invalid && (primary ? questionControlStyles.buttonError : questionControlStyles.buttonSecondaryError),
          disabled && questionControlStyles.buttonDisabled
        ]}
        onPress={onPress}
      >
        {icon ? (
          <IconLabel icon={icon} color={primary ? T.onPrimary : T.primary}>
            {text}
          </IconLabel>
        ) : (
          text
        )}
      </Pressable>
    );
  }

  /**
   * A square 48px icon button; the label is its accessible name. `danger`
   * (red, for delete: always last in its row) or the secondary look for the photo viewer's actions.
   */
  function IconButton({
    icon,
    label,
    testID,
    danger = false,
    onPress
  }: {
    icon: IconName;
    label: string;
    testID?: string | undefined;
    danger?: boolean;
    onPress: () => void;
  }) {
    const color = danger ? T.danger : T.primary;
    return (
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={label}
        aria-label={label}
        testID={testID}
        hitSlop={8}
        style={[
          questionControlStyles.button,
          danger ? questionControlStyles.buttonDanger : questionControlStyles.buttonSecondary,
          questionControlStyles.buttonCompact,
          { minWidth: 48, minHeight: 48, paddingHorizontal: 0, alignItems: "center", justifyContent: "center" }
        ]}
        onPress={onPress}
      >
        <Glyph icon={icon} color={color} />
      </Pressable>
    );
  }

  /**
   * An inline "are you sure" for an action that destroys a saved attachment
   * (owner, 2026-10-30): the red button goes ahead, the other keeps it.
   */
  function ConfirmPrompt({
    testID,
    prompt,
    confirmLabel,
    cancelLabel,
    confirmTone = "danger",
    onConfirm,
    onCancel
  }: {
    testID: string;
    prompt: string;
    confirmLabel: string;
    cancelLabel: string;
    /** `primary` for a prompt whose yes destroys nothing (the blurry-photo retake). */
    confirmTone?: "danger" | "primary";
    onConfirm: () => void;
    onCancel: () => void;
  }) {
    const danger = confirmTone === "danger";
    return (
      <View accessibilityRole="alert" testID={testID} style={{ gap: 8, marginTop: 8 }}>
        <PrimitiveText style={questionControlStyles.choiceText}>{prompt}</PrimitiveText>
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
          <Pressable
            accessibilityRole="button"
            testID={`${testID}-yes`}
            style={[
              questionControlStyles.button,
              danger && questionControlStyles.buttonDanger,
              questionControlStyles.buttonCompact
            ]}
            onPress={onConfirm}
          >
            <PrimitiveText style={danger ? questionControlStyles.buttonTextDanger : questionControlStyles.buttonText}>
              {confirmLabel}
            </PrimitiveText>
          </Pressable>
          <Pressable
            accessibilityRole="button"
            testID={`${testID}-cancel`}
            style={[questionControlStyles.button, questionControlStyles.buttonSecondary, questionControlStyles.buttonCompact]}
            onPress={onCancel}
          >
            <PrimitiveText style={questionControlStyles.buttonTextSecondary}>{cancelLabel}</PrimitiveText>
          </Pressable>
        </View>
      </View>
    );
  }

  /**
   * The radio circle or checkbox square at the start of a choice row. Purely
   * visual: the row's Pressable carries the role and state, so this is hidden
   * from assistive technology.
   */
  function ChoiceIndicator({ kind, selected }: { kind: "radio" | "checkbox"; selected: boolean }) {
    const radio = kind === "radio";
    return (
      <View
        aria-hidden="true"
        style={[
          questionControlStyles.choiceIndicator,
          radio ? questionControlStyles.choiceIndicatorRadio : questionControlStyles.choiceIndicatorCheckbox,
          selected && questionControlStyles.choiceIndicatorSelected,
          selected && !radio && questionControlStyles.choiceIndicatorCheckboxSelected
        ]}
      >
        {selected ? (
          radio ? (
            <View style={questionControlStyles.choiceIndicatorRadioDot} />
          ) : (
            <PrimitiveText style={questionControlStyles.choiceIndicatorCheck}>✓</PrimitiveText>
          )
        ) : null}
      </View>
    );
  }

  function Text({ question, value, locale, issues, onAnswer }: WhoVaQuestionControlProps) {
    const multiline = hasAppearance(question, "multiline");
    const numbersOnly = hasAppearance(question, "numbers");
    const masked = hasAppearance(question, "masked");
    const grouped = hasAppearance(question, "thousands-sep");
    const readOnly = question.readOnly;
    // The national ID is typed into a local buffer and committed (reduced by
    // the session) on blur, end/submit editing, unmount, or a flush by the
    // form before it advances, saves or submits, so the full number never
    // reaches the session data or a draft and typing is not rewritten key by
    // key. A buffer typed over a value that then changed from outside
    // (replaceData, server merge, relevance reset) is dropped, not shown stale.
    const buffered = question.name === NATIONAL_ID_FIELD;
    const [typed, setTyped] = useState<string>();
    const typedOver = useRef<unknown>(undefined);
    const stale = typed !== undefined && value !== typedOver.current;
    const live = stale ? undefined : typed;
    const pending = useRef<{ text: string | undefined; commit: typeof onAnswer }>({ text: undefined, commit: onAnswer });
    pending.current = { text: live, commit: onAnswer };
    const commitTyped = () => {
      const { text, commit } = pending.current;
      if (text === undefined) return;
      pending.current = { text: undefined, commit };
      setTyped(undefined);
      commit(text || undefined);
    };
    useEffect(() => {
      if (stale) setTyped(undefined);
    }, [stale]);
    useEffect(() => {
      if (!buffered) return undefined;
      pendingFlushes.add(commitTyped);
      return () => {
        pendingFlushes.delete(commitTyped);
        const { text, commit } = pending.current;
        if (text !== undefined) commit(text || undefined);
      };
      // commitTyped only reads refs, so the first one registered stays valid.
    }, [buffered]);
    return (
      <TextInput
        accessibilityLabel={questionLabel(question, locale)}
        testID={`question-${question.name}`}
        style={[
          questionControlStyles.input,
          multiline && questionControlStyles.narrativeInput,
          issues.length > 0 && questionControlStyles.inputError,
          readOnly && questionControlStyles.inputReadOnly
        ]}
        aria-invalid={issues.length > 0 || undefined}
        aria-readonly={readOnly || undefined}
        editable={!readOnly}
        readOnly={readOnly || undefined}
        onBlur={buffered ? commitTyped : undefined}
        onEndEditing={buffered ? commitTyped : undefined}
        onSubmitEditing={buffered ? commitTyped : undefined}
        value={
          buffered && live !== undefined
            ? live
            : grouped && !multiline && value != null && value !== ""
            ? formatGrouped(String(value).replace(/[^\d.eE+-]/g, ""), locale)
            : value == null
              ? ""
              : String(value)
        }
        multiline={multiline}
        // The typed narrative must keep the keyboard's microphone (voice
        // typing, digitva-kkdb): never secure, never a restricted keyboard,
        // and autocorrect / sentence capitals left to the keyboard.
        secureTextEntry={masked && !multiline ? true : undefined}
        autoCapitalize={multiline ? "sentences" : undefined}
        keyboardType={numbersOnly ? "number-pad" : undefined}
        inputMode={numbersOnly ? "numeric" : multiline ? "text" : undefined}
        onChangeText={(text: string) => {
          if (readOnly) return;
          // `numbers` restricts what can be typed but still stores text.
          const next = numbersOnly ? asciiDigits(text).replace(/[^\d.+-]/g, "") : text;
          if (buffered) {
            if (live === undefined) typedOver.current = value;
            setTyped(next);
          }
          else onAnswer(next || undefined);
        }}
      />
    );
  }

  /**
   * A "-" or "+" button. A tap steps once; holding it repeats, faster the
   * longer it is held, until released or the caller disables it at a bound.
   */
  function StepButton({
    disabled,
    glyph,
    label,
    onStep,
    testID
  }: {
    disabled: boolean;
    glyph: string;
    label: string;
    onStep: () => void;
    testID: string;
  }) {
    const stepRef = useRef(onStep);
    stepRef.current = onStep;
    const disabledRef = useRef(disabled);
    disabledRef.current = disabled;
    const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
    const stop = () => {
      if (timer.current) clearTimeout(timer.current);
      timer.current = undefined;
    };
    useEffect(() => stop, []);
    const run = (delay: number) => {
      if (disabledRef.current) {
        stop();
        return;
      }
      stepRef.current();
      timer.current = setTimeout(() => run(Math.max(60, delay * 0.85)), delay);
    };
    return (
      <Pressable
        accessibilityLabel={label}
        accessibilityRole="button"
        delayLongPress={400}
        disabled={disabled}
        onLongPress={() => run(320)}
        onPress={() => stepRef.current()}
        onPressOut={stop}
        style={[questionControlStyles.stepButton, disabled && questionControlStyles.buttonDisabled]}
        testID={testID}
      >
        <PrimitiveText aria-hidden="true" style={questionControlStyles.stepGlyph}>
          {glyph}
        </PrimitiveText>
      </Pressable>
    );
  }

  /**
   * A numeric box sized to its expected digits, between "-" and "+" buttons
   * and followed by its unit. The buttons never go below the constraint's
   * minimum and stop at its maximum; typing is unrestricted, so a special
   * code such as 99 for "does not wish to disclose" still goes in.
   */
  function NumberField({
    bounds,
    decimal,
    issues,
    locale,
    messages,
    onBlur,
    onChangeText,
    onFocus,
    onStep,
    placeholder,
    question,
    stepSize,
    text,
    value
  }: {
    /** Bounds that are not in the constraint (a `range` question's start and end). */
    bounds?: { min?: number; max?: number };
    stepSize?: number;
    decimal: boolean;
    issues: ValidationIssue[];
    locale: string;
    messages: WhoVaUiMessages;
    onBlur?: () => void;
    onChangeText: (text: string) => void;
    onFocus?: () => void;
    onStep: (next: number) => void;
    placeholder?: string;
    question: InstrumentQuestion;
    text: string;
    value: AnswerValue | undefined;
  }) {
    const readOnly = question.readOnly;
    const { min, max } = bounds ?? constraintBounds(question);
    const current = typeof value === "number" ? value : undefined;
    const step = stepSize ?? (decimal ? 0.1 : 1);
    const canDecrease =
      !readOnly && (current === undefined ? min === undefined || false : min === undefined || current > min);
    const canIncrease = !readOnly && (current === undefined || max === undefined || current < max);
    const digits = Math.max(3, String(max ?? 999).length) + (decimal ? 2 : 0);
    const stepTo = (delta: number) => {
      const base = current ?? (min ?? 0) - (delta > 0 ? delta : 0);
      let next = Number((base + delta).toFixed(decimal ? 1 : 0));
      if (min !== undefined && next < min) next = min;
      if (max !== undefined && delta > 0 && base < max && next > max) next = max;
      onStep(next);
    };
    return (
      <View style={questionControlStyles.numberRow}>
        <StepButton
          disabled={!canDecrease}
          glyph="−"
          label={messages.decrease}
          onStep={() => stepTo(-step)}
          testID={`question-${question.name}-decrease`}
        />
        <TextInput
          accessibilityLabel={questionLabel(question, locale)}
          testID={`question-${question.name}`}
          style={[
            questionControlStyles.input,
            questionControlStyles.numberInput,
            { width: 24 + digits * 12 },
            issues.length > 0 && questionControlStyles.inputError,
            readOnly && questionControlStyles.inputReadOnly
          ]}
          aria-invalid={issues.length > 0 || undefined}
          aria-readonly={readOnly || undefined}
          autoCapitalize="none"
          autoCorrect={false}
          editable={!readOnly}
          inputMode={decimal ? "decimal" : "numeric"}
          keyboardType={decimal ? "decimal-pad" : "number-pad"}
          onBlur={onBlur}
          onChangeText={onChangeText}
          onFocus={onFocus}
          placeholder={placeholder}
          readOnly={readOnly || undefined}
          spellCheck={false}
          value={text}
        />
        <StepButton
          disabled={!canIncrease}
          glyph="+"
          label={messages.increase}
          onStep={() => stepTo(step)}
          testID={`question-${question.name}-increase`}
        />
        {numericUnit(question, messages) ? (
          <PrimitiveText style={questionControlStyles.unit} testID={`question-${question.name}-unit`}>
            {numericUnit(question, messages)}
          </PrimitiveText>
        ) : null}
      </View>
    );
  }

  function Integer({
    question,
    value,
    locale,
    messages = ENGLISH_UI_MESSAGES,
    issues,
    onAnswer
  }: WhoVaQuestionControlProps) {
    const readOnly = question.readOnly;
    const grouped = hasAppearance(question, "thousands-sep");
    const [focused, setFocused] = useState(false);
    return (
      <NumberField
        decimal={false}
        issues={issues}
        locale={locale}
        messages={messages}
        onBlur={() => setFocused(false)}
        onChangeText={(typed: string) => {
          if (readOnly) return;
          // Digits only, whatever keyboard or separator produced them.
          const raw = asciiDigits(typed).replace(/[^\d-]/g, "");
          if (raw === "") onAnswer(undefined);
          else if (/^-?\d+$/.test(raw)) onAnswer(Number(raw));
        }}
        onFocus={() => setFocused(true)}
        onStep={(next) => onAnswer(next)}
        question={question}
        text={
          value == null ? "" : grouped && !focused ? formatGrouped(value as number, locale) : String(value)
        }
        value={value}
      />
    );
  }

  function Decimal({
    question,
    value,
    locale,
    messages = ENGLISH_UI_MESSAGES,
    issues,
    onAnswer
  }: WhoVaQuestionControlProps) {
    const readOnly = question.readOnly;
    // Partial input has to survive keystrokes: "1." and "-" are not numbers
    // yet, so they are held as draft text and only committed once parseable.
    const [draft, setDraft] = useState<string>();
    const grouped = hasAppearance(question, "thousands-sep");
    const shown =
      draft ?? (value == null ? "" : grouped ? formatGrouped(value as number, locale) : String(value));
    return (
      <NumberField
        decimal
        issues={issues}
        locale={locale}
        messages={messages}
        onBlur={() => setDraft(undefined)}
        onChangeText={(typed: string) => {
          if (readOnly) return;
          const text = asciiDigits(typed);
          if (text === "") {
            setDraft(undefined);
            onAnswer(undefined);
            return;
          }
          const raw = grouped ? text.replace(/[^\d.eE+-]/g, "") : text;
          if (!/^-?\d*([.]\d*)?$/.test(raw)) return;
          setDraft(raw);
          const parsed = Number(raw);
          if (Number.isFinite(parsed) && /\d/.test(raw)) onAnswer(parsed);
        }}
        onStep={(next) => {
          setDraft(undefined);
          onAnswer(next);
        }}
        placeholder="0.0"
        question={question}
        text={shown}
        value={value}
      />
    );
  }

  function Time({ question, value, locale, issues, onAnswer }: WhoVaQuestionControlProps) {
    const readOnly = question.readOnly;
    return (
      <TextInput
        accessibilityLabel={questionLabel(question, locale)}
        testID={`question-${question.name}`}
        aria-invalid={issues.length > 0 || undefined}
        aria-readonly={readOnly || undefined}
        editable={!readOnly}
        readOnly={readOnly || undefined}
        // Web renders this as <input type="time">; native falls back to a
        // validated text entry in the same canonical HH:MM shape.
        {...({ type: "time", inputMode: "numeric" } as Record<string, unknown>)}
        style={[
          questionControlStyles.input,
          questionControlStyles.timeInput,
          issues.length > 0 && questionControlStyles.inputError,
          readOnly && questionControlStyles.inputReadOnly
        ]}
        placeholder="HH:MM"
        value={typeof value === "string" ? value : ""}
        onChangeText={(text: string) => {
          if (readOnly) return;
          if (text === "") onAnswer(undefined);
          else onAnswer(text);
        }}
      />
    );
  }

  function DateTime({ question, value, locale, issues, onAnswer }: WhoVaQuestionControlProps) {
    const readOnly = question.readOnly;
    return (
      <TextInput
        accessibilityLabel={questionLabel(question, locale)}
        testID={`question-${question.name}`}
        aria-invalid={issues.length > 0 || undefined}
        aria-readonly={readOnly || undefined}
        editable={!readOnly}
        readOnly={readOnly || undefined}
        {...({ type: "datetime-local" } as Record<string, unknown>)}
        style={[
          questionControlStyles.input,
          questionControlStyles.dateTimeInput,
          issues.length > 0 && questionControlStyles.inputError,
          readOnly && questionControlStyles.inputReadOnly
        ]}
        placeholder="YYYY-MM-DDTHH:MM"
        value={typeof value === "string" ? value : ""}
        onChangeText={(text: string) => {
          if (readOnly) return;
          if (text === "") onAnswer(undefined);
          else onAnswer(text);
        }}
      />
    );
  }

  function Barcode({
    question,
    value,
    data,
    locale,
    messages = ENGLISH_UI_MESSAGES,
    issues,
    platform: propPlatform,
    onAnswer
  }: WhoVaQuestionControlProps) {
    const services = propPlatform ?? primitives.platform;
    const readOnly = question.readOnly;
    const [busy, setBusy] = useState(false);
    return (
      <View>
        <TextInput
          accessibilityLabel={questionLabel(question, locale)}
          testID={`question-${question.name}`}
          style={[
            questionControlStyles.input,
            issues.length > 0 && questionControlStyles.inputError,
            readOnly && questionControlStyles.inputReadOnly
          ]}
          aria-invalid={issues.length > 0 || undefined}
          editable={!readOnly}
          readOnly={readOnly || undefined}
          value={typeof value === "string" ? value : ""}
          onChangeText={(text: string) => {
            if (!readOnly) onAnswer(text || undefined);
          }}
        />
        {services?.scanBarcode && !readOnly ? (
          <Pressable
            accessibilityRole="button"
            testID={`question-${question.name}-scan`}
            disabled={busy}
            onPress={async () => {
              setBusy(true);
              try {
                const scanned = await services.scanBarcode?.(question, data);
                if (scanned) onAnswer(scanned);
              } finally {
                setBusy(false);
              }
            }}
            style={[
              questionControlStyles.button,
              questionControlStyles.buttonSecondary,
              busy && questionControlStyles.buttonDisabled
            ]}
          >
            <PrimitiveText style={questionControlStyles.buttonTextSecondary}>
              {messages.scanBarcode}
            </PrimitiveText>
          </Pressable>
        ) : null}
      </View>
    );
  }

  function Range({
    question,
    value,
    locale,
    messages = ENGLISH_UI_MESSAGES,
    issues,
    onAnswer
  }: WhoVaQuestionControlProps) {
    const readOnly = question.readOnly;
    const { start, end, step } = rangeParameters(question);
    const fractional = !Number.isInteger(step);
    const hasIssues = issues.length > 0;

    // `picker` shows the range as a list of discrete options; `rating` shows
    // the same values as stars. Both need the enumerated values.
    const asPicker = hasAppearance(question, "picker");
    const asRating = hasAppearance(question, "rating");
    const values = useMemo(
      () => (asPicker || asRating ? rangeValues(question) : []),
      [asPicker, asRating, question]
    );

    if (asRating) {
      const selected = typeof value === "number" ? value : undefined;
      return (
        <View style={questionControlStyles.choiceRow}>
          {values.map((option) => {
            const filled = selected != null && option <= selected;
            return (
              <Pressable
                key={option}
                accessibilityRole="radio"
                accessibilityLabel={`${option}`}
                accessibilityState={{ selected: selected === option, disabled: readOnly }}
                disabled={readOnly}
                testID={`question-${question.name}-star-${option}`}
                style={[questionControlStyles.star, hasIssues && questionControlStyles.inputError]}
                onPress={() => {
                  if (!readOnly) onAnswer(option);
                }}
              >
                <PrimitiveText
                  style={filled ? questionControlStyles.starFilled : questionControlStyles.starEmpty}
                >
                  {filled ? "\u2605" : "\u2606"}
                </PrimitiveText>
              </Pressable>
            );
          })}
        </View>
      );
    }

    if (asPicker) {
      return (
        <View style={questionControlStyles.choiceRow}>
          {values.map((option) => {
            const selected = value === option;
            return (
              <Pressable
                key={option}
                accessibilityRole="radio"
                accessibilityState={{ selected, disabled: readOnly }}
                disabled={readOnly}
                testID={`question-${question.name}-choice-${option}`}
                style={[
                  questionControlStyles.choice,
                  questionControlStyles.choiceInline,
                  hasIssues && questionControlStyles.inputError,
                  selected && questionControlStyles.choiceSelected,
                  readOnly && questionControlStyles.inputReadOnly
                ]}
                onPress={() => {
                  if (!readOnly) onAnswer(option);
                }}
              >
                <PrimitiveText style={questionControlStyles.choiceText}>{option}</PrimitiveText>
              </Pressable>
            );
          })}
        </View>
      );
    }

    // No picker or rating: a numeric box with - / + buttons stepping by the
    // range's step and stopping at its ends, so the control is visible.
    return (
      <NumberField
        bounds={{ min: Math.min(start, end), max: Math.max(start, end) }}
        decimal={fractional}
        issues={issues}
        locale={locale}
        messages={messages}
        onChangeText={(text: string) => {
          if (readOnly) return;
          if (text === "") {
            onAnswer(undefined);
            return;
          }
          const pattern = fractional ? /^-?\d*([.]\d*)?$/ : /^-?\d+$/;
          if (!pattern.test(text)) return;
          const parsed = Number(text);
          if (Number.isFinite(parsed)) onAnswer(parsed);
        }}
        onStep={(next) => onAnswer(next)}
        question={question}
        stepSize={Math.abs(step)}
        text={value == null ? "" : String(value)}
        value={value}
      />
    );
  }

  function GeoPoint({
    question,
    value,
    data,
    locale,
    messages = ENGLISH_UI_MESSAGES,
    issues,
    platform: propPlatform,
    onAnswer
  }: WhoVaQuestionControlProps) {
    const services = propPlatform ?? primitives.platform;
    const readOnly = question.readOnly;
    const [busy, setBusy] = useState(false);
    const current = typeof value === "string" ? value : "";
    const [latitude, longitude] = current.split(/\s+/);
    return (
      <View>
        <PrimitiveText testID={`question-${question.name}-value`} style={questionControlStyles.hint}>
          {current ? `${latitude}, ${longitude}` : ""}
        </PrimitiveText>
        <TextInput
          accessibilityLabel={questionLabel(question, locale)}
          testID={`question-${question.name}`}
          style={[
            questionControlStyles.input,
            issues.length > 0 && questionControlStyles.inputError,
            readOnly && questionControlStyles.inputReadOnly
          ]}
          aria-invalid={issues.length > 0 || undefined}
          editable={!readOnly}
          readOnly={readOnly || undefined}
          placeholder="latitude longitude"
          value={current}
          onChangeText={(text: string) => {
            if (!readOnly) onAnswer(text || undefined);
          }}
        />
        {services?.captureLocation && !readOnly ? (
          <Pressable
            accessibilityRole="button"
            testID={`question-${question.name}-capture`}
            disabled={busy}
            onPress={async () => {
              setBusy(true);
              try {
                const captured = await services.captureLocation?.(question, data);
                if (captured) onAnswer(captured);
              } finally {
                setBusy(false);
              }
            }}
            style={[
              questionControlStyles.button,
              questionControlStyles.buttonSecondary,
              busy && questionControlStyles.buttonDisabled
            ]}
          >
            <PrimitiveText style={questionControlStyles.buttonTextSecondary}>
              {current ? messages.updateLocation : messages.getLocation}
            </PrimitiveText>
          </Pressable>
        ) : null}
      </View>
    );
  }

  /**
   * The text-entry state machine shared by the `month-year` and `year`
   * appearances: empty clears, a complete entry stores the canonical ISO date
   * and drops the draft, a partial entry keeps the draft and stores nothing.
   */
  function commitDateText(
    text: string,
    isComplete: (text: string) => boolean,
    toIso: (text: string) => string,
    updateDraft: (next: string | undefined) => void,
    onAnswer: (value: AnswerValue | undefined) => void
  ) {
    if (text === "") {
      updateDraft(undefined);
      onAnswer(undefined);
    } else if (isComplete(text)) {
      onAnswer(toIso(text));
      updateDraft(undefined);
    } else {
      updateDraft(text);
      onAnswer(undefined);
    }
  }

  function DateTextInput({
    question,
    label,
    hasIssues,
    ...rest
  }: {
    question: InstrumentQuestion;
    label: string;
    hasIssues: boolean;
    value: string;
    maxLength: number;
    placeholder: string;
    onChangeText: (text: string) => void;
    keyboardType?: string;
    type?: string;
  }) {
    const readOnly = question.readOnly;
    const { type, ...props } = rest;
    return (
      <TextInput
        accessibilityLabel={label}
        testID={`question-${question.name}`}
        style={[
          questionControlStyles.input,
          hasIssues && questionControlStyles.inputError,
          readOnly && questionControlStyles.inputReadOnly
        ]}
        aria-invalid={hasIssues || undefined}
        aria-readonly={readOnly || undefined}
        editable={!readOnly}
        readOnly={readOnly || undefined}
        {...(type ? ({ type } as Record<string, unknown>) : {})}
        {...props}
      />
    );
  }

  function DateSelector({
    appearance,
    data,
    hasIssues,
    label,
    locale,
    messages,
    onAnswer,
    onDraftIssue,
    question,
    readOnly,
    value
  }: {
    appearance: "month-year" | "year";
    data: SubmissionData;
    hasIssues: boolean;
    label: string;
    locale: string;
    messages: WhoVaUiMessages;
    onAnswer: (value: AnswerValue | undefined) => void;
    onDraftIssue: (draft: string | undefined, issue?: ValidationIssue) => void;
    question: InstrumentQuestion;
    readOnly: boolean | undefined;
    value: string | undefined;
  }) {
    const SelectControl = PartialSelect as React.ElementType;
    const fromValue = (iso: string | undefined) => {
      const match = iso ? /^(\d{4})-(\d{2})-01$/.exec(iso) : null;
      return match ? { month: match[2] ?? "", year: match[1] ?? "" } : { month: "", year: "" };
    };
    const [parts, setParts] = useState(() => fromValue(value));
    const [shownFor, setShownFor] = useState(value);
    if (shownFor !== value) {
      setShownFor(value);
      if (value !== undefined || parts.month || parts.year) setParts(fromValue(value));
    }
    const months = useMemo(
      () =>
        localizedMonthNames(locale).map((name, index) => ({
          value: String(index + 1).padStart(2, "0"),
          label: name
        })),
      [locale]
    );
    const { min, max } = dateBounds(question);
    const thisYear = new globalThis.Date().getFullYear();
    const minYear = min ? Number(min.slice(0, 4)) : thisYear - 151;
    const maxYear = max ? Number(max.slice(0, 4)) : thisYear;
    const years = useMemo(
      () => Array.from({ length: Math.max(0, maxYear - minYear + 1) }, (_, index) => String(maxYear - index)),
      [maxYear, minYear]
    );
    const boundedMonths = useMemo(() => {
      if (appearance !== "month-year" || !parts.year) return months;
      return months.filter(({ value: month }) => {
        const candidate = `${parts.year}-${month}-01`;
        const lower = min ? `${min.slice(0, 7)}-01` : undefined;
        const upper = max ? `${max.slice(0, 7)}-01` : undefined;
        return (!lower || candidate >= lower) && (!upper || candidate <= upper);
      });
    }, [appearance, max, min, months, parts.year]);
    const monthOptions = boundedMonths;
    const commit = (next: { month: string; year: string }) => {
      const previousParts = parts;
      const previousShownFor = shownFor;
      setParts(next);
      const complete =
        /^\d{4}$/.test(next.year) && (appearance === "year" || /^(0[1-9]|1[0-2])$/.test(next.month));
      if (complete) {
        const iso = `${next.year}-${appearance === "year" ? "01" : next.month}-01`;
        const issue = validateAnswer(question, iso, data, locale, messages)[0];
        const lower = min ? `${min.slice(0, 7)}-01` : undefined;
        const upper = max ? `${max.slice(0, 7)}-01` : undefined;
        const outsideStaticBounds =
          (lower !== undefined && iso < lower) || (upper !== undefined && iso > upper);
        if (issue || outsideStaticBounds) {
          const yearChanged = appearance === "month-year" && next.year !== previousParts.year;
          if (yearChanged && outsideStaticBounds) {
            setParts({ month: "", year: next.year });
            // Keep the controlled answer as the synchronization anchor while
            // the user reselects the now-invalid month.
            setShownFor(value);
          } else {
            setParts(previousParts);
            setShownFor(previousShownFor);
          }
          onDraftIssue(
            undefined,
            issue ?? {
              question: question.name,
              code: "constraint",
              message: messages.invalidConstraint(label)
            }
          );
          return;
        }
        onAnswer(iso);
        setParts(next);
        setShownFor(iso);
        onDraftIssue(undefined);
      } else {
        onAnswer(undefined);
        setParts(next);
        setShownFor(undefined);
        onDraftIssue(undefined);
      }
    };
    const partStyle = [questionControlStyles.input, questionControlStyles.datePart];
    return (
      <View>
        <View
          accessibilityRole="none"
          role="group"
          style={[
            questionControlStyles.dateGroup,
            hasIssues && questionControlStyles.inputError,
            readOnly && questionControlStyles.inputReadOnly
          ]}
        >
          {appearance === "month-year" ? (
            <SelectControl
              accessibilityLabel={messages.month}
              disabled={readOnly}
              emptyOptionLabel={messages.selectDate}
              onValueChange={(month: string) => {
                if (!readOnly) commit({ ...parts, month });
              }}
              options={monthOptions}
              style={[...partStyle, questionControlStyles.datePartMonth]}
              testID={`question-${question.name}-month`}
              value={parts.month}
            />
          ) : null}
          <SelectControl
            accessibilityLabel={messages.year}
            disabled={readOnly}
            emptyOptionLabel={messages.selectDate}
            onValueChange={(year: string) => {
              if (!readOnly) commit({ ...parts, year });
            }}
            options={years.map((year) => ({ value: year, label: year }))}
            style={[...partStyle, questionControlStyles.datePartYear]}
            testID={`question-${question.name}-year`}
            value={parts.year}
          />
        </View>
        <PrimitiveText
          accessibilityLabel={label}
          style={questionControlStyles.formatHint}
          testID={`question-${question.name}-format`}
        >
          {appearance === "month-year" ? `${messages.month} / ${messages.year}` : messages.year}
        </PrimitiveText>
      </View>
    );
  }

  /**
   * A year-only date on a phone: [ - ] 2021 [ + ] with the year a bordered
   * field that opens a list of years (newest first, within the constraint's
   * bounds). The buttons stop at the bounds and repeat while held. Stored as
   * `YYYY-01-01`, as the `year` appearance always is.
   */
  function YearStepper({
    data,
    hasIssues,
    label,
    locale,
    messages,
    onAnswer,
    onDraftIssue,
    question,
    readOnly,
    value
  }: {
    data: SubmissionData;
    hasIssues: boolean;
    label: string;
    locale: string;
    messages: WhoVaUiMessages;
    onAnswer: (value: AnswerValue | undefined) => void;
    onDraftIssue: (draft: string | undefined, issue?: ValidationIssue) => void;
    question: InstrumentQuestion;
    readOnly: boolean | undefined;
    value: string | undefined;
  }) {
    const SelectControl = PartialSelect as React.ElementType;
    const { min, max } = dateBounds(question);
    const thisYear = new globalThis.Date().getFullYear();
    const minYear = min ? Number(min.slice(0, 4)) : thisYear - 151;
    const maxYear = max ? Number(max.slice(0, 4)) : thisYear;
    const match = value ? /^(\d{4})-\d{2}-\d{2}$/.exec(value) : null;
    const current = match ? Number(match[1]) : undefined;
    const years = useMemo(
      () => Array.from({ length: Math.max(0, maxYear - minYear + 1) }, (_, index) => String(maxYear - index)),
      [maxYear, minYear]
    );
    const commit = (year: number) => {
      const iso = `${String(year).padStart(4, "0")}-01-01`;
      const issue = validateAnswer(question, iso, data, locale, messages)[0];
      if (issue) {
        onDraftIssue(undefined, issue);
        return;
      }
      onAnswer(iso);
      onDraftIssue(undefined);
    };
    // From empty either button starts at the newest year.
    const stepTo = (delta: number) =>
      commit(current === undefined ? maxYear : Math.min(maxYear, Math.max(minYear, current + delta)));
    const canDecrease = !readOnly && (current === undefined || current > minYear);
    const canIncrease = !readOnly && (current === undefined || current < maxYear);
    return (
      <View
        accessibilityRole="none"
        role="group"
        aria-label={label}
        style={[questionControlStyles.numberRow, { flexWrap: "nowrap" }]}
      >
        <StepButton
          disabled={!canDecrease}
          glyph="−"
          label={messages.decrease}
          onStep={() => stepTo(-1)}
          testID={`question-${question.name}-year-decrease`}
        />
        <SelectControl
          accessibilityLabel={`${label}: ${messages.year}`}
          disabled={readOnly}
          emptyOptionLabel={messages.selectYear}
          onValueChange={(year: string) => {
            if (!readOnly && /^\d{4}$/.test(year)) commit(Number(year));
          }}
          options={years.map((year) => ({ value: year, label: year }))}
          style={[
            questionControlStyles.input,
            hasIssues && questionControlStyles.inputError,
            readOnly && questionControlStyles.inputReadOnly,
            { flexGrow: 1, flexShrink: 1, minWidth: 120 }
          ]}
          testID={`question-${question.name}-year`}
          typedEntry
          value={current === undefined ? "" : String(current)}
        />
        <StepButton
          disabled={!canIncrease}
          glyph="+"
          label={messages.increase}
          onStep={() => stepTo(1)}
          testID={`question-${question.name}-year-increase`}
        />
      </View>
    );
  }

  function DatePickerButton({
    question,
    value,
    data,
    locale,
    messages,
    label,
    hasIssues,
    pickDate,
    onAnswer
  }: {
    question: InstrumentQuestion;
    value: AnswerValue | undefined;
    data: SubmissionData;
    locale: string;
    messages: WhoVaUiMessages;
    label: string;
    hasIssues: boolean;
    pickDate: NonNullable<WhoVaPlatformServices["pickDate"]>;
    onAnswer: (value: AnswerValue | undefined) => void;
  }) {
    const [busy, setBusy] = useState(false);
    // Petrol (a host theme): the input-sized row with a calendar glyph in the host's secondary text colour.
    const theme = useFormTheme();
    const readOnly = question.readOnly;
    const shownText = busy
      ? messages.openingCalendar
      : value == null
        ? messages.selectDate
        : formatDdMmmYyyy(String(value), locale);
    return (
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={label}
        accessibilityState={{ disabled: busy }}
        testID={`question-${question.name}`}
        style={[
          questionControlStyles.input,
          theme && questionControlStyles.dateButton,
          hasIssues && questionControlStyles.inputError,
          (readOnly || busy) && questionControlStyles.buttonDisabled
        ]}
        disabled={readOnly || busy}
        onPress={async () => {
          if (readOnly) return;
          setBusy(true);
          try {
            const selected = await pickDate(question, data, typeof value === "string" ? value : undefined);
            if (selected !== undefined) onAnswer(selected);
          } finally {
            setBusy(false);
          }
        }}
      >
        {theme ? (
          <>
            {/* The placeholder is input-sized text, centred like any field's entry (not the small hint style). */}
            <PrimitiveText
              style={[questionControlStyles.dateButtonText, value == null && questionControlStyles.dateButtonPlaceholder]}
            >
              {shownText}
            </PrimitiveText>
            <Glyph icon="calendar" color={theme.textMuted} size={22} />
          </>
        ) : (
          <PrimitiveText style={value == null ? questionControlStyles.hint : questionControlStyles.choiceText}>
            {shownText}
          </PrimitiveText>
        )}
      </Pressable>
    );
  }

  function Date({
    question,
    value,
    data,
    locale,
    messages = ENGLISH_UI_MESSAGES,
    issues,
    platform,
    onAnswer,
    onDraftIssue
  }: WhoVaQuestionControlProps) {
    const [draft, setDraft] = useState<string>();
    const label = questionLabel(question, locale);
    const hasIssues = issues.length > 0;
    const readOnly = question.readOnly;
    const services = { ...primitives.platform, ...platform };

    useEffect(() => () => onDraftIssue?.(question.name, undefined), [onDraftIssue, question.name]);

    const updateDraft = (next: string | undefined, issue?: ValidationIssue) => {
      setDraft(next);
      onDraftIssue?.(question.name, issue ?? incompleteDateIssue(question, next, locale, messages));
    };

    if (hasAppearance(question, "month-year") && PartialSelect) {
      return (
        <DateSelector
          appearance="month-year"
          data={data}
          hasIssues={hasIssues}
          label={label}
          locale={locale}
          messages={messages}
          onAnswer={onAnswer}
          onDraftIssue={updateDraft}
          question={question}
          readOnly={readOnly}
          value={typeof value === "string" ? value : undefined}
        />
      );
    }

    if (hasAppearance(question, "month-year")) {
      return (
        <DateTextInput
          question={question}
          label={label}
          hasIssues={hasIssues}
          type="month"
          value={draft ?? (typeof value === "string" ? value.slice(0, 7) : "")}
          maxLength={7}
          placeholder="YYYY-MM"
          onChangeText={(text: string) => {
            if (readOnly || !/^[\d-]*$/.test(text)) return;
            // Canonical storage stays a full ISO date, as `year` does.
            commitDateText(
              text,
              (t) => /^\d{4}-(0[1-9]|1[0-2])$/.test(t),
              (t) => `${t}-01`,
              updateDraft,
              onAnswer
            );
          }}
        />
      );
    }

    if (hasAppearance(question, "year") && PartialSelect && !Select) {
      return (
        <YearStepper
          data={data}
          hasIssues={hasIssues}
          label={label}
          locale={locale}
          messages={messages}
          onDraftIssue={updateDraft}
          onAnswer={onAnswer}
          question={question}
          readOnly={readOnly}
          value={typeof value === "string" ? value : undefined}
        />
      );
    }

    if (hasAppearance(question, "year") && PartialSelect) {
      return (
        <DateSelector
          appearance="year"
          data={data}
          hasIssues={hasIssues}
          label={label}
          locale={locale}
          messages={messages}
          onAnswer={onAnswer}
          onDraftIssue={updateDraft}
          question={question}
          readOnly={readOnly}
          value={typeof value === "string" ? value : undefined}
        />
      );
    }

    if (hasAppearance(question, "year")) {
      return (
        <DateTextInput
          question={question}
          label={label}
          hasIssues={hasIssues}
          keyboardType="number-pad"
          value={draft ?? (typeof value === "string" ? value.slice(0, 4) : "")}
          maxLength={4}
          placeholder="YYYY"
          onChangeText={(text: string) => {
            if (readOnly || !/^\d*$/.test(text)) return;
            commitDateText(
              text,
              (t) => t.length === 4,
              (t) => `${t}-01-01`,
              updateDraft,
              onAnswer
            );
          }}
        />
      );
    }

    // `no-calendar` asks for a spinner-style picker rather than no picker at
    // all, and the host owns the picker. It receives `question`, so it reads
    // the appearance itself; suppressing pickDate here would remove the picker
    // the interviewer is meant to get.
    if (services?.pickDate) {
      return (
        <DatePickerButton
          question={question}
          value={value}
          data={data}
          locale={locale}
          messages={messages}
          label={label}
          hasIssues={hasIssues}
          pickDate={services.pickDate}
          onAnswer={onAnswer}
        />
      );
    }

    return (
      <DateParts
        hasIssues={hasIssues}
        label={label}
        locale={locale}
        messages={messages}
        onAnswer={onAnswer}
        onDraftIssue={updateDraft}
        question={question}
        readOnly={readOnly}
        value={typeof value === "string" ? value : undefined}
      />
    );
  }

  /**
   * A date as DD-MMM-YYYY: day and year boxes with a month select between
   * them, styled as one field, and a calendar button that opens the platform
   * picker. The stored value stays ISO; a
   * partial entry stores nothing, an impossible date (31-Feb) shows an error
   * and stores nothing. Without a Select primitive the month is a numeric box.
   */
  function DateParts({
    hasIssues,
    label,
    locale,
    messages,
    onAnswer,
    onDraftIssue,
    question,
    readOnly,
    value
  }: {
    hasIssues: boolean;
    label: string;
    locale: string;
    messages: WhoVaUiMessages;
    onAnswer: (value: AnswerValue | undefined) => void;
    onDraftIssue: (draft: string | undefined, issue?: ValidationIssue) => void;
    question: InstrumentQuestion;
    readOnly: boolean | undefined;
    value: string | undefined;
  }) {
    const fromValue = (iso: string | undefined) => {
      const match = iso ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso) : null;
      return match
        ? { day: match[3] ?? "", month: match[2] ?? "", year: match[1] ?? "" }
        : { day: "", month: "", year: "" };
    };
    const [parts, setParts] = useState(() => fromValue(value));
    const [shownFor, setShownFor] = useState(value);
    // A value set from outside (a draft, the picker) refreshes the parts.
    if (shownFor !== value) {
      setShownFor(value);
      if (value !== undefined || isoFromParts(parts.day, parts.month, parts.year)) setParts(fromValue(value));
    }
    const monthRef = useRef<unknown>(null);
    const yearRef = useRef<unknown>(null);
    const pickerRef = useRef<unknown>(null);
    const focus = (node: unknown) => (node as { focus?: () => void } | null)?.focus?.();
    const months = useMemo(
      () =>
        localizedMonthNames(locale).map((name, index) => ({
          value: String(index + 1).padStart(2, "0"),
          label: name
        })),
      [locale]
    );
    const { min, max } = dateBounds(question);
    const hintId = `question-${question.name}-format`;
    const labelId = `question-${question.name}-label`;

    const commit = (next: { day: string; month: string; year: string }) => {
      setParts(next);
      const complete = next.day && next.month && next.year.length === 4;
      const iso = isoFromParts(next.day, next.month, next.year);
      if (iso) {
        onDraftIssue(undefined);
        onAnswer(iso);
        setShownFor(iso);
      } else {
        onAnswer(undefined);
        setShownFor(undefined);
        onDraftIssue(
          complete ? "invalid" : undefined,
          complete
            ? {
                question: question.name,
                code: "type",
                message: messages.invalidDate("DD-MMM-YYYY", formatDdMmmYyyy("1986-07-16", locale))
              }
            : undefined
        );
      }
    };
    const partStyle = [questionControlStyles.input, questionControlStyles.datePart];
    return (
      <View>
        <View
          accessibilityRole="none"
          aria-describedby={hintId}
          aria-labelledby={labelId}
          role="group"
          style={questionControlStyles.dateGroup}
        >
          <PrimitiveText nativeID={labelId} style={questionControlStyles.hidden}>
            {label}
          </PrimitiveText>
          <View
            style={[
              questionControlStyles.dateField,
              hasIssues && questionControlStyles.inputError,
              readOnly && questionControlStyles.inputReadOnly
            ]}
          >
            <TextInput
              accessibilityLabel={messages.day}
              aria-describedby={hintId}
              aria-invalid={hasIssues || undefined}
              autoCapitalize="none"
              autoCorrect={false}
              editable={!readOnly}
              inputMode="numeric"
              keyboardType="number-pad"
              maxLength={2}
              onChangeText={(text: string) => {
                if (readOnly) return;
                const day = asciiDigits(text).replace(/\D/g, "").slice(0, 2);
                commit({ ...parts, day });
                if (day.length === 2) focus(monthRef.current);
              }}
              placeholder="DD"
              readOnly={readOnly || undefined}
              style={[...partStyle, questionControlStyles.datePartDay]}
              testID={`question-${question.name}-day`}
              value={parts.day}
            />
            <PrimitiveText aria-hidden="true" style={questionControlStyles.dateSeparator}>
              -
            </PrimitiveText>
            {Select ? (
              <Select
                ref={monthRef}
                accessibilityLabel={messages.month}
                onValueChange={(month: string) => {
                  if (readOnly) return;
                  commit({ ...parts, month });
                  if (month) focus(yearRef.current);
                }}
                options={months}
                style={[...partStyle, questionControlStyles.datePartMonth]}
                testID={`question-${question.name}-month`}
                value={parts.month}
              />
            ) : (
              <TextInput
                ref={monthRef}
                accessibilityLabel={messages.month}
                editable={!readOnly}
                inputMode="numeric"
                keyboardType="number-pad"
                maxLength={2}
                onChangeText={(text: string) => {
                  if (readOnly) return;
                  const month = asciiDigits(text).replace(/\D/g, "").slice(0, 2);
                  commit({ ...parts, month });
                  if (month.length === 2) focus(yearRef.current);
                }}
                placeholder="MM"
                readOnly={readOnly || undefined}
                style={[...partStyle, questionControlStyles.datePartDay]}
                testID={`question-${question.name}-month`}
                value={parts.month}
              />
            )}
            <PrimitiveText aria-hidden="true" style={questionControlStyles.dateSeparator}>
              -
            </PrimitiveText>
            <TextInput
              ref={yearRef}
              accessibilityLabel={messages.year}
              aria-describedby={hintId}
              aria-invalid={hasIssues || undefined}
              autoCapitalize="none"
              autoCorrect={false}
              editable={!readOnly}
              inputMode="numeric"
              keyboardType="number-pad"
              maxLength={4}
              onChangeText={(text: string) => {
                if (readOnly) return;
                commit({ ...parts, year: asciiDigits(text).replace(/\D/g, "").slice(0, 4) });
              }}
              placeholder="YYYY"
              readOnly={readOnly || undefined}
              style={[...partStyle, questionControlStyles.datePartYear]}
              testID={`question-${question.name}-year`}
              value={parts.year}
            />
          </View>
          {DateInput ? (
            <>
              <DateInput
                ref={pickerRef}
                accessibilityLabel={label}
                locale={locale}
                readOnly={readOnly || undefined}
                aria-hidden="true"
                tabIndex={-1}
                testID={`question-${question.name}`}
                style={questionControlStyles.hiddenPicker}
                {...(min ? { min } : {})}
                {...(max ? { max } : {})}
                value={value ?? ""}
                onChangeText={(text: string) => {
                  if (readOnly) return;
                  commit(fromValue(text || undefined));
                }}
              />
              <Pressable
                accessibilityLabel={messages.openCalendar}
                accessibilityRole="button"
                disabled={readOnly}
                onPress={() => {
                  const picker = pickerRef.current as {
                    showPicker?: () => void;
                    focus?: () => void;
                    click?: () => void;
                  } | null;
                  try {
                    picker?.showPicker?.();
                  } catch {
                    picker?.focus?.();
                  }
                }}
                style={[questionControlStyles.stepButton, readOnly && questionControlStyles.buttonDisabled]}
                testID={`question-${question.name}-calendar`}
              >
                <PrimitiveText aria-hidden="true" style={questionControlStyles.stepGlyph}>
                  {CALENDAR_ICON}
                </PrimitiveText>
              </Pressable>
            </>
          ) : null}
        </View>
        <PrimitiveText nativeID={hintId} style={questionControlStyles.formatHint} testID={hintId}>
          {messages.dateFormatHint}
        </PrimitiveText>
      </View>
    );
  }

  function SearchableSingleChoice({ question, value, locale, issues, onAnswer }: WhoVaQuestionControlProps) {
    const readOnly = question.readOnly;
    const [query, setQuery] = useState("");
    const searchText = query.trim().toLocaleLowerCase(locale);
    const choices = (question.choices ?? []).filter((choice) => {
      if (!searchText) return true;
      const label = languageChoiceLabel(choice).toLocaleLowerCase(locale);
      return choice.value.toLocaleLowerCase(locale).includes(searchText) || label.includes(searchText);
    });
    return (
      <>
        <TextInput
          accessibilityLabel={questionLabel(question, locale)}
          accessibilityRole="combobox"
          testID={`question-${question.name}`}
          style={[
            questionControlStyles.input,
            issues.length > 0 && questionControlStyles.inputError,
            readOnly && questionControlStyles.inputReadOnly
          ]}
          aria-invalid={issues.length > 0 || undefined}
          aria-readonly={readOnly || undefined}
          editable={!readOnly}
          readOnly={readOnly || undefined}
          value={query}
          placeholder="Search language"
          onChangeText={(text: string) => {
            if (!readOnly) setQuery(text);
          }}
        />
        <View style={questionControlStyles.dropdownList}>
          {choices.map((choice) => {
            const selected = value === choice.value;
            return (
              <Pressable
                key={choice.value}
                role="option"
                accessibilityState={{ selected, disabled: readOnly }}
                disabled={readOnly}
                testID={`question-${question.name}-choice-${choice.value}`}
                style={[questionControlStyles.choice, selected && questionControlStyles.choiceSelected]}
                onPress={() => {
                  if (readOnly) return;
                  onAnswer(choice.value);
                  setQuery("");
                }}
              >
                <ChoiceIndicator kind="radio" selected={selected} />
                <PrimitiveText style={[questionControlStyles.choiceText, questionControlStyles.choiceTextFill]}>
                  {languageChoiceLabel(choice)}
                </PrimitiveText>
              </Pressable>
            );
          })}
        </View>
      </>
    );
  }

  /**
   * Shared presentation for the select appearances: `search` filters the list,
   * `columns`/`columns-n`/`columns-pack` and `likert` lay choices along a row,
   * and `no-buttons` drops the control chrome so the cell itself is the target.
   * Unknown appearance tokens fall through to the default vertical list, which
   * is what ODK clients do with an appearance they do not implement.
   */
  function useChoicePresentation(question: InstrumentQuestion, locale: string, choiceColumns?: number) {
    const [query, setQuery] = useState("");
    const [width, setWidth] = useState(0);
    const layout = columnLayout(question);
    const likert = hasAppearance(question, "likert");
    const bare = hasAppearance(question, "no-buttons");
    const searchable = hasAppearance(question, "search");
    const petrol = useFormTheme() !== undefined;

    const choices = useMemo(() => {
      const all = question.choices ?? [];
      const needle = query.trim().toLowerCase();
      if (!searchable || !needle) return all;
      return all.filter((choice) =>
        localized(choice.label, locale, choice.value).toLowerCase().includes(needle)
      );
    }, [question, locale, query, searchable]);

    // A short list (at most six choices, every label at most 24 characters
    // in the shown locale) becomes a grid of equal cells: as many columns as
    // choices when the host allows and each cell keeps 96px, else two, else
    // one. Row-major, so reading and tab order stay the choice order.
    const gridCandidate =
      !layout &&
      !likert &&
      !searchable &&
      (choiceColumns ?? 1) > 1 &&
      choices.length > 1 &&
      choices.length <= 6 &&
      choices.every((choice) => [...localized(choice.label, locale, choice.value)].length <= 24);
    let columns = 1;
    if (gridCandidate && width > 0) {
      // A cell must hold its longest word on one line beside the indicator:
      // 58px of chrome (padding, indicator, gap) plus ~9px a character.
      const longestWord = Math.max(
        ...choices.map((choice) =>
          Math.max(
            ...localized(choice.label, locale, choice.value)
              .split(/\s+/)
              .map((word) => [...word].length)
          )
        )
      );
      const minCell = Math.max(96, 58 + 9 * longestWord);
      columns = Math.min(choices.length, choiceColumns ?? 1);
      while (columns > 1 && (width - 8 * (columns - 1)) / columns < minCell) columns -= 1;
    }
    const grid =
      columns > 1 ? { columns, cellWidth: Math.floor((width - 8 * (columns - 1)) / columns) } : undefined;
    const inline = Boolean(layout) || likert;
    const cellStyle: Record<string, unknown>[] = [];
    if (grid) {
      cellStyle.push(questionControlStyles.choiceCell, { width: grid.cellWidth });
    } else if (likert) {
      cellStyle.push(questionControlStyles.choiceLikert);
    } else if (layout) {
      cellStyle.push(questionControlStyles.choiceInline);
      if (layout.mode === "fixed") {
        const share = `${100 / layout.count}%`;
        cellStyle.push({ flexBasis: share, maxWidth: share, flexGrow: 0 });
      } else if (layout.mode === "responsive") {
        // No measurement here: a comfortable minimum width lets the row hold
        // more columns on a wide screen and fewer on a narrow one.
        cellStyle.push({ flexBasis: 150, flexGrow: 1 });
      } else {
        cellStyle.push(questionControlStyles.choicePacked);
      }
    }
    // A one-column list: under a host theme (Petrol) the rows sit edge to edge in one grouped card (see `wrap`).
    const listed = !grid && !inline;
    if (listed) cellStyle.push(questionControlStyles.choiceGrouped);
    if (bare) cellStyle.push(questionControlStyles.choiceBare);
    // Inline cells size to their label, so only list and grid labels fill the row.
    const textStyle = inline
      ? questionControlStyles.choiceText
      : [questionControlStyles.choiceText, questionControlStyles.choiceTextFill];

    const searchNode = searchable ? (
      <TextInput
        accessibilityLabel={`${questionLabel(question, locale)} search`}
        testID={`question-${question.name}-search`}
        style={[questionControlStyles.input, questionControlStyles.searchInput]}
        value={query}
        onChangeText={setQuery}
      />
    ) : null;

    // The measuring wrapper exists whenever a grid is possible, so the
    // first layout can decide the column count.
    const group = (cells: React.ReactNode[]) => (
      <View style={questionControlStyles.choiceGroup} testID={`question-${question.name}-choice-group`}>
        {cells.flatMap((cell, index) =>
          index ? [<View key={`separator-${index}`} style={questionControlStyles.choiceSeparator} />, cell] : [cell]
        )}
      </View>
    );
    const wrap = (cells: React.ReactNode[]) =>
      gridCandidate ? (
        <View
          onLayout={(event: { nativeEvent: { layout: { width: number } } }) =>
            setWidth(event.nativeEvent.layout.width)
          }
          style={grid ? questionControlStyles.choiceGrid : undefined}
          testID={`question-${question.name}-choices`}
          {...(grid ? { "data-columns": grid.columns } : {})}
        >
          {petrol && listed && cells.length ? group(cells) : cells}
        </View>
      ) : inline ? (
        <View style={questionControlStyles.choiceRow}>{cells}</View>
      ) : petrol && cells.length ? (
        group(cells)
      ) : (
        cells
      );

    return { choices, cellStyle, inline, searchNode, textStyle, wrap };
  }

  function SingleChoice(props: WhoVaQuestionControlProps) {
    const { question, value, locale, issues, onAnswer } = props;
    const { choices, cellStyle, searchNode, textStyle, wrap } = useChoicePresentation(
      question,
      locale,
      props.choiceColumns
    );
    if (question.name === "language") return <SearchableSingleChoice {...props} />;
    const hasIssues = issues.length > 0;
    const readOnly = question.readOnly;
    const cells = choices.map((choice) => {
      const selected = value === choice.value;
      return (
        <Pressable
          key={choice.value}
          accessibilityRole="radio"
          accessibilityState={{ selected, disabled: readOnly }}
          aria-invalid={hasIssues || undefined}
          disabled={readOnly}
          testID={`question-${question.name}-choice-${choice.value}`}
          style={[
            questionControlStyles.choice,
            ...cellStyle,
            hasIssues && questionControlStyles.inputError,
            selected && questionControlStyles.choiceSelected,
            readOnly && questionControlStyles.inputReadOnly
          ]}
          onPress={() => {
            if (!readOnly) onAnswer(choice.value);
          }}
        >
          <ChoiceIndicator kind="radio" selected={selected} />
          <PrimitiveText style={[textStyle, selected && questionControlStyles.choiceTextSelected]}>
            <ChoiceLabel choice={choice} locale={locale} showEnglish={props.showEnglish} />
          </PrimitiveText>
        </Pressable>
      );
    });
    return (
      <>
        {searchNode}
        {wrap(cells)}
      </>
    );
  }

  function MultipleChoice(props: WhoVaQuestionControlProps) {
    const { question, value, locale, issues, onAnswer } = props;
    const selectedValues = Array.isArray(value) ? value : EMPTY_SELECTED_VALUES;
    const selectedSet = useMemo(() => new Set(selectedValues), [selectedValues]);
    const hasIssues = issues.length > 0;
    const readOnly = question.readOnly;
    const { choices, cellStyle, searchNode, textStyle, wrap } = useChoicePresentation(
      question,
      locale,
      props.choiceColumns
    );
    const cells = choices.map((choice) => {
      const selected = selectedSet.has(choice.value);
      return (
        <Pressable
          key={choice.value}
          accessibilityRole="checkbox"
          accessibilityState={{ checked: selected, disabled: readOnly }}
          aria-invalid={hasIssues || undefined}
          disabled={readOnly}
          testID={`question-${question.name}-choice-${choice.value}`}
          style={[
            questionControlStyles.choice,
            ...cellStyle,
            hasIssues && questionControlStyles.inputError,
            selected && questionControlStyles.choiceSelected,
            readOnly && questionControlStyles.inputReadOnly
          ]}
          onPress={() => {
            if (readOnly) return;
            onAnswer(
              selected
                ? selectedValues.filter((item) => item !== choice.value)
                : [...selectedValues, choice.value]
            );
          }}
        >
          <ChoiceIndicator kind="checkbox" selected={selected} />
          <PrimitiveText style={[textStyle, selected && questionControlStyles.choiceTextSelected]}>
            <ChoiceLabel choice={choice} locale={locale} showEnglish={props.showEnglish} />
          </PrimitiveText>
        </Pressable>
      );
    });
    return (
      <>
        {searchNode}
        {wrap(cells)}
      </>
    );
  }

  function Confirm({
    question,
    value,
    messages = ENGLISH_UI_MESSAGES,
    issues,
    onAnswer
  }: WhoVaQuestionControlProps) {
    const hasIssues = issues.length > 0;
    const readOnly = question.readOnly;
    return (
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ disabled: readOnly }}
        aria-invalid={hasIssues || undefined}
        disabled={readOnly}
        testID={`question-${question.name}`}
        style={[
          questionControlStyles.button,
          hasIssues && questionControlStyles.buttonError,
          value === true && questionControlStyles.choiceSelected,
          readOnly && questionControlStyles.buttonDisabled
        ]}
        onPress={() => {
          if (!readOnly) onAnswer(true);
        }}
      >
        <PrimitiveText style={questionControlStyles.buttonText}>
          {value === true ? messages.confirmed : messages.confirm}
        </PrimitiveText>
      </Pressable>
    );
  }

  function storedAttachmentReference(value: AnswerValue | undefined): AttachmentReference | undefined {
    const reference = attachmentReference(value);
    if (reference || typeof value !== "string" || !value.startsWith("who-va-attachment:")) return reference;
    const id = value.slice("who-va-attachment:".length);
    return id ? { uri: value, id } : undefined;
  }

  /** Resolve a saved audio attachment without ever handing the opaque ref to the player. */
  function useAudioPreviewUri(
    value: AnswerValue | undefined,
    services: WhoVaPlatformServices,
    loadFailedMessage: string,
    onLoadError: (message: string | undefined) => void
  ) {
    const attachmentUri = attachmentDetails(value).uri;
    const [previewUri, setPreviewUri] = useState<string | undefined>();
    const [loading, setLoading] = useState(false);
    const resolveAttachmentUri = services.resolveAttachmentUri;
    const releaseAttachmentUri = services.releaseAttachmentUri;

    useEffect(() => {
      let active = true;
      let resolvedUri: string | undefined;
      const attachmentValue = storedAttachmentReference(value);
      if (!attachmentUri) {
        setPreviewUri(undefined);
        setLoading(false);
        return () => {
          active = false;
        };
      }
      if (!attachmentUri.startsWith("who-va-attachment:")) {
        setPreviewUri(attachmentUri);
        setLoading(false);
        return () => {
          active = false;
        };
      }
      if (!resolveAttachmentUri || !attachmentValue) {
        setPreviewUri(undefined);
        setLoading(false);
        onLoadError(loadFailedMessage);
        return () => {
          active = false;
        };
      }
      setPreviewUri(undefined);
      setLoading(true);
      void resolveAttachmentUri(attachmentValue)
        .then((uri) => {
          if (!active) {
            if (uri) releaseAttachmentUri?.(uri);
            return;
          }
          if (!uri || uri.startsWith("who-va-attachment:")) {
            if (uri) releaseAttachmentUri?.(uri);
            setLoading(false);
            onLoadError(loadFailedMessage);
            return;
          }
          resolvedUri = uri;
          setLoading(false);
          setPreviewUri(uri);
          onLoadError(undefined);
        })
        .catch(() => {
          if (active) {
            setLoading(false);
            onLoadError(loadFailedMessage);
          }
        });
      return () => {
        active = false;
        if (resolvedUri) releaseAttachmentUri?.(resolvedUri);
      };
    }, [attachmentUri, loadFailedMessage, onLoadError, releaseAttachmentUri, resolveAttachmentUri, value]);

    return { previewUri, loading };
  }

  const formatRecordingTime = (seconds: number) =>
    `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;

  /** While a take is open: a red dot (grey when paused), the time with what is left, and a bar toward the limit. */
  function RecordingStatus({
    question,
    messages,
    elapsedSeconds,
    paused,
    limitMs
  }: {
    question: InstrumentQuestion;
    messages: WhoVaUiMessages;
    elapsedSeconds: number;
    paused: boolean;
    limitMs: number | undefined;
  }) {
    const remainingSeconds =
      limitMs !== undefined ? Math.max(0, Math.ceil(limitMs / 1000) - elapsedSeconds) : undefined;
    const limitShare = limitMs ? Math.min(100, (elapsedSeconds * 100_000) / limitMs) : undefined;
    return (
      <>
        <View style={questionControlStyles.recordingStatus}>
          <View
            aria-hidden="true"
            style={[questionControlStyles.recordingDot, paused && questionControlStyles.recordingDotPaused]}
          />
          <PrimitiveText
            accessibilityLabel={`${messages.recordingTime} ${formatRecordingTime(elapsedSeconds)}`}
            testID={`question-${question.name}-timer`}
            style={[questionControlStyles.audioTimer, { marginTop: 0 }]}
          >
            {messages.recordingTime} {formatRecordingTime(elapsedSeconds)}
            {remainingSeconds !== undefined
              ? ` · ${formatRecordingTime(remainingSeconds)} ${messages.recordingLeft}`
              : ""}
            {paused ? ` · ${messages.recordingPaused}` : ""}
          </PrimitiveText>
        </View>
        {limitShare !== undefined ? (
          <View
            aria-hidden="true"
            testID={`question-${question.name}-progress`}
            style={questionControlStyles.recordingTrack}
          >
            <View style={[questionControlStyles.recordingFill, { width: `${limitShare}%` }]} />
          </View>
        ) : null}
      </>
    );
  }

  function Audio({
    question,
    value,
    data,
    platform,
    messages = ENGLISH_UI_MESSAGES,
    issues,
    onAnswer
  }: WhoVaQuestionControlProps) {
    const [phase, setPhase] = useState<"idle" | "starting" | "recording" | "stopping">("idle");
    const [recordingError, setRecordingError] = useState<string>();
    const [playbackError, setPlaybackError] = useState<string>();
    const [confirming, setConfirming] = useState<"replace" | "delete">();
    const [recordingStartedAt, setRecordingStartedAt] = useState<number>();
    const [recordingElapsed, setRecordingElapsed] = useState(0);
    const [recordingPaused, setRecordingPaused] = useState(false);
    const [recordingLimitMs, setRecordingLimitMs] = useState<number>();
    const [pausable, setPausable] = useState(false);
    const session = useRef<WhoVaAudioRecordingSession | undefined>(undefined);
    const requestId = useRef(0);
    const mounted = useRef(true);
    const readOnly = question.readOnly;
    const services = { ...primitives.platform, ...platform };
    const currentAttachment = storedAttachmentReference(value);
    const attachment = attachmentDetails(value);
    const Player = services.AudioPlayer ?? AudioPlayer;
    const recordingUnavailable = !services.startAudioRecording && !services.captureAudio;
    useEffect(() => setPlaybackError(undefined), [attachment.uri]);
    const { previewUri, loading: playbackLoading } = useAudioPreviewUri(
      value,
      services,
      messages.savedAudioLoadFailed,
      setPlaybackError
    );
    const disabled =
      readOnly || phase === "starting" || phase === "stopping" || (phase === "idle" && recordingUnavailable);

    const cancelSession = (activeSession: WhoVaAudioRecordingSession, reportError = false) => {
      void Promise.resolve()
        .then(() => activeSession.cancel())
        .catch(() => {
          if (reportError && mounted.current) setRecordingError(messages.audioRecordingFailed);
        });
    };

    useEffect(() => {
      if (phase !== "recording" || recordingStartedAt === undefined) return;
      const updateElapsed = () => {
        const state = session.current?.getState?.();
        if (state) {
          setRecordingElapsed(Math.max(0, Math.floor(state.elapsedMs / 1000)));
          setRecordingPaused(state.paused);
          setRecordingLimitMs(state.limitMs);
        } else setRecordingElapsed(Math.max(0, Math.floor((globalThis.Date.now() - recordingStartedAt) / 1000)));
      };
      updateElapsed();
      const timer = globalThis.setInterval(updateElapsed, 500);
      return () => globalThis.clearInterval(timer);
    }, [phase, recordingStartedAt]);

    useEffect(() => {
      mounted.current = true;
      return () => {
        mounted.current = false;
        requestId.current += 1;
        const activeSession = session.current;
        session.current = undefined;
        if (activeSession)
          void Promise.resolve()
            .then(() => activeSession.cancel())
            .catch(() => undefined);
      };
    }, []);

    const cancelRecording = () => {
      requestId.current += 1;
      const activeSession = session.current;
      session.current = undefined;
      if (activeSession) cancelSession(activeSession, true);
      setRecordingStartedAt(undefined);
      setRecordingElapsed(0);
      setRecordingPaused(false);
      setPhase("idle");
    };

    const togglePause = async () => {
      const active = session.current;
      if (!active) return;
      try {
        if (recordingPaused) await active.resume?.();
        else await active.pause?.();
        setRecordingPaused(!recordingPaused);
      } catch {
        if (mounted.current) setRecordingError(messages.audioRecordingFailed);
      }
    };

    const removeOldAttachment = (attachmentToRemove: AttachmentReference | undefined) => {
      if (attachmentToRemove)
        void Promise.resolve()
          .then(() => services.removeAttachment?.(attachmentToRemove))
          .catch(() => undefined);
    };

    const record = async () => {
      setConfirming(undefined);
      setRecordingError(undefined);
      const operationId = ++requestId.current;
      try {
        if (phase === "recording" && session.current) {
          const activeSession = session.current;
          setPhase("stopping");
          const recorded = await activeSession.stop();
          if (!mounted.current || requestId.current !== operationId) {
            removeOldAttachment(attachmentReference(recorded));
            return;
          }
          session.current = undefined;
          onAnswer(recorded);
          removeOldAttachment(currentAttachment);
          setRecordingStartedAt(undefined);
          setRecordingElapsed(0);
          setPhase("idle");
          return;
        }
        if (services.startAudioRecording) {
          setPhase("starting");
          const nextSession = await services.startAudioRecording(question, data);
          if (!mounted.current || requestId.current !== operationId) {
            cancelSession(nextSession);
            return;
          }
          session.current = nextSession;
          setPausable(Boolean(nextSession.pause && nextSession.resume));
          setRecordingPaused(false);
          setRecordingLimitMs(undefined);
          setRecordingStartedAt(globalThis.Date.now());
          setRecordingElapsed(0);
          setPhase("recording");
          return;
        }
        if (!services.captureAudio) return;
        setPhase("starting");
        const recorded = await services.captureAudio(question, data);
        if (!mounted.current || requestId.current !== operationId) {
          removeOldAttachment(attachmentReference(recorded));
          return;
        }
        onAnswer(recorded);
        removeOldAttachment(currentAttachment);
        setRecordingStartedAt(undefined);
        setRecordingElapsed(0);
        setPhase("idle");
      } catch (error) {
        if (!mounted.current || requestId.current !== operationId) return;
        const activeSession = session.current;
        session.current = undefined;
        if (activeSession) cancelSession(activeSession);
        setRecordingStartedAt(undefined);
        setRecordingElapsed(0);
        setPhase("idle");
        setRecordingError(
          (typeof DOMException !== "undefined" && error instanceof DOMException && error.name === "NotAllowedError") ||
            (error instanceof Error && error.name === "NotAllowedError")
            ? messages.microphonePermissionDenied
            : messages.audioRecordingFailed
        );
      }
    };

    const label = {
      starting: messages.startingMicrophone,
      recording: messages.stopAndSaveRecording,
      stopping: messages.savingRecording,
      idle: value ? messages.replaceAudio : messages.recordAudio
    }[phase];

    return (
      <View>
        {phase === "recording" ? (
          <RecordingStatus
            question={question}
            messages={messages}
            elapsedSeconds={recordingElapsed}
            paused={recordingPaused}
            limitMs={recordingLimitMs}
          />
        ) : null}
        <View style={questionControlStyles.actionRow}>
          {phase === "recording" && pausable ? (
            <ActionButton
              icon={recordingPaused ? "mic" : "pause"}
              label={recordingPaused ? messages.resumeRecording : messages.pauseRecording}
              disabled={readOnly}
              testID={`question-${question.name}-pause`}
              onPress={() => void togglePause()}
            />
          ) : null}
          <ActionButton
            icon={phase === "recording" ? "stop" : "mic"}
            label={label}
            primary
            invalid={issues.length > 0}
            busy={phase === "starting" || phase === "stopping"}
            disabled={disabled}
            describedBy={recordingUnavailable ? `question-${question.name}-unavailable` : undefined}
            testID={`question-${question.name}`}
            onPress={() => {
              if (readOnly) return;
              if (phase === "idle" && value) setConfirming("replace");
              else void record();
            }}
          />
        </View>
        {services.startAudioRecording && (phase === "starting" || phase === "recording") ? (
          <Pressable
            accessibilityRole="button"
            disabled={readOnly}
            testID={`question-${question.name}-cancel`}
            style={questionControlStyles.textDangerButton}
            onPress={cancelRecording}
          >
            <PrimitiveText style={questionControlStyles.buttonTextDanger}>{messages.cancelRecording}</PrimitiveText>
          </Pressable>
        ) : null}
        {playbackLoading ? (
          <PrimitiveText style={questionControlStyles.hint}>{messages.loadingAudio}</PrimitiveText>
        ) : null}
        {/* Play and Delete share one row with Delete as an icon at the far end, so a tap meant for Play
            cannot land on Delete (owner, phone check 2026-10-30). */}
        {phase === "idle" && ((previewUri && Player) || (value && !readOnly && services.removeAttachment)) ? (
          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 16, marginTop: 16 }}>
            {previewUri && Player ? (
              <Player
                accessibilityLabel={messages.recorded}
                onError={() => setPlaybackError(messages.savedAudioLoadFailed)}
                uri={previewUri}
              />
            ) : <View />}
            {value && !readOnly && services.removeAttachment ? (
              <IconButton
                icon="delete"
                danger
                label={messages.removeRecording}
                testID={`question-${question.name}-remove`}
                onPress={() => setConfirming("delete")}
              />
            ) : null}
          </View>
        ) : null}
        {/* Replace and Delete both destroy the saved recording, so each asks first. */}
        {phase === "idle" && confirming && value ? (
          <ConfirmPrompt
            testID={`question-${question.name}-confirm`}
            prompt={confirming === "delete" ? messages.confirmRemoveRecording : messages.confirmReplaceRecording}
            confirmLabel={confirming === "delete" ? messages.deleteRecordingAction : messages.replaceRecordingAction}
            cancelLabel={messages.keepRecording}
            onConfirm={() => {
              if (confirming === "replace") {
                void record();
                return;
              }
              setConfirming(undefined);
              removeOldAttachment(currentAttachment);
              onAnswer(undefined);
            }}
            onCancel={() => setConfirming(undefined)}
          />
        ) : null}
        {playbackError ? (
          <PrimitiveText accessibilityRole="alert" style={questionControlStyles.attachmentError}>
            {playbackError}
          </PrimitiveText>
        ) : null}
        {recordingError ? (
          <PrimitiveText accessibilityRole="alert" style={questionControlStyles.attachmentError}>
            {recordingError}
          </PrimitiveText>
        ) : null}
        {recordingUnavailable ? (
          <PrimitiveText
            nativeID={`question-${question.name}-unavailable`}
            style={questionControlStyles.hint}
            testID={`question-${question.name}-unavailable`}
          >
            {messages.audioUnavailable}
          </PrimitiveText>
        ) : null}
      </View>
    );
  }

  type ImageSource = "scan" | "camera" | "library" | "draw";

  /**
   * Image questions whose photo is a paper document (owner, 2026-11-06, digitva-lq5m): the written narrative and
   * the medical and death documents. They get "Scan document" first; every other image question keeps Camera first.
   */
  const DOCUMENT_IMAGE_QUESTION = /^(imagenarr|md_im\d+|ds_im\d+)$/;

  /** The host picker for a source, or undefined when the host supplies none. */
  function imagePickerFor(
    source: ImageSource,
    services: WhoVaPlatformServices,
    drawMode: "draw" | "signature" | undefined
  ) {
    if (source === "camera") return services.captureImage;
    if (source === "library") return services.selectImage;
    if (source === "scan") return scanOrCamera(services);
    const captureDrawing = services.captureDrawing;
    if (!captureDrawing) return undefined;
    return (q: InstrumentQuestion, d: SubmissionData) => captureDrawing(q, d, drawMode ?? "draw");
  }

  /** The scanner, falling back to the plain camera when it fails (no scanner on this phone); a cancel is a cancel. */
  function scanOrCamera(services: WhoVaPlatformServices) {
    const scan = services.scanDocument;
    const camera = services.captureImage;
    if (!scan) return camera;
    return async (q: InstrumentQuestion, d: SubmissionData) => {
      try {
        return await scan(q, d);
      } catch (error) {
        if (!camera) throw error;
        return camera(q, d);
      }
    };
  }

  /** Whether the host scores the just-picked image as blurry. Never throws: a failed check counts as sharp. */
  async function looksBlurry(services: WhoVaPlatformServices, uri: string) {
    if (!services.checkSharpness) return false;
    try {
      return (await services.checkSharpness(uri)).blurry;
    } catch {
      return false;
    }
  }

  /**
   * Run a picker and return the processed image it yields (undefined when the
   * user cancels) and whether it looked blurry. Fail-closed: an unprocessed
   * candidate needs the host's processImage, and whatever comes back must be a
   * processed image. The blur check reads the candidate before processImage,
   * the only moment its plain file exists.
   */
  async function acquireProcessedImage(
    picker: (q: InstrumentQuestion, d: SubmissionData) => Promise<AttachmentCandidate | undefined>,
    services: WhoVaPlatformServices,
    question: InstrumentQuestion,
    data: SubmissionData,
    checkBlur: boolean
  ) {
    const candidate = await picker(question, data);
    let selected = candidate;
    let blurry = false;
    if (candidate !== undefined && !isProcessedImageAttachment(candidate)) {
      if (!services.processImage) throw new AttachmentProcessingError("image-processing-unavailable");
      if (checkBlur) blurry = await looksBlurry(services, candidate.uri);
      selected = await services.processImage(candidate, WHO_VA_ATTACHMENT_POLICY.image, question, data);
    }
    if (selected !== undefined && !isProcessedImageAttachment(selected)) {
      throw new AttachmentProcessingError("image-output-invalid");
    }
    return { selected, blurry };
  }

  /**
   * The URL to preview a stored image from. Opaque `who-va-attachment:` refs
   * are resolved through the host (and released on change); anything else is
   * shown as is. A failed resolution is reported through `onLoadError`.
   */
  function useImagePreviewUri(
    value: AnswerValue | undefined,
    attachmentUri: string | undefined,
    services: WhoVaPlatformServices,
    loadFailedMessage: string,
    onLoadError: (message: string) => void
  ) {
    const [previewUri, setPreviewUri] = useState<string | undefined>(() =>
      attachmentUri?.startsWith("who-va-attachment:") ? undefined : attachmentUri
    );
    const resolveAttachmentUri = services.resolveAttachmentUri;
    const releaseAttachmentUri = services.releaseAttachmentUri;

    useEffect(() => {
      let active = true;
      let resolvedUri: string | undefined;
      // A resumed draft keeps the answer as the bare "who-va-attachment:<id>" string, so read both forms.
      const attachmentValue = storedAttachmentReference(value);
      if (
        !attachmentUri ||
        !resolveAttachmentUri ||
        attachmentValue === undefined ||
        !attachmentUri.startsWith("who-va-attachment:")
      ) {
        // An opaque ref the host cannot resolve is never handed to <Image>: no platform can load it.
        setPreviewUri(attachmentUri?.startsWith("who-va-attachment:") ? undefined : attachmentUri);
        return () => {
          active = false;
        };
      }
      setPreviewUri(undefined);
      void resolveAttachmentUri(attachmentValue)
        .then((uri) => {
          resolvedUri = uri;
          if (active) setPreviewUri(uri);
        })
        .catch(() => {
          if (active) onLoadError(loadFailedMessage);
        });
      return () => {
        active = false;
        if (resolvedUri) releaseAttachmentUri?.(resolvedUri);
      };
    }, [attachmentUri, loadFailedMessage, onLoadError, releaseAttachmentUri, resolveAttachmentUri, value]);

    return previewUri;
  }

  /** The plain enlarged view for a host without its own viewer: no gestures, a rotate and a close button. */
  function PlainPhotoViewer({
    uri,
    accessibilityLabel,
    rotateLabel,
    closeLabel,
    onClose
  }: WhoVaImageViewerProps) {
    const [rotation, setRotation] = useState(0);
    const body = (
      <View
        accessibilityViewIsModal
        aria-label={accessibilityLabel}
        aria-modal="true"
        role="dialog"
        testID="photo-viewer"
        style={questionControlStyles.viewerOverlay}
      >
        <View style={questionControlStyles.viewerBar}>
          <IconButton
            icon="rotate"
            label={rotateLabel}
            testID="photo-viewer-rotate"
            onPress={() => setRotation((current) => (current + 90) % 360)}
          />
          <IconButton icon="close" label={closeLabel} testID="photo-viewer-close" onPress={onClose} />
        </View>
        {Image ? (
          <Image
            accessibilityLabel={accessibilityLabel}
            testID="photo-viewer-image"
            source={{ uri }}
            style={[questionControlStyles.viewerImage, { transform: [{ rotate: `${rotation}deg` }] }]}
          />
        ) : null}
      </View>
    );
    if (!Modal) return body;
    return (
      <Modal animationType="none" onRequestClose={onClose} transparent visible>
        {body}
      </Modal>
    );
  }

  /**
   * A stored photo's preview; a tap opens it full screen in the host's viewer (pinch-zoom, pan, rotate) or the
   * plain one. Rotation there is view-only, as it always was: the stored image never changes.
   */
  function PhotoPreview({
    question,
    uri,
    name,
    services,
    messages
  }: {
    question: InstrumentQuestion;
    uri: string;
    name: string | undefined;
    services: WhoVaPlatformServices;
    messages: WhoVaUiMessages;
  }) {
    const [viewing, setViewing] = useState(false);
    if (!Image) return null;
    const Viewer = services.ImageViewer ?? PlainPhotoViewer;
    const label = name ?? messages.selectedImage;
    return (
      <>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`${messages.viewFullScreen}: ${label}`}
          aria-label={`${messages.viewFullScreen}: ${label}`}
          testID={`question-${question.name}-preview-open`}
          style={questionControlStyles.imageFrame}
          onPress={() => setViewing(true)}
        >
          <Image
            accessibilityLabel={label}
            testID={`question-${question.name}-preview`}
            source={{ uri }}
            style={questionControlStyles.image}
          />
        </Pressable>
        {viewing ? (
          <Viewer
            uri={uri}
            accessibilityLabel={label}
            rotateLabel={messages.rotate}
            closeLabel={messages.closeImage}
            onClose={() => setViewing(false)}
          />
        ) : null}
      </>
    );
  }

  /** "This photo looks blurry. Retake?" after a blurry capture: the photo is already saved, so Keep only dismisses. */
  function BlurryPrompt({
    question,
    messages,
    onRetake,
    onKeep
  }: {
    question: InstrumentQuestion;
    messages: WhoVaUiMessages;
    onRetake: () => void;
    onKeep: () => void;
  }) {
    return (
      <ConfirmPrompt
        testID={`question-${question.name}-blurry`}
        prompt={messages.blurryPhoto}
        confirmLabel={messages.retakePhoto}
        cancelLabel={messages.keepPhoto}
        confirmTone="primary"
        onConfirm={onRetake}
        onCancel={onKeep}
      />
    );
  }

  /**
   * The image control's buttons: Draw / Sign alone for `draw` and `signature`; otherwise Scan document (document
   * questions, when the host has a scanner), Camera and the gallery, the first one filled; Delete last.
   */
  function ImageActionRow({
    question,
    services,
    messages,
    busy,
    drawMode,
    hasImage,
    invalid,
    readOnly,
    onChoose,
    onRemove
  }: {
    question: InstrumentQuestion;
    services: WhoVaPlatformServices;
    messages: WhoVaUiMessages;
    busy: ImageSource | undefined;
    drawMode: "draw" | "signature" | undefined;
    hasImage: boolean;
    invalid: boolean;
    readOnly: boolean | undefined;
    onChoose: (source: ImageSource) => void;
    onRemove: () => void;
  }) {
    const offersScan = !drawMode && Boolean(services.scanDocument) && DOCUMENT_IMAGE_QUESTION.test(question.name);
    const unavailableId =
      !services.captureImage && !services.selectImage ? `question-${question.name}-unavailable` : undefined;
    const drawLabel =
      drawMode === "signature"
        ? hasImage
          ? messages.reSign
          : messages.sign
        : hasImage
          ? messages.redraw
          : messages.draw;
    return (
      <View style={questionControlStyles.actionRow}>
        {drawMode ? (
          <ActionButton
            label={drawLabel}
            primary
            invalid={invalid}
            disabled={readOnly || !services.captureDrawing || busy != null}
            testID={`question-${question.name}-draw`}
            onPress={() => onChoose("draw")}
          />
        ) : (
          <>
            {offersScan ? (
              <ActionButton
                icon="scan"
                label={busy === "scan" ? messages.openingScanner : messages.scanDocument}
                primary
                invalid={invalid}
                busy={busy === "scan"}
                disabled={readOnly || busy != null}
                testID={`question-${question.name}-scan`}
                onPress={() => onChoose("scan")}
              />
            ) : null}
            <ActionButton
              icon="camera"
              label={busy === "camera" ? messages.openingCamera : messages.camera}
              primary={!offersScan}
              invalid={invalid}
              busy={busy === "camera"}
              disabled={readOnly || !services.captureImage || busy != null}
              describedBy={unavailableId}
              testID={`question-${question.name}-camera`}
              onPress={() => onChoose("camera")}
            />
            <ActionButton
              icon="gallery"
              label={
                busy === "library" ? messages.openingImages : hasImage ? messages.replaceImage : messages.chooseImage
              }
              invalid={invalid}
              busy={busy === "library"}
              disabled={readOnly || !services.selectImage || busy != null}
              testID={`question-${question.name}-library`}
              onPress={() => onChoose("library")}
            />
          </>
        )}
        {hasImage && !readOnly ? (
          <IconButton
            icon="delete"
            danger
            label={messages.removeImage}
            testID={`question-${question.name}-remove`}
            onPress={onRemove}
          />
        ) : null}
      </View>
    );
  }

  function ImagePicker({
    question,
    value,
    data,
    platform,
    messages = ENGLISH_UI_MESSAGES,
    issues,
    onAnswer
  }: WhoVaQuestionControlProps) {
    const attachment = attachmentDetails(value);
    const [busy, setBusy] = useState<ImageSource>();
    const [confirmingRemove, setConfirmingRemove] = useState(false);
    const [blurrySource, setBlurrySource] = useState<ImageSource>();
    const [processingError, setProcessingError] = useState<string>();
    const readOnly = question.readOnly;
    const services = { ...primitives.platform, ...platform };
    const currentAttachment = storedAttachmentReference(value);
    const previewUri = useImagePreviewUri(
      value,
      attachment.uri,
      services,
      messages.savedImageLoadFailed,
      setProcessingError
    );

    // `signature` and `draw` replace capture-or-select with a drawing surface.
    const drawMode = hasAppearance(question, "signature")
      ? ("signature" as const)
      : hasAppearance(question, "draw")
        ? ("draw" as const)
        : undefined;
    const hasImage = Boolean(attachment.uri);

    const choose = async (source: ImageSource) => {
      const picker = imagePickerFor(source, services, drawMode);
      if (readOnly || !picker) return;
      setBusy(source);
      setBlurrySource(undefined);
      setProcessingError(undefined);
      try {
        const { selected, blurry } = await acquireProcessedImage(picker, services, question, data, source !== "draw");
        if (selected !== undefined) {
          if (currentAttachment) await services.removeAttachment?.(currentAttachment);
          onAnswer(selected);
          setConfirmingRemove(false);
          if (blurry) setBlurrySource(source);
        }
      } catch (error) {
        setProcessingError(attachmentErrorMessage(error, messages));
      } finally {
        setBusy(undefined);
      }
    };

    return (
      <>
        {previewUri ? (
          <PhotoPreview
            question={question}
            uri={previewUri}
            name={attachment.name}
            services={services}
            messages={messages}
          />
        ) : null}
        {attachment.name ? (
          <PrimitiveText style={questionControlStyles.attachmentName}>{attachment.name}</PrimitiveText>
        ) : null}
        {processingError ? (
          <PrimitiveText accessibilityRole="alert" style={questionControlStyles.attachmentError}>
            {processingError}
          </PrimitiveText>
        ) : null}
        {!services.captureImage && !services.selectImage && !services.captureDrawing ? (
          <PrimitiveText
            nativeID={`question-${question.name}-unavailable`}
            style={questionControlStyles.hint}
            testID={`question-${question.name}-unavailable`}
          >
            {messages.imageUnavailable}
          </PrimitiveText>
        ) : null}
        <ImageActionRow
          question={question}
          services={services}
          messages={messages}
          busy={busy}
          drawMode={drawMode}
          hasImage={hasImage}
          invalid={issues.length > 0}
          readOnly={readOnly}
          onChoose={(source) => void choose(source)}
          onRemove={() => setConfirmingRemove(true)}
        />
        {blurrySource && hasImage ? (
          <BlurryPrompt
            question={question}
            messages={messages}
            onRetake={() => void choose(blurrySource)}
            onKeep={() => setBlurrySource(undefined)}
          />
        ) : null}
        {confirmingRemove && hasImage ? (
          <ConfirmPrompt
            testID={`question-${question.name}-confirm`}
            prompt={messages.confirmRemoveAttachment(messages.selectedImage.toLowerCase())}
            confirmLabel={messages.removeImage}
            cancelLabel={messages.keepAttachment(messages.selectedImage.toLowerCase())}
            onConfirm={() => {
              setConfirmingRemove(false);
              setBlurrySource(undefined);
              if (currentAttachment) void services.removeAttachment?.(currentAttachment);
              onAnswer(undefined);
            }}
            onCancel={() => setConfirmingRemove(false)}
          />
        ) : null}
      </>
    );
  }

  function FilePicker({
    question,
    value,
    data,
    platform,
    messages = ENGLISH_UI_MESSAGES,
    issues,
    onAnswer
  }: WhoVaQuestionControlProps) {
    const [busy, setBusy] = useState<"files" | "camera" | "scan">();
    const [confirmingRemove, setConfirmingRemove] = useState(false);
    const [blurrySource, setBlurrySource] = useState<"camera" | "scan" | "files">();
    const [processingError, setProcessingError] = useState<string>();
    const attachment = attachmentDetails(value);
    const readOnly = question.readOnly;
    const services = { ...primitives.platform, ...platform };
    const currentAttachment = storedAttachmentReference(value);
    const acceptsImages = hasAppearance(question, "image-or-pdf");
    // An image-or-PDF upload is a paper certificate: the scanner leads where the host has one.
    const offersScan = acceptsImages && Boolean(services.scanDocument);
    const acceptedMimeTypes = acceptsImages
      ? [
          ...WHO_VA_ATTACHMENT_POLICY.image.acceptedMimeTypes,
          ...WHO_VA_ATTACHMENT_POLICY.pdf.acceptedMimeTypes
        ]
      : [...WHO_VA_ATTACHMENT_POLICY.pdf.acceptedMimeTypes];
    const attachmentLabel = acceptsImages ? messages.attachment : messages.pdf;
    // A photographed or chosen image is shown; a PDF is shown by its name.
    const isImage = attachmentMimeType(value)?.startsWith("image/") ?? false;
    const previewUri = useImagePreviewUri(
      isImage ? value : undefined,
      isImage ? attachment.uri : undefined,
      services,
      messages.savedImageLoadFailed,
      setProcessingError
    );
    // A saved PDF has no preview, so it opens in a new tab through the host's resolver (blob URL on web).
    const canOpenInTab = typeof window !== "undefined" && typeof window.open === "function";
    const openPdf = async () => {
      if (!currentAttachment || !services.resolveAttachmentUri) return;
      const uri = await services.resolveAttachmentUri(currentAttachment);
      if (!uri) return setProcessingError(messages.savedImageLoadFailed);
      window.open(uri, "_blank", "noopener");
      // The new tab needs the blob URL to outlive this call; the tab holds its own reference once loaded.
      setTimeout(() => services.releaseAttachmentUri?.(uri), 60_000);
    };
    const save = async (selected: AnswerValue | undefined, blurry: boolean, source: "camera" | "scan" | "files") => {
      if (selected === undefined) return;
      if (currentAttachment) await services.removeAttachment?.(currentAttachment);
      setConfirmingRemove(false);
      onAnswer(selected);
      if (blurry) setBlurrySource(source);
    };
    const takePhoto = async (source: "camera" | "scan") => {
      const picker = source === "scan" ? scanOrCamera(services) : services.captureImage;
      if (readOnly || !picker) return;
      setBusy(source);
      setBlurrySource(undefined);
      setProcessingError(undefined);
      try {
        const { selected, blurry } = await acquireProcessedImage(picker, services, question, data, true);
        await save(selected, blurry, source);
      } catch (error) {
        setProcessingError(attachmentErrorMessage(error, messages));
      } finally {
        setBusy(undefined);
      }
    };
    const chooseFile = async () => {
      if (readOnly || !services?.selectFile) return;
      setBusy("files");
      setBlurrySource(undefined);
      setProcessingError(undefined);
      try {
        const candidate = await services.selectFile(question, data, acceptedMimeTypes);
        let selected = candidate;
        let blurry = false;
        if (
          candidate !== undefined &&
          !isRetainedPdfAttachment(candidate) &&
          !(acceptsImages && isProcessedImageAttachment(candidate))
        ) {
          if (
            acceptsImages &&
            WHO_VA_ATTACHMENT_POLICY.image.acceptedMimeTypes.includes(
              attachmentMimeType(candidate) as "image/jpeg" | "image/png"
            )
          ) {
            if (!services.processImage) throw new AttachmentProcessingError("image-processing-unavailable");
            blurry = await looksBlurry(services, candidate.uri);
            selected = await services.processImage(candidate, WHO_VA_ATTACHMENT_POLICY.image, question, data);
          } else {
            throw new AttachmentProcessingError("pdf-processing-unavailable");
          }
        }
        if (selected !== undefined) {
          if (!isRetainedPdfAttachment(selected) && !(acceptsImages && isProcessedImageAttachment(selected))) {
            throw new AttachmentProcessingError(acceptsImages ? "image-output-invalid" : "pdf-render-failed");
          }
          await save(selected, blurry, "files");
        }
      } catch (error) {
        setProcessingError(attachmentErrorMessage(error, messages));
      } finally {
        setBusy(undefined);
      }
    };
    const invalid = issues.length > 0;
    const hasCamera = acceptsImages && Boolean(services.captureImage);
    return (
      <>
        {previewUri ? (
          <PhotoPreview
            question={question}
            uri={previewUri}
            name={attachment.name}
            services={services}
            messages={messages}
          />
        ) : null}
        {attachment.name ? (
          <PrimitiveText style={questionControlStyles.attachmentName}>{attachment.name}</PrimitiveText>
        ) : null}
        {!services?.selectFile ? (
          <PrimitiveText
            nativeID={`question-${question.name}-unavailable`}
            style={questionControlStyles.hint}
            testID={`question-${question.name}-unavailable`}
          >
            {messages.fileUnavailable}
          </PrimitiveText>
        ) : null}
        <View style={questionControlStyles.actionRow}>
          {offersScan ? (
            <ActionButton
              icon="scan"
              label={busy === "scan" ? messages.openingScanner : messages.scanDocument}
              primary
              invalid={invalid}
              busy={busy === "scan"}
              disabled={readOnly || busy != null}
              testID={`question-${question.name}-scan`}
              onPress={() => void takePhoto("scan")}
            />
          ) : null}
          {hasCamera ? (
            <ActionButton
              icon="camera"
              label={busy === "camera" ? messages.openingCamera : messages.camera}
              invalid={invalid}
              busy={busy === "camera"}
              disabled={readOnly || busy != null}
              testID={`question-${question.name}-camera`}
              onPress={() => void takePhoto("camera")}
            />
          ) : null}
          <ActionButton
            icon="attach"
            label={
              busy === "files"
                ? messages.openingFiles
                : attachment.uri
                  ? messages.replaceAttachment(attachmentLabel)
                  : messages.chooseAttachment(attachmentLabel)
            }
            primary={!offersScan && !hasCamera}
            invalid={invalid}
            busy={busy === "files"}
            disabled={readOnly || !services?.selectFile || busy != null}
            describedBy={!services?.selectFile ? `question-${question.name}-unavailable` : undefined}
            testID={`question-${question.name}`}
            onPress={() => void chooseFile()}
          />
          {attachment.uri && !isImage && canOpenInTab && services.resolveAttachmentUri ? (
            <ActionButton
              icon="attach"
              label={messages.openAttachment(attachmentLabel)}
              disabled={busy != null}
              testID={`question-${question.name}-open`}
              onPress={() => void openPdf()}
            />
          ) : null}
          {attachment.uri && !readOnly ? (
            <IconButton
              icon="delete"
              danger
              label={messages.removeAttachment(attachmentLabel)}
              testID={`question-${question.name}-remove`}
              onPress={() => setConfirmingRemove(true)}
            />
          ) : null}
        </View>
        {processingError ? (
          <PrimitiveText accessibilityRole="alert" style={questionControlStyles.attachmentError}>
            {processingError}
          </PrimitiveText>
        ) : null}
        {blurrySource && attachment.uri ? (
          <BlurryPrompt
            question={question}
            messages={messages}
            onRetake={() => void (blurrySource === "files" ? chooseFile() : takePhoto(blurrySource))}
            onKeep={() => setBlurrySource(undefined)}
          />
        ) : null}
        {confirmingRemove && attachment.uri ? (
          <ConfirmPrompt
            testID={`question-${question.name}-confirm`}
            prompt={messages.confirmRemoveAttachment(attachmentLabel)}
            confirmLabel={messages.removeAttachment(attachmentLabel)}
            cancelLabel={messages.keepAttachment(attachmentLabel)}
            onConfirm={() => {
              setConfirmingRemove(false);
              setBlurrySource(undefined);
              if (currentAttachment) void services.removeAttachment?.(currentAttachment);
              onAnswer(undefined);
            }}
            onCancel={() => setConfirmingRemove(false)}
          />
        ) : null}
      </>
    );
  }

  function Note(_props: WhoVaQuestionControlProps) {
    return null;
  }
  function Empty(_props: WhoVaQuestionControlProps) {
    return null;
  }

  function Control(props: WhoVaQuestionControlProps) {
    switch (props.question.control) {
      case "text":
        return <Text {...props} />;
      case "integer":
        return <Integer {...props} />;
      case "decimal":
        return <Decimal {...props} />;
      case "date":
        return <Date {...props} />;
      case "time":
        return <Time {...props} />;
      case "datetime":
        return <DateTime {...props} />;
      case "barcode":
        return <Barcode {...props} />;
      case "range":
        return <Range {...props} />;
      case "geopoint":
        return <GeoPoint {...props} />;
      case "singleChoice":
        return <SingleChoice {...props} />;
      case "multipleChoice":
        return <MultipleChoice {...props} />;
      case "confirm":
        return <Confirm {...props} />;
      case "audio":
        return <Audio {...props} />;
      case "image":
        return <ImagePicker {...props} />;
      case "file":
        return <FilePicker {...props} />;
      case "note":
        return <Note {...props} />;
      case "calculated":
      case "system":
        return <Empty {...props} />;
    }
  }

  return {
    Control,
    Text,
    Integer,
    Decimal,
    Date,
    Time,
    DateTime,
    Barcode,
    Range,
    GeoPoint,
    SingleChoice,
    MultipleChoice,
    Confirm,
    Audio,
    Image: ImagePicker,
    File: FilePicker,
    Note,
    Calculated: Empty,
    System: Empty
  };
}

export type WhoVaQuestionControls = ReturnType<typeof createWhoVaQuestionControls>;
