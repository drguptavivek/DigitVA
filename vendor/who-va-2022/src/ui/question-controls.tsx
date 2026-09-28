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
  /** Return an ODK geopoint string: "latitude longitude altitude accuracy". */
  captureLocation?: (question: InstrumentQuestion, data: SubmissionData) => Promise<string | undefined>;
  /** Return the scanned barcode value, or undefined when the user cancels. */
  scanBarcode?: (question: InstrumentQuestion, data: SubmissionData) => Promise<string | undefined>;
  resolveAttachmentUri?: (attachment: AttachmentReference) => Promise<string | undefined>;
  releaseAttachmentUri?: (uri: string) => void;
  removeAttachment?: (attachment: AttachmentReference) => Promise<void>;
}

export interface WhoVaAudioRecordingSession {
  stop(): Promise<AttachmentReference>;
  cancel(): void | Promise<void>;
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
  Pressable: React.ElementType;
  Image?: React.ElementType | undefined;
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

export function createWhoVaQuestionControls(primitives: WhoVaQuestionControlPrimitives) {
  const { View, Text: PrimitiveText, TextInput, DateInput, Select, Pressable, Image } = primitives;
  const RichText = primitives.RichText;

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
        {label}
        {"\n"}
        <PrimitiveText lang="en" style={questionControlStyles.choiceEnglish}>
          {RichText ? <RichText source={english} /> : plainText(english)}
        </PrimitiveText>
      </>
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
        value={
          grouped && !multiline && value != null && value !== ""
            ? formatGrouped(String(value).replace(/[^\d.eE+-]/g, ""), locale)
            : value == null
              ? ""
              : String(value)
        }
        multiline={multiline}
        secureTextEntry={masked || undefined}
        keyboardType={numbersOnly ? "number-pad" : undefined}
        inputMode={numbersOnly ? "numeric" : undefined}
        onChangeText={(text: string) => {
          if (readOnly) return;
          // `numbers` restricts what can be typed but still stores text.
          const next = numbersOnly ? asciiDigits(text).replace(/[^\d.+-]/g, "") : text;
          onAnswer(next || undefined);
        }}
      />
    );
  }

  /**
   * A numeric box sized to its expected digits, between "-" and "+" buttons
   * and followed by its unit. The buttons never go below the constraint's
   * minimum and stop at its maximum; typing is unrestricted, so a special
   * code such as 99 for "does not wish to disclose" still goes in.
   */
  function NumberField({
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
    text,
    value
  }: {
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
    const { min, max } = constraintBounds(question);
    const current = typeof value === "number" ? value : undefined;
    const step = decimal ? 0.1 : 1;
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
        <Pressable
          accessibilityLabel={messages.decrease}
          accessibilityRole="button"
          disabled={!canDecrease}
          onPress={() => stepTo(-step)}
          style={[questionControlStyles.stepButton, !canDecrease && questionControlStyles.buttonDisabled]}
          testID={`question-${question.name}-decrease`}
        >
          <PrimitiveText aria-hidden="true" style={questionControlStyles.stepGlyph}>
            −
          </PrimitiveText>
        </Pressable>
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
        <Pressable
          accessibilityLabel={messages.increase}
          accessibilityRole="button"
          disabled={!canIncrease}
          onPress={() => stepTo(step)}
          style={[questionControlStyles.stepButton, !canIncrease && questionControlStyles.buttonDisabled]}
          testID={`question-${question.name}-increase`}
        >
          <PrimitiveText aria-hidden="true" style={questionControlStyles.stepGlyph}>
            +
          </PrimitiveText>
        </Pressable>
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

  function Range({ question, value, locale, issues, onAnswer }: WhoVaQuestionControlProps) {
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

    return (
      <TextInput
        accessibilityLabel={questionLabel(question, locale)}
        testID={`question-${question.name}`}
        style={[
          questionControlStyles.input,
          hasIssues && questionControlStyles.inputError,
          readOnly && questionControlStyles.inputReadOnly
        ]}
        aria-invalid={hasIssues || undefined}
        editable={!readOnly}
        readOnly={readOnly || undefined}
        value={value == null ? "" : String(value)}
        keyboardType={fractional ? "decimal-pad" : "number-pad"}
        {...({ min: start, max: end, step } as Record<string, unknown>)}
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
    const [busy, setBusy] = useState(false);
    const label = questionLabel(question, locale);
    const hasIssues = issues.length > 0;
    const readOnly = question.readOnly;
    const services = { ...primitives.platform, ...platform };

    useEffect(() => () => onDraftIssue?.(question.name, undefined), [onDraftIssue, question.name]);

    const updateDraft = (next: string | undefined, issue?: ValidationIssue) => {
      setDraft(next);
      onDraftIssue?.(question.name, issue ?? incompleteDateIssue(question, next, locale, messages));
    };

    if (hasAppearance(question, "month-year")) {
      const shown = draft ?? (typeof value === "string" ? value.slice(0, 7) : "");
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
          {...({ type: "month" } as Record<string, unknown>)}
          value={shown}
          maxLength={7}
          placeholder="YYYY-MM"
          onChangeText={(text: string) => {
            if (readOnly || !/^[\d-]*$/.test(text)) return;
            if (text === "") {
              updateDraft(undefined);
              onAnswer(undefined);
            } else if (/^\d{4}-(0[1-9]|1[0-2])$/.test(text)) {
              // Canonical storage stays a full ISO date, as `year` does.
              onAnswer(`${text}-01`);
              updateDraft(undefined);
            } else {
              updateDraft(text);
              onAnswer(undefined);
            }
          }}
        />
      );
    }

    if (hasAppearance(question, "year")) {
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
          value={draft ?? (typeof value === "string" ? value.slice(0, 4) : "")}
          keyboardType="number-pad"
          maxLength={4}
          placeholder="YYYY"
          onChangeText={(text: string) => {
            if (readOnly || !/^\d*$/.test(text)) return;
            if (text === "") {
              updateDraft(undefined);
              onAnswer(undefined);
            } else if (text.length === 4) {
              onAnswer(`${text}-01-01`);
              updateDraft(undefined);
            } else {
              updateDraft(text);
              onAnswer(undefined);
            }
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
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={label}
          accessibilityState={{ disabled: busy }}
          testID={`question-${question.name}`}
          style={[
            questionControlStyles.input,
            hasIssues && questionControlStyles.inputError,
            (readOnly || busy) && questionControlStyles.buttonDisabled
          ]}
          disabled={readOnly || busy}
          onPress={async () => {
            if (readOnly) return;
            setBusy(true);
            try {
              const selected = await services.pickDate?.(
                question,
                data,
                typeof value === "string" ? value : undefined
              );
              if (selected !== undefined) onAnswer(selected);
            } finally {
              setBusy(false);
            }
          }}
        >
          <PrimitiveText
            style={value == null ? questionControlStyles.hint : questionControlStyles.choiceText}
          >
            {busy
              ? messages.openingCalendar
              : value == null
                ? messages.selectDate
                : formatDdMmmYyyy(String(value), locale)}
          </PrimitiveText>
        </Pressable>
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
   * them, styled as one field, and a calendar button that opens the native
   * picker (a hidden <input type="date">). The stored value stays ISO; a
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
                  📅
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
                accessibilityRole="option"
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
                <PrimitiveText style={questionControlStyles.choiceText}>
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
    if (bare) cellStyle.push(questionControlStyles.choiceBare);

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
    const wrap = (cells: React.ReactNode) =>
      gridCandidate ? (
        <View
          onLayout={(event: { nativeEvent: { layout: { width: number } } }) =>
            setWidth(event.nativeEvent.layout.width)
          }
          style={grid ? questionControlStyles.choiceGrid : undefined}
          testID={`question-${question.name}-choices`}
          {...(grid ? { "data-columns": grid.columns } : {})}
        >
          {cells}
        </View>
      ) : inline ? (
        <View style={questionControlStyles.choiceRow}>{cells}</View>
      ) : (
        cells
      );

    return { choices, cellStyle, inline, searchNode, wrap };
  }

  function SingleChoice(props: WhoVaQuestionControlProps) {
    const { question, value, locale, issues, onAnswer } = props;
    const { choices, cellStyle, searchNode, wrap } = useChoicePresentation(
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
          <PrimitiveText style={questionControlStyles.choiceText}>
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
    const { choices, cellStyle, searchNode, wrap } = useChoicePresentation(
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
          <PrimitiveText style={questionControlStyles.choiceText}>
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
    const session = useRef<WhoVaAudioRecordingSession | undefined>(undefined);
    const readOnly = question.readOnly;
    const services = { ...primitives.platform, ...platform };
    const currentAttachment = attachmentReference(value);
    const disabled =
      readOnly ||
      phase === "starting" ||
      phase === "stopping" ||
      (phase === "idle" && !services.startAudioRecording && !services.captureAudio);

    useEffect(
      () => () => {
        if (session.current) void session.current.cancel();
      },
      []
    );

    const label =
      phase === "starting"
        ? messages.startingMicrophone
        : phase === "recording"
          ? messages.stopAndSaveRecording
          : phase === "stopping"
            ? messages.savingRecording
            : value
              ? messages.replaceAudio
              : messages.recordAudio;

    return (
      <View>
        <Pressable
          accessibilityRole="button"
          accessibilityState={{ disabled, busy: phase === "starting" || phase === "stopping" }}
          aria-invalid={issues.length > 0 || undefined}
          testID={`question-${question.name}`}
          aria-describedby={
            !services.startAudioRecording && !services.captureAudio
              ? `question-${question.name}-unavailable`
              : undefined
          }
          style={[
            questionControlStyles.button,
            issues.length > 0 && questionControlStyles.buttonError,
            disabled && questionControlStyles.buttonDisabled
          ]}
          disabled={disabled}
          onPress={async () => {
            if (readOnly) return;
            setRecordingError(undefined);
            try {
              if (phase === "recording" && session.current) {
                setPhase("stopping");
                const recorded = await session.current.stop();
                session.current = undefined;
                if (currentAttachment) await services.removeAttachment?.(currentAttachment);
                onAnswer(recorded);
                setPhase("idle");
                return;
              }
              if (services.startAudioRecording) {
                setPhase("starting");
                session.current = await services.startAudioRecording(question, data);
                setPhase("recording");
                return;
              }
              if (!services.captureAudio) return;
              setPhase("starting");
              const recorded = await services.captureAudio(question, data);
              if (currentAttachment) await services.removeAttachment?.(currentAttachment);
              onAnswer(recorded);
              setPhase("idle");
            } catch (error) {
              session.current = undefined;
              setPhase("idle");
              setRecordingError(
                typeof DOMException !== "undefined" &&
                  error instanceof DOMException &&
                  error.name === "NotAllowedError"
                  ? messages.microphonePermissionDenied
                  : messages.audioRecordingFailed
              );
            }
          }}
        >
          <PrimitiveText style={questionControlStyles.buttonText}>{label}</PrimitiveText>
        </Pressable>
        {recordingError ? (
          <PrimitiveText accessibilityRole="alert" style={questionControlStyles.attachmentError}>
            {recordingError}
          </PrimitiveText>
        ) : null}
        {!services.startAudioRecording && !services.captureAudio ? (
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
    const [busy, setBusy] = useState<"camera" | "library" | "draw">();
    const [rotation, setRotation] = useState(0);
    const [zoom, setZoom] = useState(1);
    const [visible, setVisible] = useState(true);
    const [previewUri, setPreviewUri] = useState<string | undefined>(() => attachment.uri);
    const [processingError, setProcessingError] = useState<string>();
    const readOnly = question.readOnly;
    const services = { ...primitives.platform, ...platform };
    const currentAttachment = attachmentReference(value);
    const resolveAttachmentUri = services.resolveAttachmentUri;
    const releaseAttachmentUri = services.releaseAttachmentUri;

    useEffect(() => {
      let active = true;
      let resolvedUri: string | undefined;
      const attachmentValue = attachmentReference(value);
      if (!attachment.uri) {
        setPreviewUri(undefined);
        return () => {
          active = false;
        };
      }
      if (
        !resolveAttachmentUri ||
        attachmentValue === undefined ||
        !attachment.uri.startsWith("who-va-attachment:")
      ) {
        setPreviewUri(attachment.uri);
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
          if (active) setProcessingError(messages.savedImageLoadFailed);
        });
      return () => {
        active = false;
        if (resolvedUri) releaseAttachmentUri?.(resolvedUri);
      };
    }, [attachment.uri, messages.savedImageLoadFailed, releaseAttachmentUri, resolveAttachmentUri, value]);

    // `signature` and `draw` replace capture-or-select with a drawing surface.
    const drawMode = hasAppearance(question, "signature")
      ? ("signature" as const)
      : hasAppearance(question, "draw")
        ? ("draw" as const)
        : undefined;

    const choose = async (source: "camera" | "library" | "draw") => {
      const picker =
        source === "draw"
          ? services?.captureDrawing
            ? (q: InstrumentQuestion, d: SubmissionData) => services.captureDrawing!(q, d, drawMode ?? "draw")
            : undefined
          : source === "camera"
            ? services?.captureImage
            : services?.selectImage;
      if (readOnly || !picker) return;
      setBusy(source);
      setProcessingError(undefined);
      try {
        const candidate = await picker(question, data);
        let selected = candidate;
        if (candidate !== undefined && !isProcessedImageAttachment(candidate)) {
          if (!services.processImage) throw new AttachmentProcessingError("image-processing-unavailable");
          selected = await services.processImage(candidate, WHO_VA_ATTACHMENT_POLICY.image, question, data);
        }
        if (selected !== undefined) {
          if (!isProcessedImageAttachment(selected))
            throw new AttachmentProcessingError("image-output-invalid");
          if (currentAttachment) await services.removeAttachment?.(currentAttachment);
          onAnswer(selected);
          setRotation(0);
          setZoom(1);
          setVisible(true);
        }
      } catch (error) {
        setProcessingError(attachmentErrorMessage(error, messages));
      } finally {
        setBusy(undefined);
      }
    };

    return (
      <>
        {previewUri && visible && Image ? (
          <View style={questionControlStyles.imageFrame}>
            <Image
              accessibilityLabel={attachment.name ?? messages.selectedImage}
              testID={`question-${question.name}-preview`}
              source={{ uri: previewUri }}
              style={[
                questionControlStyles.image,
                { transform: [{ rotate: `${rotation}deg` }, { scale: zoom }] }
              ]}
            />
          </View>
        ) : null}
        {attachment.name ? (
          <PrimitiveText style={questionControlStyles.attachmentName}>{attachment.name}</PrimitiveText>
        ) : null}
        {processingError ? (
          <PrimitiveText accessibilityRole="alert" style={questionControlStyles.attachmentError}>
            {processingError}
          </PrimitiveText>
        ) : null}
        {!services?.captureImage && !services?.selectImage && !services?.captureDrawing ? (
          <PrimitiveText
            nativeID={`question-${question.name}-unavailable`}
            style={questionControlStyles.hint}
            testID={`question-${question.name}-unavailable`}
          >
            {messages.imageUnavailable}
          </PrimitiveText>
        ) : null}
        <View style={questionControlStyles.actions}>
          {drawMode ? (
            <Pressable
              accessibilityRole="button"
              aria-invalid={issues.length > 0 || undefined}
              testID={`question-${question.name}-draw`}
              disabled={readOnly || !services?.captureDrawing || busy != null}
              style={[
                questionControlStyles.button,
                issues.length > 0 && questionControlStyles.buttonError,
                (readOnly || !services?.captureDrawing || busy != null) &&
                  questionControlStyles.buttonDisabled
              ]}
              onPress={() => void choose("draw")}
            >
              <PrimitiveText style={questionControlStyles.buttonText}>
                {drawMode === "signature"
                  ? attachment.uri
                    ? messages.reSign
                    : messages.sign
                  : attachment.uri
                    ? messages.redraw
                    : messages.draw}
              </PrimitiveText>
            </Pressable>
          ) : null}
          <Pressable
            accessibilityRole="button"
            aria-describedby={
              !services?.captureImage && !services?.selectImage
                ? `question-${question.name}-unavailable`
                : undefined
            }
            aria-invalid={issues.length > 0 || undefined}
            disabled={readOnly || !services?.captureImage || busy != null || Boolean(drawMode)}
            style={[
              questionControlStyles.button,
              issues.length > 0 && questionControlStyles.buttonError,
              (readOnly || !services?.captureImage || busy != null || Boolean(drawMode)) &&
                questionControlStyles.buttonDisabled,
              Boolean(drawMode) && questionControlStyles.hidden
            ]}
            onPress={() => void choose("camera")}
          >
            <PrimitiveText style={questionControlStyles.buttonText}>
              {busy === "camera" ? messages.openingCamera : messages.camera}
            </PrimitiveText>
          </Pressable>
          <Pressable
            accessibilityRole="button"
            aria-invalid={issues.length > 0 || undefined}
            disabled={readOnly || !services?.selectImage || busy != null || Boolean(drawMode)}
            style={[
              questionControlStyles.button,
              questionControlStyles.buttonSecondary,
              issues.length > 0 && questionControlStyles.buttonSecondaryError,
              (readOnly || !services?.selectImage || busy != null || Boolean(drawMode)) &&
                questionControlStyles.buttonDisabled,
              Boolean(drawMode) && questionControlStyles.hidden
            ]}
            onPress={() => void choose("library")}
          >
            <PrimitiveText style={questionControlStyles.buttonTextSecondary}>
              {busy === "library"
                ? messages.openingImages
                : attachment.uri
                  ? messages.replaceImage
                  : messages.chooseImage}
            </PrimitiveText>
          </Pressable>
          {attachment.uri ? (
            <>
              <Pressable
                accessibilityRole="button"
                style={[questionControlStyles.button, questionControlStyles.buttonSecondary]}
                onPress={() => setVisible((current) => !current)}
              >
                <PrimitiveText style={questionControlStyles.buttonTextSecondary}>
                  {visible ? messages.hideImage : messages.viewImage}
                </PrimitiveText>
              </Pressable>
              <Pressable
                accessibilityRole="button"
                style={[questionControlStyles.button, questionControlStyles.buttonSecondary]}
                onPress={() => setRotation((current) => (current + 90) % 360)}
              >
                <PrimitiveText style={questionControlStyles.buttonTextSecondary}>
                  {messages.rotate}
                </PrimitiveText>
              </Pressable>
              <Pressable
                accessibilityRole="button"
                style={[questionControlStyles.button, questionControlStyles.buttonSecondary]}
                onPress={() => setZoom((current) => Math.min(3, current + 0.25))}
              >
                <PrimitiveText style={questionControlStyles.buttonTextSecondary}>
                  {messages.zoomIn}
                </PrimitiveText>
              </Pressable>
              <Pressable
                accessibilityRole="button"
                style={[questionControlStyles.button, questionControlStyles.buttonSecondary]}
                onPress={() => setZoom((current) => Math.max(0.5, current - 0.25))}
              >
                <PrimitiveText style={questionControlStyles.buttonTextSecondary}>
                  {messages.zoomOut}
                </PrimitiveText>
              </Pressable>
              <Pressable
                accessibilityRole="button"
                disabled={readOnly}
                style={[
                  questionControlStyles.button,
                  questionControlStyles.buttonDanger,
                  readOnly && questionControlStyles.buttonDisabled
                ]}
                onPress={() => {
                  if (readOnly) return;
                  if (currentAttachment) void services.removeAttachment?.(currentAttachment);
                  onAnswer(undefined);
                }}
              >
                <PrimitiveText style={questionControlStyles.buttonTextDanger}>
                  {messages.removeImage}
                </PrimitiveText>
              </Pressable>
            </>
          ) : null}
        </View>
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
    const [busy, setBusy] = useState(false);
    const [processingError, setProcessingError] = useState<string>();
    const attachment = attachmentDetails(value);
    const readOnly = question.readOnly;
    const services = { ...primitives.platform, ...platform };
    const currentAttachment = attachmentReference(value);
    const acceptsImages = hasAppearance(question, "image-or-pdf");
    const acceptedMimeTypes = acceptsImages
      ? [
          ...WHO_VA_ATTACHMENT_POLICY.image.acceptedMimeTypes,
          ...WHO_VA_ATTACHMENT_POLICY.pdf.acceptedMimeTypes
        ]
      : [...WHO_VA_ATTACHMENT_POLICY.pdf.acceptedMimeTypes];
    const attachmentLabel = acceptsImages ? messages.attachment : messages.pdf;
    return (
      <>
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
        <View style={questionControlStyles.actions}>
          <Pressable
            accessibilityRole="button"
            aria-describedby={!services?.selectFile ? `question-${question.name}-unavailable` : undefined}
            testID={`question-${question.name}`}
            aria-invalid={issues.length > 0 || undefined}
            disabled={readOnly || !services?.selectFile || busy}
            style={[
              questionControlStyles.button,
              issues.length > 0 && questionControlStyles.buttonError,
              (readOnly || !services?.selectFile || busy) && questionControlStyles.buttonDisabled
            ]}
            onPress={async () => {
              if (readOnly || !services?.selectFile) return;
              setBusy(true);
              setProcessingError(undefined);
              try {
                const candidate = await services.selectFile(question, data, acceptedMimeTypes);
                let selected = candidate;
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
                    if (!services.processImage)
                      throw new AttachmentProcessingError("image-processing-unavailable");
                    selected = await services.processImage(
                      candidate,
                      WHO_VA_ATTACHMENT_POLICY.image,
                      question,
                      data
                    );
                  } else {
                    throw new AttachmentProcessingError("pdf-processing-unavailable");
                  }
                }
                if (selected !== undefined) {
                  if (
                    !isRetainedPdfAttachment(selected) &&
                    !(acceptsImages && isProcessedImageAttachment(selected))
                  ) {
                    throw new AttachmentProcessingError(
                      acceptsImages ? "image-output-invalid" : "pdf-render-failed"
                    );
                  }
                  if (currentAttachment) await services.removeAttachment?.(currentAttachment);
                  onAnswer(selected);
                }
              } catch (error) {
                setProcessingError(attachmentErrorMessage(error, messages));
              } finally {
                setBusy(false);
              }
            }}
          >
            <PrimitiveText style={questionControlStyles.buttonText}>
              {busy
                ? messages.openingFiles
                : attachment.uri
                  ? messages.replaceAttachment(attachmentLabel)
                  : messages.chooseAttachment(attachmentLabel)}
            </PrimitiveText>
          </Pressable>
          {processingError ? (
            <PrimitiveText accessibilityRole="alert" style={questionControlStyles.attachmentError}>
              {processingError}
            </PrimitiveText>
          ) : null}
          {attachment.uri ? (
            <Pressable
              accessibilityRole="button"
              disabled={readOnly}
              style={[
                questionControlStyles.button,
                questionControlStyles.buttonDanger,
                readOnly && questionControlStyles.buttonDisabled
              ]}
              onPress={() => {
                if (readOnly) return;
                if (currentAttachment) void services.removeAttachment?.(currentAttachment);
                onAnswer(undefined);
              }}
            >
              <PrimitiveText style={questionControlStyles.buttonTextDanger}>
                {messages.removeAttachment(attachmentLabel)}
              </PrimitiveText>
            </Pressable>
          ) : null}
        </View>
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
