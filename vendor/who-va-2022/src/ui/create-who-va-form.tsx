/**
 * Factory for the shared questionnaire form, coordinating session state,
 * validation, navigation, draft persistence, and platform question controls.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  AnswerValue,
  GoToQuestionResult,
  InstrumentDefinition,
  InstrumentQuestion,
  InstrumentSection,
  SessionSnapshot,
  SubmissionData,
  SubmissionValidationResult,
  ValidationIssue,
  WhoVaDraft,
  WhoVaDraftStore,
  WhoVaSession
} from "../types.js";
import { WHO_VA_DRAFT_SCHEMA_VERSION, createDraftId, decodeWhoVaDraft } from "../draft.js";
import { getInstrumentRuntimeIndex } from "../engine/instrument-index.js";
import { createWhoVaSession } from "../engine/session.js";
import {
  applyCalculations,
  isQuestionRelevantWithCalculatedData,
  validateAnswer
} from "../engine/validation.js";
import { localeFromLanguageName, resolveUiMessages, type WhoVaUiTranslations } from "../i18n.js";
import { WHO_VA_BUILT_IN_UI_TRANSLATIONS } from "../languages/ui.js";
import { WHO_VA_FORM_VERSION } from "../version.js";
import { englishAlongside, plainText } from "./localize.js";
import { createRichText } from "./rich-text-view.js";
import { createSectionNavigation, type SectionNavItem } from "./section-navigation.js";
import { createProblemsDialog, type ProblemRow } from "./problems-dialog.js";
import {
  ageDetail,
  agreesWithSuggestion,
  boundaryFix,
  deriveAge,
  ageSuggestions,
  narrationLanguageSuggestion,
  type AgeSuggestion,
  type AssistKind
} from "./assists.js";
import {
  createWhoVaQuestionControls,
  flushPendingAnswers,
  questionControlStyles,
  type WhoVaPlatformServices
} from "./question-controls.js";
import {
  FooterIcon,
  formStyles as styles,
  hasAnswer,
  instructionLabel,
  interpolateSubmissionReferences,
  interviewerQuestionLabel,
  localized,
  localizedRich,
  prefersReducedMotion,
  previewAnswer,
  splitQuestionCode
} from "./form-presentation.js";

export type { WhoVaPlatformServices } from "./question-controls.js";

interface WhoVaFormCommonProps {
  locale?: string;
  /**
   * Form UI strings per locale. Unset, the package's built-in packs (hi, fr)
   * apply; a supplied value (even `{}`) replaces them. Missing strings fall
   * back to English one by one.
   */
  uiTranslations?: WhoVaUiTranslations;
  showSourceGuidance?: boolean;
  /**
   * Show the English beneath translated question labels, hints and choice
   * labels, so an interviewer can check the translation against it.
   */
  showEnglish?: boolean;
  /**
   * Show each question's WHO code (`Id10010b`) as a small chip beside its
   * label. On by default: coders read by code, interviewers by text, and the
   * chip serves both without leading every label with the code.
   */
  showQuestionCodes?: boolean;
  platform?: WhoVaPlatformServices;
  /**
   * Tighten repeated prompts for a phone: a question whose prompt repeats the one above it (an audio question
   * and its typed twin) shows the prompt once, and a long interviewer instruction shrinks to one line once it
   * has been shown (tap to open it again). Off by default, so existing hosts render as before.
   */
  condensePrompts?: boolean;
  draftId?: string;
  draftStore?: WhoVaDraftStore;
  lockedQuestionNames?: Iterable<string>;
  /** Custom web theme variables to carry into the modal section drawer portal. */
  portalThemeStyle?: unknown;
  onReady?: (session: WhoVaSession) => void;
  onChange?: (data: SubmissionData, snapshot: SessionSnapshot) => void;
  onValidation?: (issues: ValidationIssue[]) => void;
  onDraftSaved?: (draft: WhoVaDraft) => void;
  onDraftError?: (error: Error) => void;
  /**
   * Fires once the initial draft restore has settled -- after the mount-time
   * load from `draftStore` (if any) has applied its data, found nothing, or
   * failed. `status` is "restored" when saved data was applied, "empty" when
   * there was no draft store or no matching draft, and "error" when the load
   * failed (autosave then stays off for the rest of this mount).
   */
  onDraftRestored?: (result: { status: "restored" | "empty" | "error" }) => void;
  onDraftController?: (controller: WhoVaDraftController | undefined) => void;
  autoSaveDraftOnChange?: boolean;
  autoSaveDraftIntervalMs?: number | false;
  onInstrumentError?: (error: Error) => void;
  onComplete?: (result: SubmissionValidationResult) => void;
  /**
   * A phone's bottom bar: Back and Next/Complete only, on one line, fixed
   * under the questions. Save draft and Preview answers are then the host's
   * to offer (draft controller `saveDraft` and `openPreview`).
   */
  compactFooter?: boolean;
  /** System bar insets, for the overlays (Sections drawer, problems list) that draw behind them. */
  safeInsets?: { top: number; bottom: number };
  /**
   * Problems the host knows that the form cannot (the server refused the
   * interview). A row naming a `question` can be jumped to; one without is a
   * general note. They join the form's own validation issues in the problems
   * list and drop out once the named answer changes.
   */
  serverProblems?: ReadonlyArray<{ question?: string; message: string }>;
  /** The number of problems the list holds, each time it changes. */
  onProblemsChange?: (count: number) => void;
}

export type WhoVaFormProps = WhoVaFormCommonProps &
  (
    | { session: WhoVaSession; instrument: InstrumentDefinition; initialData?: never }
    | { session?: never; instrument?: InstrumentDefinition; initialData?: SubmissionData }
  );

export interface WhoVaDraftController {
  draftId: string;
  saveDraft(): Promise<void>;
  /** Open the problems list (form issues plus the host's `serverProblems`). */
  showProblems(): void;
  /** Open the section that shows `name`, scroll to it, focus and highlight it. */
  goToQuestion(name: string): GoToQuestionResult;
  /** Show the answer preview. */
  openPreview(): void;
}

export interface WhoVaPrimitiveSet {
  View: React.ElementType;
  Text: React.ElementType;
  TextInput: React.ElementType;
  DateInput?: React.ElementType;
  /** A native select (web); the month of a date falls back to a numeric box without it. */
  Select?: React.ElementType;
  /** Select primitive reserved for partial date selectors. */
  PartialSelect?: React.ElementType;
  Pressable: React.ElementType;
  /** Plays a resolved saved audio attachment. */
  AudioPlayer?: React.ComponentType<{
    uri: string;
    accessibilityLabel: string;
    onError: () => void;
  }>;
  ScrollView: React.ElementType;
  Image?: React.ElementType;
  /** See SectionNavPrimitives.Modal: hosts the section drawer above the page. */
  Modal?: React.ElementType;
  Svg?: React.ElementType;
  SvgCircle?: React.ElementType;
  SvgPath?: React.ElementType;
  platform?: WhoVaPlatformServices;
  draftStore?: WhoVaDraftStore;
  navigation?: WhoVaNavigationAdapter;
  scrollToQuestion?: (questionNode: unknown, scrollViewNode: unknown, y: number) => void;
  /** Move assistive-technology focus to a node (native; the web focuses the DOM element itself). */
  focusNode?: (node: unknown) => void;
}

type FormView = "form" | "preview";
type DraftStatus = "idle" | "saving" | "saved" | "error";
/**
 * Form-width breakpoints (the form's own width, not the window's). Below
 * MEDIUM the section rail and the label-left question layout give way to the
 * horizontal stepper, drawer and stacked labels; below COMPACT the footer
 * labels shrink so the four buttons still fit one row.
 */
const MEDIUM_FORM_WIDTH = 900;
const COMPACT_FORM_WIDTH = 600;
type SectionProgressStatus = "empty" | "started" | "complete";

function isAnswerableQuestion(question: InstrumentQuestion): boolean {
  return !["calculated", "note", "system"].includes(question.control);
}

function sectionStatus({
  draftIssues,
  instrument,
  locale,
  calculated,
  messages,
  section,
  snapshot
}: {
  draftIssues: Record<string, ValidationIssue>;
  instrument: InstrumentDefinition;
  locale: string;
  calculated: SubmissionData;
  messages: ReturnType<typeof resolveUiMessages>;
  section: InstrumentSection;
  snapshot: SessionSnapshot;
}): SectionProgressStatus {
  const runtimeIndex = getInstrumentRuntimeIndex(instrument);
  const questions = (runtimeIndex.questionsBySection.get(section.name) ?? []).filter(
    (question) =>
      isAnswerableQuestion(question) && isQuestionRelevantWithCalculatedData(instrument, question, calculated)
  );
  if (!questions.length) return "empty";

  const answered = questions.filter((question) => hasAnswer(snapshot.data[question.name]));
  if (!answered.length) return "empty";

  const issueQuestionNames = new Set([
    ...snapshot.issues.map((issue) => issue.question),
    ...Object.values(draftIssues).map((issue) => issue.question)
  ]);
  const hasKnownIssue = questions.some((question) => issueQuestionNames.has(question.name));
  const hasValidationIssue = questions.some((question) =>
    validateAnswer(
      question,
      snapshot.data[question.name],
      calculated,
      locale,
      messages,
      runtimeIndex.choiceValuesByQuestionName.get(question.name)
    ).some((issue) => issue.code !== "required" || hasAnswer(snapshot.data[issue.question]))
  );
  const requiredQuestions = questions.filter((question) => question.required);
  const requiredComplete = requiredQuestions.every((question) => hasAnswer(snapshot.data[question.name]));

  return requiredComplete && !hasKnownIssue && !hasValidationIssue ? "complete" : "started";
}

function sectionStatuses({
  draftIssues,
  instrument,
  locale,
  messages,
  snapshot
}: {
  draftIssues: Record<string, ValidationIssue>;
  instrument: InstrumentDefinition;
  locale: string;
  messages: ReturnType<typeof resolveUiMessages>;
  snapshot: SessionSnapshot;
}): ReadonlyMap<string, SectionProgressStatus> {
  // One calculation pass for all sections, not one per section.
  const calculated = applyCalculations(instrument, snapshot.data);
  return new Map(
    snapshot.visibleSections.map((section) => [
      section.name,
      sectionStatus({ draftIssues, instrument, locale, calculated, messages, section, snapshot })
    ])
  );
}

/**
 * The visible sections as stepper items. Depth counts the ancestors that are
 * themselves pages listed earlier, so nesting reads as indentation. Any other
 * ancestor -- one that is not a page (WHO's "deceased_CRVS" wrapper), or one
 * the engine pages after its children (WHO's "consented", whose own three
 * questions come last) -- becomes a plain heading above its first visible
 * descendant; the outermost such ancestor names the heading.
 */
function sectionNavItems({
  instrument,
  issueSectionNames,
  locale,
  sectionProgress,
  snapshot
}: {
  instrument: InstrumentDefinition;
  issueSectionNames: ReadonlySet<string>;
  locale: string;
  sectionProgress: ReadonlyMap<string, SectionProgressStatus>;
  snapshot: SessionSnapshot;
}): SectionNavItem[] {
  const byName = new Map(instrument.sections.map((section) => [section.name, section]));
  const position = new Map(snapshot.visibleSections.map((section, index) => [section.name, index]));
  const headed = new Set<string>();
  return snapshot.visibleSections.map((section, index) => {
    let depth = 0;
    let groupLabel: string | undefined;
    for (let parent = section.parent; parent; parent = byName.get(parent)?.parent) {
      const parentIndex = position.get(parent);
      if (parentIndex !== undefined && parentIndex < index) depth += 1;
      else if (!headed.has(parent)) {
        headed.add(parent);
        const parentSection = byName.get(parent);
        if (parentSection) groupLabel = localized(parentSection.label, locale, parent);
      }
    }
    return {
      name: section.name,
      label: `${index + 1}. ${localized(section.label, locale, section.name)}`,
      status: issueSectionNames.has(section.name) ? "issues" : (sectionProgress.get(section.name) ?? "empty"),
      active: section.name === snapshot.currentSection.name,
      depth,
      ...(groupLabel ? { groupLabel } : {})
    };
  });
}

export interface WhoVaNavigationState {
  instrumentId: string;
  draftId: string;
  currentSection: string;
  view: FormView;
  data?: SubmissionData;
}

export interface WhoVaNavigationAdapter {
  read(): WhoVaNavigationState | undefined;
  replace(state: WhoVaNavigationState): void;
  push(state: WhoVaNavigationState): void;
  back(): void;
  subscribe(listener: (state: WhoVaNavigationState | undefined) => void): () => void;
}

export function createWhoVaForm(
  primitives: WhoVaPrimitiveSet,
  loadDefaultInstrument?: () => Promise<InstrumentDefinition>
): React.ComponentType<WhoVaFormProps> {
  const { View, Text, Pressable, ScrollView } = primitives;
  // Labels, hints, guidance and choice labels may carry ODK's inline markup;
  // 337 of the WHO guidance fields do. The presentation layer used to strip it,
  // discarding the distinctions the form author drew, so every user-facing
  // text field now renders through this instead.
  const RichText = createRichText(Text);
  const svgPrimitives =
    primitives.Svg && primitives.SvgCircle && primitives.SvgPath
      ? { Svg: primitives.Svg, SvgCircle: primitives.SvgCircle, SvgPath: primitives.SvgPath }
      : undefined;
  const { SectionRail, SectionHeaderBar, SectionDrawer } = createSectionNavigation({
    View,
    Text,
    Pressable,
    ScrollView,
    Modal: primitives.Modal
  });
  const ProblemsDialog = createProblemsDialog({
    View,
    Text,
    Pressable,
    ScrollView,
    Modal: primitives.Modal
  });
  const questionControls = createWhoVaQuestionControls({
    View,
    Text,
    RichText,
    TextInput: primitives.TextInput,
    DateInput: primitives.DateInput,
    Select: primitives.Select,
    PartialSelect: primitives.PartialSelect,
    Pressable,
    AudioPlayer: primitives.AudioPlayer,
    Image: primitives.Image,
    platform: primitives.platform
  });

  // The icons decorate a visible text label, so a primitive set without SVG
  // simply shows the label alone.
  const saveDraftIcon = svgPrimitives ? <FooterIcon name="save" primitives={svgPrimitives} /> : null;
  const previewIcon = svgPrimitives ? <FooterIcon name="preview" primitives={svgPrimitives} /> : null;
  const nextIcon = svgPrimitives ? <FooterIcon name="next" primitives={svgPrimitives} /> : null;

  /**
   * Back, Save draft, Preview answers, Next: one row of four equal-width
   * buttons at every form width (labels wrap on a narrow phone rather than
   * the row splitting in two). Back and Next are the sequential controls; the
   * section rail and drawer are the random-access ones. The row carries
   * testID "form-footer" so a host can position it (DigitVA sticks it to the
   * bottom of a phone viewport).
   *
   * `compact` (a phone): a ~56dp bar of Back and Next/Complete only, labels
   * on one line; Save draft and Preview answers move to the host's menu.
   */
  function FormFooter({
    canGoBack,
    canGoForward,
    canSave,
    compact,
    draftStatus,
    messages,
    narrow,
    onBack,
    onNext,
    onPreview,
    onSave
  }: {
    canGoBack: boolean;
    canGoForward: boolean;
    canSave: boolean;
    compact: boolean;
    draftStatus: DraftStatus;
    messages: ReturnType<typeof resolveUiMessages>;
    narrow: boolean;
    onBack: () => void;
    onNext: () => void;
    onPreview: () => void;
    onSave: () => void;
  }) {
    const saving = draftStatus === "saving";
    const secondaryText = [
      questionControlStyles.buttonTextSecondary,
      styles.navText,
      narrow && styles.navSmallText
    ];
    const lineProps = compact ? { numberOfLines: 1 } : {};
    return (
      <View style={compact ? styles.footerBar : styles.footer} testID="form-footer">
        <Pressable
          accessibilityRole="button"
          disabled={!canGoBack}
          style={[
            questionControlStyles.button,
            questionControlStyles.buttonSecondary,
            styles.navButton,
            !canGoBack && questionControlStyles.buttonDisabled
          ]}
          onPress={onBack}
        >
          <Text {...lineProps} style={secondaryText}>
            {messages.back}
          </Text>
        </Pressable>
        {compact ? null : (
          <Pressable
            accessibilityRole="button"
            disabled={!canSave || saving}
            style={[
              questionControlStyles.button,
              questionControlStyles.buttonSecondary,
              styles.navButton,
              (!canSave || saving) && questionControlStyles.buttonDisabled
            ]}
            onPress={onSave}
            accessibilityLabel={saving ? messages.saving : messages.saveDraft}
          >
            {saveDraftIcon}
            <Text style={secondaryText}>{saving ? messages.saving : messages.saveDraft}</Text>
          </Pressable>
        )}
        {compact ? null : (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={messages.previewAnswers}
            style={[questionControlStyles.button, questionControlStyles.buttonSecondary, styles.navButton]}
            onPress={onPreview}
          >
            {previewIcon}
            <Text style={secondaryText}>{messages.previewAnswers}</Text>
          </Pressable>
        )}
        <Pressable
          accessibilityRole="button"
          style={[questionControlStyles.button, styles.navButton]}
          onPress={onNext}
        >
          <Text {...lineProps} style={[questionControlStyles.buttonText, styles.navText, narrow && styles.navSmallText]}>
            {canGoForward ? messages.next : messages.complete}
          </Text>
          {nextIcon}
        </Pressable>
      </View>
    );
  }

  /** What an assist says under a question: a hint, a confirmation, or a one-tap boundary fix. */
  interface AssistNotice {
    key: string;
    hint?: string;
    confirm?: { text: string; keep: string; use: string };
    fix?: { text: string; action: string };
  }

  /** The voice-typing tip under the typed narrative (Id10476). */
  function NarrativeTip({ name, text }: { name: string; text: string }) {
    return name === "Id10476" ? (
      <Text style={styles.hint} testID="narrative-voice-tip">
        {text}
      </Text>
    ) : null;
  }

  function FocusNotice({ text }: { text: string }) {
    return text ? (
      <Text accessibilityLiveRegion="polite" style={styles.assistBox} testID="focus-notice">
        {text}
      </Text>
    ) : null;
  }

  /** The fix, confirmation and hint an assist shows under a question. */
  function AssistRows({
    assist,
    name,
    onAssist
  }: {
    assist: AssistNotice | undefined;
    name: string;
    onAssist: (action: "keep" | "use" | "fix", name: string) => void;
  }) {
    if (!assist) return null;
    const question = { name };
    return (
      <>
            {assist.fix ? (
              <View style={styles.assistBox} testID={`assist-fix-${question.name}`}>
                <Text style={styles.assistText}>{assist.fix.text}</Text>
                <Pressable
                  accessibilityRole="button"
                  onPress={() => onAssist("fix", question.name)}
                  style={styles.assistButton}
                  testID={`assist-fix-action-${question.name}`}
                >
                  <Text style={styles.assistButtonText}>{assist.fix.action}</Text>
                </Pressable>
              </View>
            ) : null}
            {assist.confirm ? (
              <View style={styles.assistBox} testID={`assist-confirm-${question.name}`}>
                <Text accessibilityLiveRegion="polite" style={styles.assistText}>
                  {assist.confirm.text}
                </Text>
                <View style={styles.assistButtons}>
                  <Pressable
                    accessibilityRole="button"
                    onPress={() => onAssist("keep", question.name)}
                    style={styles.assistButton}
                    testID={`assist-keep-${question.name}`}
                  >
                    <Text style={styles.assistButtonText}>{assist.confirm.keep}</Text>
                  </Pressable>
                  <Pressable
                    accessibilityRole="button"
                    onPress={() => onAssist("use", question.name)}
                    style={styles.assistButton}
                    testID={`assist-use-${question.name}`}
                  >
                    <Text style={styles.assistButtonText}>{assist.confirm.use}</Text>
                  </Pressable>
                </View>
              </View>
            ) : null}
            {assist.hint ? (
              <Text style={styles.assistHint} testID={`assist-hint-${question.name}`}>
                {assist.hint}
              </Text>
            ) : null}
      </>
    );
  }

  interface QuestionRowProps {
    assist: AssistNotice | undefined;
    highlighted: boolean;
    onAssist: (action: "keep" | "use" | "fix", name: string) => void;
    choiceColumns: number;
    code: string;
    data: SubmissionData;
    guidance: string;
    hint: string;
    hintEnglish: string;
    instruction: boolean;
    /** The prompt is the same as the question above it: shown there, not repeated. */
    repeatedPrompt: boolean;
    condensePrompts: boolean;
    issues: ValidationIssue[];
    label: string;
    labelEnglish: string;
    locale: string;
    messages: ReturnType<typeof resolveUiMessages>;
    onAnswer: (value: AnswerValue | undefined) => void;
    onDraftIssue: (questionName: string, issue: ValidationIssue | undefined) => void;
    platform: WhoVaPlatformServices | undefined;
    question: InstrumentQuestion;
    registerNode: (name: string, node: unknown) => void;
    registerPosition: (name: string, y: number) => void;
    showEnglish: boolean | undefined;
    showQuestionCodes: boolean;
    splitLayout: boolean;
    value: AnswerValue | undefined;
  }

  /**
   * The message shown under the question itself. It sits beneath the label,
   * so it never repeats it: a required-empty issue becomes the short
   * sentence, and any other message loses the leading label the engine put
   * there. Payloads, summaries and the section list keep the full message.
   */
  function inlineIssueMessage(
    issue: ValidationIssue,
    label: string,
    messages: ReturnType<typeof resolveUiMessages>
  ): string {
    if (issue.code === "required") return messages.requiredShort;
    const message = splitQuestionCode(issue.message).text;
    const plain = plainText(label);
    if (plain && message.startsWith(plain)) {
      const rest = message.slice(plain.length).trim();
      if (rest) return rest.charAt(0).toUpperCase() + rest.slice(1);
    }
    return message;
  }

  /** Controls that hand the whole answer set to a platform service and so must see fresh `data`. */
  const DATA_DEPENDENT_CONTROLS = new Set(["audio", "barcode", "date", "file", "geopoint", "image"]);

  /**
   * One question. Memoised so that answering one question re-renders that
   * row alone rather than the whole section (164 rows on the largest page);
   * `data` changes on every answer and is compared only for the controls that
   * read it, and `issues` by content.
   */
  /** Instructions longer than this (plain characters) shrink to one line after their first view. */
  const INSTRUCTION_ONE_LINE_AT = 120;
  /** Instructions already shown in this session, so their second showing is the short one. */
  const seenInstructions = new Set<string>();

  const QuestionRow = React.memo(
    function QuestionRow({
      assist,
      highlighted,
      onAssist,
      choiceColumns,
      code,
      data,
      guidance,
      hint,
      hintEnglish,
      instruction,
      repeatedPrompt,
      condensePrompts,
      issues,
      label,
      labelEnglish,
      locale,
      messages,
      onAnswer,
      onDraftIssue,
      platform,
      question,
      registerNode,
      registerPosition,
      showEnglish,
      showQuestionCodes,
      splitLayout,
      value
    }: QuestionRowProps) {
      const hasIssues = issues.length > 0;
      const isQuestionComplete = isAnswerableQuestion(question) && hasAnswer(value) && !hasIssues;
      // A long instruction is read in full the first time it is shown; later it takes one line until tapped.
      const condensable = condensePrompts && instruction && plainText(label).length > INSTRUCTION_ONE_LINE_AT;
      const [collapsed, setCollapsed] = useState(() => condensable && seenInstructions.has(question.name));
      useEffect(() => {
        if (condensable) seenInstructions.add(question.name);
      }, [condensable, question.name]);
      return (
        <View
          ref={(node: unknown) => registerNode(question.name, node)}
          onLayout={(event: { nativeEvent: { layout: { y: number } } }) =>
            registerPosition(question.name, event.nativeEvent.layout.y)
          }
          style={[
            styles.question,
            splitLayout && styles.questionRow,
            question.control === "note" && styles.note,
            hasIssues && styles.questionError,
            highlighted && styles.questionHighlight
          ]}
          testID={`question-card-${question.name}`}
        >
          <View style={[splitLayout && styles.questionLead]}>
            {code && showQuestionCodes && !repeatedPrompt ? (
              <Text style={styles.codeChip} testID={`question-code-${question.name}`}>
                {code}
              </Text>
            ) : null}
            {instruction && !repeatedPrompt ? (
              <Text style={styles.instructionTag} testID={`question-instruction-${question.name}`}>
                {messages.interviewer}
              </Text>
            ) : null}
            {repeatedPrompt ? null : (<View style={styles.questionHeader}>
              <Text
                {...(condensable
                  ? {
                      numberOfLines: collapsed ? 1 : undefined,
                      accessibilityRole: "button",
                      onPress: () => setCollapsed((current) => !current)
                    }
                  : {})}
                style={[
                  styles.label,
                  instruction && styles.labelInstruction,
                  isQuestionComplete && styles.labelWithStatus
                ]}
                {...(instruction
                  ? { "aria-label": `${messages.interviewerInstruction}: ${plainText(label)}` }
                  : {})}
              >
                <RichText source={label} />
                {question.required && question.control !== "note" ? (
                  <Text style={styles.required}> *</Text>
                ) : null}
              </Text>
              {isQuestionComplete ? (
                <View
                  accessibilityLabel="Answered"
                  style={styles.questionStatusBadge}
                  testID={`question-status-${question.name}`}
                >
                  <Text style={styles.questionStatusBadgeText}>✓</Text>
                </View>
              ) : null}
            </View>)}
            {labelEnglish && !repeatedPrompt && !collapsed ? (
              <Text lang="en" style={styles.english} testID={`question-english-${question.name}`}>
                <RichText source={labelEnglish} />
              </Text>
            ) : null}
            {hint ? (
              <Text style={styles.hint}>
                <RichText source={hint} />
              </Text>
            ) : null}
            {hintEnglish ? (
              <Text lang="en" style={styles.english} testID={`question-hint-english-${question.name}`}>
                <RichText source={hintEnglish} />
              </Text>
            ) : null}
            {guidance ? (
              <Text style={styles.guidance}>
                <RichText source={guidance} />
              </Text>
            ) : null}
          </View>
          <View style={[splitLayout && styles.questionBody]}>
            <questionControls.Control
              question={question}
              value={value}
              data={data}
              locale={locale}
              showEnglish={showEnglish}
              messages={messages}
              issues={issues}
              platform={platform}
              onAnswer={onAnswer}
              onDraftIssue={onDraftIssue}
              choiceColumns={choiceColumns}
            />
            <NarrativeTip name={question.name} text={messages.narrativeTip} />
            {issues.map((issue) => (
              <Text
                key={`${issue.code}-${issue.message}`}
                style={styles.error}
                accessibilityLiveRegion="polite"
                role="alert"
              >
                {inlineIssueMessage(issue, label, messages)}
              </Text>
            ))}
            <AssistRows assist={assist} name={question.name} onAssist={onAssist} />
          </View>
        </View>
      );
    },
    (previous, next) => {
      for (const key of Object.keys(next) as (keyof QuestionRowProps)[]) {
        if (key === "data") {
          if (DATA_DEPENDENT_CONTROLS.has(next.question.control) && previous.data !== next.data) return false;
        } else if (key === "assist") {
          if (previous.assist?.key !== next.assist?.key) return false;
        } else if (key === "issues") {
          if (
            previous.issues.length !== next.issues.length ||
            previous.issues.some((issue, index) => issue.message !== next.issues[index]?.message)
          )
            return false;
        } else if (previous[key] !== next[key]) return false;
      }
      return true;
    }
  );

  function ReadyForm(props: WhoVaFormProps & { resolvedInstrument: InstrumentDefinition }) {
    if (props.session && props.initialData !== undefined) {
      throw new Error("WhoVaForm cannot combine a caller-owned session with initialData");
    }
    const { draftStore, onChange, onDraftController, onDraftError, onDraftRestored, onDraftSaved, onReady } =
      props;
    const showQuestionCodes = props.showQuestionCodes ?? true;
    const instrument = props.resolvedInstrument;
    const locale = props.locale ?? localeFromLanguageName(instrument.defaultLanguage) ?? "en";
    const uiTranslations = props.uiTranslations ?? WHO_VA_BUILT_IN_UI_TRANSLATIONS;
    const messages = useMemo(() => resolveUiMessages(locale, uiTranslations), [locale, uiTranslations]);
    const [restoredNavigation] = useState(() => {
      const restored = primitives.navigation?.read();
      if (restored?.instrumentId !== instrument.id) return undefined;
      if (props.draftId && restored.draftId !== props.draftId) return undefined;
      return restored;
    });
    const [session] = useState(() => {
      if (props.session) {
        if (restoredNavigation) {
          if (restoredNavigation.data) props.session.replaceData(restoredNavigation.data);
          props.session.goToSection(restoredNavigation.currentSection);
        }
        return props.session;
      }
      const initialData = props.initialData ?? restoredNavigation?.data;
      return createWhoVaSession(instrument, {
        ...(initialData ? { initialData } : {}),
        ...(props.lockedQuestionNames ? { lockedQuestionNames: props.lockedQuestionNames } : {}),
        ...(restoredNavigation?.currentSection ? { initialSection: restoredNavigation.currentSection } : {}),
        locale,
        uiTranslations
      });
    });
    const [snapshot, setSnapshot] = useState(() => session.getSnapshot());
    const [view, setView] = useState<FormView>(restoredNavigation?.view ?? "form");
    const [draftIssues, setDraftIssues] = useState<Record<string, ValidationIssue>>({});
    const [draftId] = useState(() => props.draftId ?? restoredNavigation?.draftId ?? createDraftId());
    const [draftStatus, setDraftStatus] = useState<DraftStatus>("idle");
    // Gates every save path (autosave-on-change, the autosave interval, a
    // section switch, the manual Save-draft button) behind the mount-time
    // restore: "pending" until settled, "ready" once it is safe to overwrite
    // what draftStore holds, "blocked" forever after a failed load so a
    // draft this mount could not read is never silently replaced. Starts
    // "ready" when navigation already restored the data in place (no load
    // needed).
    const [draftRestoreState, setDraftRestoreState] = useState<"pending" | "ready" | "blocked">(() =>
      restoredNavigation?.data ? "ready" : "pending"
    );
    const [draftRestoreOutcome, setDraftRestoreOutcome] = useState<"restored" | "empty" | "error">();
    const autoSaveDraftIntervalMs = props.autoSaveDraftIntervalMs ?? 20_000;
    const draftCreatedAt = useRef(new Date().toISOString());
    const draftSaveQueue = useRef<Promise<void>>(Promise.resolve());
    const latestDraftSaveRequest = useRef(0);
    const onDraftErrorRef = useRef(onDraftError);
    const onDraftSavedRef = useRef(onDraftSaved);
    const scrollViewRef = useRef<unknown>(null);
    // The form lays itself out by its own width, not the window's: a rail
    // beside the questions when there is room, a header bar and drawer when
    // there is not. Until the first layout the wide layout is assumed.
    const [shellWidth, setShellWidth] = useState(0);
    const medium = shellWidth > 0 && shellWidth < MEDIUM_FORM_WIDTH;
    const compact = shellWidth > 0 && shellWidth < COMPACT_FORM_WIDTH;
    const [drawerOpen, setDrawerOpen] = useState(false);
    const drawerToggleRef = useRef<unknown>(null);
    const questionRefs = useRef<Record<string, unknown>>({});
    const questionPositions = useRef<Record<string, number>>({});
    // The problems list (digitva-man7). `validationIssues` is null until a
    // Complete attempt or the chip asked for a full check; then it is kept
    // fresh as answers change.
    const [problemsOpen, setProblemsOpen] = useState(false);
    const [validationIssues, setValidationIssues] = useState<ValidationIssue[] | null>(null);
    const [focusRequest, setFocusRequest] = useState<{ name: string; stamp: number } | undefined>();
    const [highlighted, setHighlighted] = useState<string>();
    const [focusNotice, setFocusNotice] = useState("");
    const focusRequestRef = useRef(focusRequest);
    focusRequestRef.current = focusRequest;
    // Assists (digitva-12ks, digitva-v5zz): what the form filled itself, and
    // what the interviewer has answered. In memory only; nothing is stored.
    const assistAuto = useRef<Record<string, AnswerValue>>({});
    const assistTouched = useRef(new Set<string>());
    const assistKept = useRef<Record<string, string>>({});
    const [assistTick, setAssistTick] = useState(0);

    useEffect(() => {
      onReady?.(session);
      return session.subscribe((next) => {
        setSnapshot(next);
        setDraftStatus("idle");
        onChange?.(next.data, next);
      });
    }, [onChange, onReady, session]);

    useEffect(() => {
      onDraftErrorRef.current = onDraftError;
      onDraftSavedRef.current = onDraftSaved;
    }, [onDraftError, onDraftSaved]);

    useEffect(() => {
      session.setLocale(locale, uiTranslations);
    }, [locale, uiTranslations, session]);

    useEffect(() => {
      if (props.lockedQuestionNames !== undefined) session.setLockedQuestionNames(props.lockedQuestionNames);
    }, [props.lockedQuestionNames, session]);

    useEffect(() => {
      session.setInstrument(instrument);
    }, [instrument, session]);

    // Loads the draft on first mount whenever a draftStore is configured --
    // not only when the navigation adapter restored a position (digitva-ybz:
    // a host that sets draft-id + draftStore without a navigation adapter
    // never got a load, so the form showed empty over 48 saved answers and
    // the first autosave then overwrote them). Runs once; draftRestoreState
    // leaving "pending" is what stops it from running again.
    useEffect(() => {
      if (draftRestoreState !== "pending") return;
      const store = draftStore ?? primitives.draftStore;
      if (!store) {
        setDraftRestoreState("ready");
        setDraftRestoreOutcome("empty");
        return;
      }
      let active = true;
      const restore = async () => {
        const loadedDraft = await store.load?.(draftId);
        const draft = loadedDraft ? decodeWhoVaDraft(loadedDraft) : undefined;
        if (!active) return;
        const matches =
          Boolean(draft) &&
          draft!.instrumentId === instrument.id &&
          draft!.instrumentVersion === instrument.version;
        if (matches) {
          session.replaceData(draft!.data);
          // Otherwise every save after a restore stamps createdAt with this
          // mount's start time (draftCreatedAt defaults to "now"), drifting
          // the server's original creation time forward on every reload.
          draftCreatedAt.current = draft!.createdAt;
        }
        if (restoredNavigation) {
          session.goToSection(restoredNavigation.currentSection);
          setView(restoredNavigation.view);
        } else if (matches) {
          session.goToSection(draft!.currentSection);
        }
        setDraftRestoreState("ready");
        setDraftRestoreOutcome(matches ? "restored" : "empty");
      };
      void restore().catch((error: unknown) => {
        if (!active) return;
        setDraftRestoreState("blocked");
        onDraftError?.(error instanceof Error ? error : new Error(String(error)));
        setDraftRestoreOutcome("error");
      });
      return () => {
        active = false;
      };
    }, [
      draftId,
      draftRestoreState,
      draftStore,
      instrument.id,
      instrument.version,
      onDraftError,
      restoredNavigation,
      session
    ]);

    // Fires after the restore's own state update has committed, so a host
    // reacting to who-va-ready (e.g. re-enabling the Save-draft button) sees
    // a DOM that already reflects the restored data, not the render still in
    // flight when the restore effect above set state.
    useEffect(() => {
      if (!draftRestoreOutcome) return;
      onDraftRestored?.({ status: draftRestoreOutcome });
    }, [draftRestoreOutcome, onDraftRestored]);

    useEffect(() => {
      primitives.navigation?.replace({
        instrumentId: instrument.id,
        draftId,
        currentSection: snapshot.currentSection.name,
        view,
        data: snapshot.data
      });
    }, [draftId, instrument.id, snapshot.currentSection.name, snapshot.data, view]);

    useEffect(
      () =>
        primitives.navigation?.subscribe((state) => {
          if (!state || state.instrumentId !== instrument.id) return;
          if (state.draftId !== draftId) return;
          if (state.data) {
            session.replaceData(state.data);
            session.goToSection(state.currentSection);
            setView(state.view);
            return;
          }
          const store = draftStore ?? primitives.draftStore;
          void Promise.resolve(store?.load?.(state.draftId))
            .then((loadedDraft) => {
              const draft = loadedDraft ? decodeWhoVaDraft(loadedDraft) : undefined;
              if (draft?.instrumentId === instrument.id && draft.instrumentVersion === instrument.version) {
                session.replaceData(draft.data);
              }
              session.goToSection(state.currentSection);
              setView(state.view);
            })
            .catch((error: unknown) => {
              onDraftError?.(error instanceof Error ? error : new Error(String(error)));
            });
        }),
      [draftId, draftStore, instrument.id, instrument.version, onDraftError, session]
    );

    // One handler per question, created once: a fresh closure per render
    // would re-render every memoised row on every answer.
    const answerHandlers = useRef(new Map<string, (value: AnswerValue | undefined) => void>());
    const answerHandler = (name: string) => {
      let handler = answerHandlers.current.get(name);
      if (!handler) {
        handler = (value) => {
          assistTouched.current.add(name);
          session.setAnswer(name, value);
        };
        answerHandlers.current.set(name, handler);
      }
      return handler;
    };
    const registerQuestionNode = useCallback((name: string, node: unknown) => {
      if (node == null) delete questionRefs.current[name];
      else questionRefs.current[name] = node;
    }, []);
    const registerQuestionPosition = useCallback((name: string, y: number) => {
      questionPositions.current[name] = y;
    }, []);

    // Every way of changing section (Next, Back, rail, drawer, history)
    // lands here: the form scrolls so its top -- stepper and heading -- sits
    // at the top of the page, below the host's fixed bar, and keyboard focus
    // moves to the heading. On the web the window scrolls (host pages rely
    // on that); native scrolls the ScrollView.
    const shellRef = useRef<unknown>(null);
    const headingRef = useRef<unknown>(null);
    const shownSection = useRef(snapshot.currentSection.name);
    const pendingTop = useRef(false);
    useEffect(() => {
      if (view !== "form" || shownSection.current === snapshot.currentSection.name) return;
      shownSection.current = snapshot.currentSection.name;
      // A problems-list "Go" scrolls to its question instead of the top.
      if (focusRequestRef.current) return;
      const shell = shellRef.current;
      const heading = headingRef.current as { focus?: (options: { preventScroll: boolean }) => void } | null;
      // A DOM node scrolls the window; a native view has no scrollIntoView.
      const domShell = shell as { scrollIntoView?: (options: ScrollIntoViewOptions) => void } | null;
      if (typeof domShell?.scrollIntoView === "function") {
        domShell.scrollIntoView({ block: "start", behavior: prefersReducedMotion() ? "auto" : "smooth" });
        heading?.focus?.({ preventScroll: true });
        return;
      }
      // Native: the new page may lay out after this effect, and the old
      // offset (Next sits at the bottom) would survive it, so scroll now and
      // again once the content size has changed.
      const scrollView = scrollViewRef.current as {
        scrollTo?: (options: { animated: boolean; y: number }) => void;
      } | null;
      scrollView?.scrollTo?.({ y: 0, animated: false });
      pendingTop.current = true;
      const settle = setTimeout(() => {
        pendingTop.current = false;
      }, 500);
      primitives.focusNode?.(headingRef.current);
      return () => clearTimeout(settle);
    }, [snapshot.currentSection.name, view]);

    const switchSection = (sectionName: string) => {
      setDrawerOpen(false);
      flushPendingAnswers();
      if (sectionName === snapshot.currentSection.name) return;
      const moved = session.goToSection(sectionName);
      if (!moved) return;
      void saveDraft();
    };

    const setQuestionDraftIssue = useCallback((questionName: string, issue: ValidationIssue | undefined) => {
      setDraftIssues((current) => {
        if (issue) return current[questionName] === issue ? current : { ...current, [questionName]: issue };
        if (!current[questionName]) return current;
        const next = { ...current };
        delete next[questionName];
        return next;
      });
    }, []);

    const saveDraft = useCallback(async () => {
      flushPendingAnswers();
      const store = draftStore ?? primitives.draftStore;
      if (!store) return;
      // Every save path -- autosave-on-change, the autosave interval, a
      // section switch, the manual Save-draft button -- routes through here,
      // so gating this one function is enough: nothing writes while the
      // mount-time restore is still pending, and nothing ever writes again
      // this mount if that restore failed (digitva-ybz).
      if (draftRestoreState !== "ready") return;
      const requestId = ++latestDraftSaveRequest.current;
      const now = new Date().toISOString();
      const current = session.getSnapshot();
      const draft: WhoVaDraft = {
        schemaVersion: WHO_VA_DRAFT_SCHEMA_VERSION,
        formVersion: WHO_VA_FORM_VERSION,
        id: draftId,
        instrumentId: instrument.id,
        instrumentVersion: instrument.version,
        currentSection: current.currentSection.name,
        createdAt: draftCreatedAt.current,
        updatedAt: now,
        data: current.data
      };
      setDraftStatus("saving");
      const save = draftSaveQueue.current.then(async () => {
        try {
          await store.save(draft);
          if (requestId === latestDraftSaveRequest.current) setDraftStatus("saved");
          onDraftSavedRef.current?.(draft);
        } catch (error) {
          const resolved = error instanceof Error ? error : new Error(String(error));
          if (requestId === latestDraftSaveRequest.current) setDraftStatus("error");
          onDraftErrorRef.current?.(resolved);
        }
      });
      draftSaveQueue.current = save;
      await save;
    }, [draftId, draftRestoreState, instrument.id, instrument.version, draftStore, session]);

    // Latest versions of the callbacks the controller hands out, so the
    // controller object itself only changes with the draft.
    const formActions = useRef<{
      goToQuestion: (name: string) => GoToQuestionResult;
      openPreview: () => void;
      showProblems: () => void;
    }>({
      goToQuestion: (name) => ({ status: "unavailable", requested: name }),
      openPreview: () => undefined,
      showProblems: () => undefined
    });
    useEffect(() => {
      onDraftController?.({
        draftId,
        saveDraft,
        goToQuestion: (name) => formActions.current.goToQuestion(name),
        openPreview: () => formActions.current.openPreview(),
        showProblems: () => formActions.current.showProblems()
      });
      return () => onDraftController?.(undefined);
    }, [draftId, onDraftController, saveDraft]);

    useEffect(() => {
      if (!props.autoSaveDraftOnChange) return;
      if (Object.keys(snapshot.data).length === 0) return;
      queueMicrotask(() => void saveDraft());
    }, [props.autoSaveDraftOnChange, saveDraft, snapshot.data]);

    useEffect(() => {
      if (autoSaveDraftIntervalMs === false) return;
      if (autoSaveDraftIntervalMs <= 0) return;
      const timer = setInterval(() => {
        if (Object.keys(session.getSnapshot().data).length === 0) return;
        void saveDraft();
      }, autoSaveDraftIntervalMs);

      return () => clearInterval(timer);
    }, [autoSaveDraftIntervalMs, saveDraft, session]);

    const scrollToIssue = (issue: ValidationIssue | undefined) => {
      if (!issue) return;
      const performScroll = () => {
        const questionNode = questionRefs.current[issue.question];
        const y = questionPositions.current[issue.question] ?? 0;
        if (primitives.scrollToQuestion) {
          primitives.scrollToQuestion(questionNode, scrollViewRef.current, y);
          return;
        }
        const scrollView = scrollViewRef.current as {
          scrollTo?: (options: { animated: boolean; y: number }) => void;
        } | null;
        scrollView?.scrollTo?.({ y: Math.max(0, y - 12), animated: !prefersReducedMotion() });
      };
      if (typeof requestAnimationFrame === "function") requestAnimationFrame(performScroll);
      else setTimeout(performScroll, 0);
    };

    const runtimeIndex = useMemo(() => getInstrumentRuntimeIndex(instrument), [instrument]);
    const plainLabelOf = (question: InstrumentQuestion): string => {
      const text = splitQuestionCode(interviewerQuestionLabel(localized(question.label, locale, question.name))).text;
      const flat = instructionLabel(text).text.replace(/\s+/g, " ").trim();
      return flat.length > 90 ? `${flat.slice(0, 89)}…` : flat;
    };
    const sectionLabelOf = (question: InstrumentQuestion): string => {
      const sectionName = question.sectionPath[question.sectionPath.length - 1];
      const section = sectionName ? runtimeIndex.sectionsByName.get(sectionName) : undefined;
      return section ? localized(section.label, locale, section.name) : "";
    };

    // --- the problems list --------------------------------------------
    const serverProblemInput = props.serverProblems;
    const serverBaseline = useRef<{ source: unknown; values: Record<string, string> }>({
      source: undefined,
      values: {}
    });
    if (serverBaseline.current.source !== serverProblemInput) {
      serverBaseline.current = {
        source: serverProblemInput,
        values: Object.fromEntries(
          (serverProblemInput ?? [])
            .filter((problem) => problem.question)
            .map((problem) => [problem.question!, JSON.stringify(snapshot.data[problem.question!] ?? null)])
        )
      };
    }
    const problemRows = useMemo<ProblemRow[]>(() => {
      const rows: Array<ProblemRow & { order: number }> = [];
      const seen = new Set<string>();
      const add = (name: string | undefined, reason: string, tag: string) => {
        const question = name ? runtimeIndex.questionsByName.get(name) : undefined;
        const key = `${tag}:${name ?? ""}:${reason}`;
        if (seen.has(key)) return;
        seen.add(key);
        rows.push({
          key,
          ...(question ? { name: question.name } : {}),
          section: question ? sectionLabelOf(question) : "",
          question: question ? plainLabelOf(question) : messages.problemGeneral,
          reason,
          order: question ? question.order : Number.MAX_SAFE_INTEGER
        });
      };
      const formIssue = (issue: ValidationIssue, tag: string) => {
        const question = runtimeIndex.questionsByName.get(issue.question);
        add(issue.question, inlineIssueMessage(issue, question ? plainLabelOf(question) : "", messages), tag);
      };
      (validationIssues ?? []).forEach((issue) => formIssue(issue, "v"));
      Object.values(draftIssues).forEach((issue) => formIssue(issue, "d"));
      for (const problem of serverProblemInput ?? []) {
        const stillOpen =
          !problem.question ||
          JSON.stringify(snapshot.data[problem.question] ?? null) === serverBaseline.current.values[problem.question];
        if (stillOpen) add(problem.question, problem.message, "s");
      }
      return rows.sort((a, b) => a.order - b.order).map(({ order: _order, ...row }) => row);
      // eslint-disable-next-line react-hooks/exhaustive-deps -- label helpers only read locale and the instrument
    }, [draftIssues, locale, messages, runtimeIndex, serverProblemInput, snapshot.data, validationIssues]);
    const onProblemsChangeRef = useRef(props.onProblemsChange);
    onProblemsChangeRef.current = props.onProblemsChange;
    useEffect(() => {
      onProblemsChangeRef.current?.(problemRows.length);
    }, [problemRows.length]);

    const checking = validationIssues !== null;
    useEffect(() => {
      if (!checking) return;
      const result = session.validate();
      setValidationIssues(result.valid ? [] : result.issues);
    }, [checking, session, snapshot.data]);

    const showProblems = () => {
      flushPendingAnswers();
      const result = session.validate();
      setValidationIssues(result.valid ? [] : result.issues);
      setProblemsOpen(true);
    };

    const focusQuestion = (node: unknown) => {
      if (typeof HTMLElement !== "undefined" && node instanceof HTMLElement) {
        node
          .querySelector<HTMLElement>("input, textarea, select, button, [tabindex]")
          ?.focus?.({ preventScroll: true });
        return;
      }
      primitives.focusNode?.(node);
    };

    const goToQuestion = (name: string): GoToQuestionResult => {
      flushPendingAnswers();
      const result = session.goToQuestion(name);
      if (result.status === "unavailable") return result;
      setView("form");
      setDrawerOpen(false);
      const target = runtimeIndex.questionsByName.get(result.question);
      setFocusNotice(
        result.status === "hidden" && target ? messages.problemHiddenBy(plainLabelOf(target)) : ""
      );
      setFocusRequest({ name: result.question, stamp: Date.now() });
      void saveDraft();
      return result;
    };

    // After a "Go": once the question has laid out, scroll to it, move focus
    // to it and highlight it for a moment.
    useEffect(() => {
      if (!focusRequest || view !== "form") return;
      const { name } = focusRequest;
      let tries = 0;
      let timer: ReturnType<typeof setTimeout> | undefined;
      const run = () => {
        const node = questionRefs.current[name];
        if (!node) {
          if (tries++ < 12) timer = setTimeout(run, 60);
          else setFocusRequest(undefined);
          return;
        }
        scrollToIssue({ question: name, code: "required", message: "" });
        focusQuestion(node);
        setHighlighted(name);
        setFocusRequest(undefined);
      };
      timer = setTimeout(run, 80);
      return () => {
        if (timer) clearTimeout(timer);
      };
    }, [focusRequest, view]);
    useEffect(() => {
      if (!highlighted) return;
      const timer = setTimeout(() => setHighlighted(undefined), 2500);
      return () => clearTimeout(timer);
    }, [highlighted]);
    useEffect(() => {
      if (!focusNotice) return;
      const timer = setTimeout(() => setFocusNotice(""), 10_000);
      return () => clearTimeout(timer);
    }, [focusNotice]);

    // --- assists: age from the dates, narration language -----------------
    const shownNames = useMemo(() => new Set(snapshot.questions.map((question) => question.name)), [snapshot.questions]);
    const narrationOffered = useMemo(
      () =>
        new Set((runtimeIndex.questionsByName.get("narr_language")?.choices ?? []).map((choice) => choice.value)),
      [runtimeIndex]
    );
    const assistSuggestions = useMemo(() => {
      const found: Record<string, AgeSuggestion> = ageSuggestions(snapshot.data, shownNames);
      if (shownNames.has("narr_language")) {
        const language = narrationLanguageSuggestion(snapshot.data.Id10476, locale, narrationOffered);
        if (language) found.narr_language = { value: language, kind: "suggested" };
      }
      return found;
    }, [locale, narrationOffered, shownNames, snapshot.data]);
    useEffect(() => {
      if (view !== "form" || draftRestoreState !== "ready") return;
      const locked = new Set(snapshot.lockedQuestionNames);
      for (const [name, suggestion] of Object.entries(assistSuggestions)) {
        if (locked.has(name) || assistTouched.current.has(name)) continue;
        const current = snapshot.data[name];
        if (current != null && current !== assistAuto.current[name]) continue;
        if (current === suggestion.value) continue;
        assistAuto.current[name] = suggestion.value;
        try {
          session.setAnswer(name, suggestion.value);
        } catch {
          // A suggestion the question refuses is simply not applied.
        }
      }
    }, [assistSuggestions, draftRestoreState, session, snapshot.data, snapshot.lockedQuestionNames, view]);

    const unitWord = (key: "days" | "months" | "years", count: number): string =>
      `${count} ${key === "days" ? messages.unitDays : key === "months" ? messages.unitMonths : messages.unitYears}`;
    const choiceLabelOf = (name: string, value: AnswerValue | undefined): string => {
      const choice = runtimeIndex.questionsByName.get(name)?.choices?.find((candidate) => candidate.value === value);
      return choice ? localized(choice.label, locale, choice.value) : String(value ?? "");
    };
    const assistNotices = useMemo(() => {
      const notices: Record<string, AssistNotice> = {};
      const hintFor = (kind: AssistKind) =>
        kind === "calculated"
          ? messages.assistCalculated
          : kind === "estimate"
            ? messages.assistEstimate
            : messages.assistSuggested;
      const age = deriveAge(snapshot.data);
      for (const [name, suggestion] of Object.entries(assistSuggestions)) {
        const current = snapshot.data[name];
        if (current == null || name === "narr_language") continue;
        const agrees = agreesWithSuggestion(name, current, suggestion.value);
        if (current === assistAuto.current[name] && agrees) {
          notices[name] = { key: `hint:${suggestion.kind}`, hint: hintFor(suggestion.kind) };
        } else if (!agrees && name !== "age_child_unit" && assistKept.current[name] !== String(suggestion.value)) {
          const detail = age ? ageDetail(age, unitWord) : undefined;
          const suggested =
            name === "age_group"
              ? `${choiceLabelOf(name, suggestion.value)}${detail ? ` (${messages.assistAbout(detail)})` : ""}`
              : name === "age_neonate_days" || name === "age_child_days"
                ? unitWord("days", suggestion.value as number)
                : name === "age_child_months"
                  ? unitWord("months", suggestion.value as number)
                  : unitWord("years", suggestion.value as number);
          const entered = name === "age_group" ? choiceLabelOf(name, current) : String(current);
          notices[name] = {
            key: `confirm:${suggestion.value}:${current}`,
            confirm: {
              text: messages.assistMismatch(suggested, entered),
              keep: messages.assistKeep,
              use: messages.assistUseSuggestion
            }
          };
        }
      }
      for (const name of ["age_child_days", "age_child_years", "age_neonate_days"]) {
        if (!shownNames.has(name)) continue;
        const fix = boundaryFix(name, snapshot.data[name]);
        if (!fix) continue;
        const text =
          fix.messageKey === "fixToNeonate"
            ? messages.fixToNeonate(fix.count)
            : fix.messageKey === "fixToAdult"
              ? messages.fixToAdult(fix.count)
              : fix.messageKey === "fixToChild"
                ? messages.fixToChild(fix.count)
                : messages.fixToMonths;
        const confirmKey = notices[name]?.key ?? "";
        notices[name] = { ...notices[name], key: `${confirmKey}|fix:${fix.messageKey}:${fix.count}`, fix: { text, action: messages[fix.actionKey] } };
      }
      return notices;
      // eslint-disable-next-line react-hooks/exhaustive-deps -- assistTick re-reads the refs after Keep / Use
    }, [assistSuggestions, assistTick, locale, messages, runtimeIndex, shownNames, snapshot.data]);
    const assistNoticesRef = useRef(assistNotices);
    assistNoticesRef.current = assistNotices;
    const onAssist = useCallback(
      (action: "keep" | "use" | "fix", name: string) => {
        const suggestion = assistSuggestionsRef.current[name];
        if (action === "keep" && suggestion) {
          assistKept.current[name] = String(suggestion.value);
        } else if (action === "use" && suggestion) {
          assistTouched.current.delete(name);
          assistAuto.current[name] = suggestion.value;
          try {
            session.setAnswer(name, suggestion.value);
          } catch {
            // see above
          }
        } else if (action === "fix") {
          const fix = boundaryFix(name, session.getSnapshot().data[name]);
          for (const [target, value] of fix?.set ?? []) {
            assistTouched.current.add(target);
            try {
              session.setAnswer(target, value);
            } catch {
              // see above
            }
          }
        }
        setAssistTick((tick) => tick + 1);
      },
      [session]
    );
    const assistSuggestionsRef = useRef(assistSuggestions);
    assistSuggestionsRef.current = assistSuggestions;

    const renderQuestion = (question: InstrumentQuestion, index: number, all: readonly InstrumentQuestion[]) => {
      const draftIssue = draftIssues[question.name];
      const sessionIssues = snapshot.issues.filter(
        (issue) => issue.question === question.name && !(draftIssue && issue.code === "required")
      );
      const issues = draftIssue ? [...sessionIssues, draftIssue] : sessionIssues;
      const { code, text: rawLabel } = splitQuestionCode(
        interviewerQuestionLabel(
          interpolateSubmissionReferences(localizedRich(question.label, locale, question.name), snapshot.data)
        )
      );
      const { instruction, text: label } = instructionLabel(rawLabel);
      const previous = all[index - 1];
      const repeatedPrompt =
        props.condensePrompts === true &&
        previous !== undefined &&
        plainText(label) !== "" &&
        plainText(
          instructionLabel(
            splitQuestionCode(
              interviewerQuestionLabel(
                interpolateSubmissionReferences(localizedRich(previous.label, locale, previous.name), snapshot.data)
              )
            ).text
          ).text
        ) === plainText(label);
      const englishLabel = props.showEnglish ? englishAlongside(question.label, locale) : "";
      const labelEnglish = englishLabel
        ? instructionLabel(
            splitQuestionCode(
              interviewerQuestionLabel(interpolateSubmissionReferences(englishLabel, snapshot.data))
            ).text
          ).text
        : "";
      const englishHint = props.showEnglish ? englishAlongside(question.hint, locale) : "";
      return (
        <QuestionRow
          key={question.name}
          assist={assistNotices[question.name]}
          highlighted={highlighted === question.name}
          onAssist={onAssist}
          choiceColumns={compact ? 2 : medium ? 3 : 4}
          code={code}
          data={snapshot.data}
          guidance={
            props.showSourceGuidance
              ? interpolateSubmissionReferences(localizedRich(question.guidance, locale, ""), snapshot.data)
              : ""
          }
          hint={interpolateSubmissionReferences(localizedRich(question.hint, locale, ""), snapshot.data)}
          hintEnglish={englishHint ? interpolateSubmissionReferences(englishHint, snapshot.data) : ""}
          instruction={instruction}
          repeatedPrompt={repeatedPrompt}
          condensePrompts={props.condensePrompts === true}
          issues={issues}
          label={label}
          labelEnglish={labelEnglish}
          locale={locale}
          messages={messages}
          onAnswer={answerHandler(question.name)}
          onDraftIssue={setQuestionDraftIssue}
          platform={props.platform}
          question={question}
          registerNode={registerQuestionNode}
          registerPosition={registerQuestionPosition}
          showEnglish={props.showEnglish}
          showQuestionCodes={showQuestionCodes}
          splitLayout={!medium && question.control !== "note"}
          value={snapshot.data[question.name]}
        />
      );
    };

    const advance = () => {
      flushPendingAnswers();
      const completing = !snapshot.canGoForward;
      const incompleteDates = snapshot.questions
        .map((question) => draftIssues[question.name])
        .filter((issue): issue is ValidationIssue => issue != null);
      if (incompleteDates.length) {
        void saveDraft();
        props.onValidation?.(incompleteDates);
        if (completing) showProblems();
        scrollToIssue(incompleteDates[0]);
        return;
      }
      const result = session.next();
      void saveDraft();
      if (result.issues.length) {
        props.onValidation?.(result.issues);
        // Complete with errors lists every problem; Next shows this page's inline.
        if (completing) {
          setValidationIssues(result.issues);
          setProblemsOpen(true);
        }
        scrollToIssue(result.issues[0]);
      }
      if (result.status === "completed") props.onComplete?.(result.result);
    };

    const openPreview = () => {
      void saveDraft().then(() => {
        primitives.navigation?.push({
          instrumentId: instrument.id,
          draftId,
          currentSection: snapshot.currentSection.name,
          view: "preview"
        });
        setView("preview");
      });
    };
    formActions.current = { goToQuestion, openPreview, showProblems };

    const answeredQuestions = useMemo(() => {
      if (view !== "preview") return [];
      const calculated = applyCalculations(instrument, snapshot.data);
      return instrument.questions.filter(
        (question) =>
          !["note", "calculated", "system"].includes(question.control) &&
          hasAnswer(snapshot.data[question.name]) &&
          isQuestionRelevantWithCalculatedData(instrument, question, calculated)
      );
    }, [instrument, snapshot.data, view]);

    const previousIssueSections = useRef<ReadonlySet<string>>(new Set());
    const issueSectionNames = useMemo(() => {
      const visibleNames = new Set(snapshot.visibleSections.map((section) => section.name));
      const questionsByName = new Map(instrument.questions.map((question) => [question.name, question]));
      const names = new Set<string>();
      const collect = (issue: ValidationIssue) => {
        const question = questionsByName.get(issue.question);
        const sectionName = [...(question?.sectionPath ?? [])]
          .reverse()
          .find((candidate) => visibleNames.has(candidate));
        if (sectionName) names.add(sectionName);
      };
      snapshot.issues.forEach(collect);
      Object.values(draftIssues).forEach(collect);
      const previous = previousIssueSections.current;
      const same = previous.size === names.size && [...names].every((name) => previous.has(name));
      if (!same) previousIssueSections.current = names;
      return previousIssueSections.current;
    }, [draftIssues, instrument.questions, snapshot.issues, snapshot.visibleSections]);
    // Section status is recomputed on every answer, but the map only changes
    // identity when a status actually changes, so the stepper (memoised on
    // its items) stays out of the render of an ordinary answer.
    const previousProgress = useRef<ReadonlyMap<string, SectionProgressStatus>>(new Map());
    const sectionProgress = useMemo(() => {
      const next = sectionStatuses({ draftIssues, instrument, locale, messages, snapshot });
      const previous = previousProgress.current;
      const same =
        previous.size === next.size && [...next].every(([name, status]) => previous.get(name) === status);
      if (!same) previousProgress.current = next;
      return previousProgress.current;
    }, [draftIssues, instrument, locale, messages, snapshot]);
    const navItems = useMemo<SectionNavItem[]>(
      () =>
        sectionNavItems({
          instrument,
          issueSectionNames,
          locale,
          sectionProgress,
          snapshot
        }),
      // eslint-disable-next-line react-hooks/exhaustive-deps -- only these parts of the snapshot matter
      [
        instrument,
        issueSectionNames,
        locale,
        sectionProgress,
        snapshot.visibleSections,
        snapshot.currentSection.name
      ]
    );
    // Most of the instrument sits behind consent and the age group: three
    // pages are visible before consent, fifteen to twenty after, out of some
    // thirty. While fewer than a third are visible, say that more will come.
    const moreToCome = useMemo(() => {
      const runtimeIndex = getInstrumentRuntimeIndex(instrument);
      const pages = instrument.sections.filter((section) =>
        (runtimeIndex.questionsBySection.get(section.name) ?? []).some(isAnswerableQuestion)
      ).length;
      return snapshot.visibleSections.length * 3 < pages;
    }, [instrument, snapshot.visibleSections.length]);

    if (view === "preview") {
      return (
        <ScrollView
          key="preview"
          style={styles.root}
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
        >
          <Text style={styles.progress}>{messages.answeredQuestions(answeredQuestions.length)}</Text>
          <Text style={styles.sectionTitle}>{messages.answerPreview}</Text>
          <Text style={styles.previewIntro}>{messages.previewIntro}</Text>
          {answeredQuestions.length ? (
            <View style={styles.sectionCard}>
              {answeredQuestions.map((question) => {
                const value = snapshot.data[question.name];
                if (!hasAnswer(value)) return null;
                const { code, text: label } = splitQuestionCode(
                  interviewerQuestionLabel(
                    interpolateSubmissionReferences(
                      localized(question.label, locale, question.name),
                      snapshot.data
                    )
                  )
                );
                return (
                  <View
                    key={question.name}
                    style={styles.question}
                    testID={`preview-answer-${question.name}`}
                  >
                    {code && showQuestionCodes ? <Text style={styles.codeChip}>{code}</Text> : null}
                    <Text style={styles.label}>{label}</Text>
                    <Text style={styles.previewAnswer}>
                      {previewAnswer(question, value, locale, messages)}
                    </Text>
                  </View>
                );
              })}
            </View>
          ) : (
            <Text style={styles.previewEmpty}>{messages.noAnswers}</Text>
          )}
          <View style={styles.navigation}>
            <Pressable
              accessibilityRole="button"
              style={[questionControlStyles.button, questionControlStyles.buttonSecondary]}
              onPress={() => {
                setView("form");
                primitives.navigation?.back();
              }}
            >
              <Text style={questionControlStyles.buttonTextSecondary}>{messages.backToForm}</Text>
            </Pressable>
          </View>
        </ScrollView>
      );
    }

    const navigation = (
      <FormFooter
        canGoBack={snapshot.canGoBack}
        canGoForward={snapshot.canGoForward}
        canSave={Boolean(props.draftStore ?? primitives.draftStore) && draftRestoreState === "ready"}
        compact={props.compactFooter === true}
        draftStatus={draftStatus}
        messages={messages}
        narrow={compact}
        onBack={() => {
          flushPendingAnswers();
          void saveDraft().then(() => {
            session.previous();
          });
        }}
        onNext={advance}
        onPreview={openPreview}
        onSave={() => void saveDraft()}
      />
    );

    const sectionBody = (
      <>
        <Text
          ref={headingRef}
          aria-level={2}
          role="heading"
          style={styles.sectionTitle}
          tabIndex={-1}
          testID="section-heading"
        >
          {localized(snapshot.currentSection.label, locale, snapshot.currentSection.name)}
        </Text>
        <FocusNotice text={focusNotice} />
        <View style={styles.sectionCard}>{snapshot.questions.map((question, index, all) => renderQuestion(question, index, all))}</View>
        {props.compactFooter ? null : navigation}
        <Text style={styles.draftStatus}>
          {draftStatus === "saved"
            ? messages.draftSaved(draftId)
            : draftStatus === "error"
              ? messages.draftSaveFailed
              : messages.draftId(draftId)}
        </Text>
      </>
    );

    return (
      <View
        ref={shellRef}
        style={styles.shell}
        onLayout={(event: { nativeEvent: { layout: { width: number } } }) =>
          setShellWidth(event.nativeEvent.layout.width)
        }
      >
        <ScrollView
          key="form"
          ref={scrollViewRef}
          style={styles.root}
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
          onContentSizeChange={() => {
            if (!pendingTop.current) return;
            pendingTop.current = false;
            (scrollViewRef.current as { scrollTo?: (options: { animated: boolean; y: number }) => void } | null)
              ?.scrollTo?.({ y: 0, animated: false });
          }}
        >
          {medium ? (
            <>
              <SectionHeaderBar
                current={snapshot.currentSectionIndex + 1}
                items={navItems}
                messages={messages}
                moreToCome={moreToCome}
                onOpen={() => setDrawerOpen(true)}
                onSelect={switchSection}
                open={drawerOpen}
                toggleRef={drawerToggleRef}
                total={snapshot.visibleSectionCount}
              />
              {sectionBody}
            </>
          ) : (
            <View style={styles.layoutRow}>
              <SectionRail
                items={navItems}
                messages={messages}
                moreToCome={moreToCome}
                onSelect={switchSection}
              />
              <View style={styles.mainColumn}>
                <Text style={styles.progress}>
                  {messages.sectionProgress(snapshot.currentSectionIndex + 1, snapshot.visibleSectionCount)}
                </Text>
                {sectionBody}
              </View>
            </View>
          )}
        </ScrollView>
        <SectionDrawer
          items={navItems}
          messages={messages}
          moreToCome={moreToCome}
          onClose={() => setDrawerOpen(false)}
          onSelect={switchSection}
          open={medium && drawerOpen}
          portalThemeStyle={props.portalThemeStyle}
          safeInsets={props.safeInsets}
          toggleRef={drawerToggleRef}
        />
        {props.compactFooter ? navigation : null}
        <ProblemsDialog
          safeInsets={props.safeInsets}
          messages={messages}
          onClose={() => setProblemsOpen(false)}
          onGo={(name) => {
            setProblemsOpen(false);
            goToQuestion(name);
          }}
          open={problemsOpen}
          portalThemeStyle={props.portalThemeStyle}
          rows={problemRows}
        />
      </View>
    );
  }

  function Form(props: WhoVaFormProps) {
    const { instrument: providedInstrument, onInstrumentError } = props;
    const [loadedInstrument, setLoadedInstrument] = useState<InstrumentDefinition>();
    const [loadError, setLoadError] = useState<Error>();

    useEffect(() => {
      if (providedInstrument) return;
      let active = true;
      if (!loadDefaultInstrument) {
        const error = new Error("No instrument or default instrument loader was provided");
        queueMicrotask(() => {
          if (!active) return;
          setLoadError(error);
          onInstrumentError?.(error);
        });
        return () => {
          active = false;
        };
      }
      void loadDefaultInstrument()
        .then((instrument) => {
          if (active) setLoadedInstrument(instrument);
        })
        .catch((error: unknown) => {
          if (!active) return;
          const resolved = error instanceof Error ? error : new Error(String(error));
          setLoadError(resolved);
          onInstrumentError?.(resolved);
        });
      return () => {
        active = false;
      };
    }, [onInstrumentError, providedInstrument]);

    const instrument = providedInstrument ?? loadedInstrument;
    if (!instrument) {
      return (
        <View style={styles.root}>
          <View style={styles.content}>
            <Text
              accessibilityLiveRegion="polite"
              role={loadError ? "alert" : undefined}
              style={loadError ? styles.error : styles.progress}
            >
              {loadError ? "The questionnaire could not be loaded." : "Loading questionnaire…"}
            </Text>
          </View>
        </View>
      );
    }
    return <ReadyForm {...props} resolvedInstrument={instrument} />;
  }

  Form.displayName = "WhoVaForm";
  return Form;
}
