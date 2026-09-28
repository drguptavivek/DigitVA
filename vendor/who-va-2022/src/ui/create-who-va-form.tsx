/**
 * Factory for the shared questionnaire form, coordinating session state,
 * validation, navigation, draft persistence, and platform question controls.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  AnswerValue,
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
import { WHO_VA_FORM_VERSION } from "../version.js";
import { englishAlongside, plainText } from "./localize.js";
import { createRichText } from "./rich-text-view.js";
import { createSectionNavigation, type SectionNavItem } from "./section-navigation.js";
import {
  createWhoVaQuestionControls,
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
  draftId?: string;
  draftStore?: WhoVaDraftStore;
  lockedQuestionNames?: Iterable<string>;
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
}

export type WhoVaFormProps = WhoVaFormCommonProps &
  (
    | { session: WhoVaSession; instrument: InstrumentDefinition; initialData?: never }
    | { session?: never; instrument?: InstrumentDefinition; initialData?: SubmissionData }
  );

export interface WhoVaDraftController {
  draftId: string;
  saveDraft(): Promise<void>;
}

export interface WhoVaPrimitiveSet {
  View: React.ElementType;
  Text: React.ElementType;
  TextInput: React.ElementType;
  DateInput?: React.ElementType;
  /** A native select (web); the month of a date falls back to a numeric box without it. */
  Select?: React.ElementType;
  Pressable: React.ElementType;
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
}

type FormView = "form" | "preview";
type DraftStatus = "idle" | "saving" | "saved" | "error";
/**
 * Form-width breakpoints (the form's own width, not the window's). Below
 * MEDIUM the section rail and the label-left question layout give way to the
 * horizontal stepper, drawer and stacked labels; below COMPACT the footer
 * stacks into two rows.
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
  const questionControls = createWhoVaQuestionControls({
    View,
    Text,
    RichText,
    TextInput: primitives.TextInput,
    DateInput: primitives.DateInput,
    Select: primitives.Select,
    Pressable,
    Image: primitives.Image,
    platform: primitives.platform
  });

  // The icons decorate a visible text label, so a primitive set without SVG
  // simply shows the label alone.
  const saveDraftIcon = svgPrimitives ? <FooterIcon name="save" primitives={svgPrimitives} /> : null;
  const previewIcon = svgPrimitives ? <FooterIcon name="preview" primitives={svgPrimitives} /> : null;
  const nextIcon = svgPrimitives ? <FooterIcon name="next" primitives={svgPrimitives} /> : null;

  /**
   * Back, Save draft, Preview answers, Next. Back and Next are the
   * sequential controls; the section rail and drawer are the random-access
   * ones, so the old "<" ">" arrows beside the tab strip, which duplicated
   * Back and Next, are gone. Narrow forms stack a small secondary row (save,
   * preview) above a full-width row of Back and Next.
   */
  function FormFooter({
    canGoBack,
    canGoForward,
    canSave,
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
    draftStatus: DraftStatus;
    messages: ReturnType<typeof resolveUiMessages>;
    narrow: boolean;
    onBack: () => void;
    onNext: () => void;
    onPreview: () => void;
    onSave: () => void;
  }) {
    const saving = draftStatus === "saving";
    const backButton = (
      <Pressable
        accessibilityRole="button"
        disabled={!canGoBack}
        style={[
          questionControlStyles.button,
          questionControlStyles.buttonSecondary,
          styles.navButton,
          narrow && styles.navGrow,
          !canGoBack && questionControlStyles.buttonDisabled
        ]}
        onPress={onBack}
      >
        <Text style={questionControlStyles.buttonTextSecondary}>{messages.back}</Text>
      </Pressable>
    );
    const saveButton = (
      <Pressable
        accessibilityRole="button"
        disabled={!canSave || saving}
        style={[
          questionControlStyles.button,
          questionControlStyles.buttonSecondary,
          styles.navIconButton,
          narrow && styles.navSmallButton,
          (!canSave || saving) && questionControlStyles.buttonDisabled
        ]}
        onPress={onSave}
        accessibilityLabel={saving ? messages.saving : messages.saveDraft}
      >
        {saveDraftIcon}
        <Text style={[questionControlStyles.buttonTextSecondary, narrow && styles.navSmallText]}>
          {saving ? messages.saving : messages.saveDraft}
        </Text>
      </Pressable>
    );
    const previewButton = (
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={messages.previewAnswers}
        style={[
          questionControlStyles.button,
          questionControlStyles.buttonSecondary,
          styles.navIconButton,
          narrow && styles.navSmallButton
        ]}
        onPress={onPreview}
      >
        {previewIcon}
        <Text style={[questionControlStyles.buttonTextSecondary, narrow && styles.navSmallText]}>
          {messages.previewAnswers}
        </Text>
      </Pressable>
    );
    const nextButton = (
      <Pressable
        accessibilityRole="button"
        style={[questionControlStyles.button, styles.navPrimaryButton, narrow && styles.navGrowPrimary]}
        onPress={onNext}
      >
        <Text style={questionControlStyles.buttonText}>
          {canGoForward ? messages.next : messages.complete}
        </Text>
        {nextIcon}
      </Pressable>
    );
    if (!narrow) {
      return (
        <View style={styles.navigation}>
          {backButton}
          {saveButton}
          {previewButton}
          {nextButton}
        </View>
      );
    }
    return (
      <View style={styles.navigationNarrow}>
        <View style={styles.navRowSecondary}>
          {saveButton}
          {previewButton}
        </View>
        <View style={styles.navRowPrimary}>
          {backButton}
          {nextButton}
        </View>
      </View>
    );
  }

  interface QuestionRowProps {
    choiceColumns: number;
    code: string;
    data: SubmissionData;
    guidance: string;
    hint: string;
    hintEnglish: string;
    instruction: boolean;
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
  const QuestionRow = React.memo(
    function QuestionRow({
      choiceColumns,
      code,
      data,
      guidance,
      hint,
      hintEnglish,
      instruction,
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
            hasIssues && styles.questionError
          ]}
          testID={`question-card-${question.name}`}
        >
          <View style={[splitLayout && styles.questionLead]}>
            {code && showQuestionCodes ? (
              <Text style={styles.codeChip} testID={`question-code-${question.name}`}>
                {code}
              </Text>
            ) : null}
            {instruction ? (
              <Text style={styles.instructionTag} testID={`question-instruction-${question.name}`}>
                {messages.interviewer}
              </Text>
            ) : null}
            <View style={styles.questionHeader}>
              <Text
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
            </View>
            {labelEnglish ? (
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
          </View>
        </View>
      );
    },
    (previous, next) => {
      for (const key of Object.keys(next) as (keyof QuestionRowProps)[]) {
        if (key === "data") {
          if (DATA_DEPENDENT_CONTROLS.has(next.question.control) && previous.data !== next.data) return false;
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
    const messages = useMemo(
      () => resolveUiMessages(locale, props.uiTranslations),
      [locale, props.uiTranslations]
    );
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
        ...(props.uiTranslations ? { uiTranslations: props.uiTranslations } : {})
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
      session.setLocale(locale, props.uiTranslations);
    }, [locale, props.uiTranslations, session]);

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
        handler = (value) => session.setAnswer(name, value);
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
    useEffect(() => {
      if (view !== "form" || shownSection.current === snapshot.currentSection.name) return;
      shownSection.current = snapshot.currentSection.name;
      const shell = shellRef.current;
      const heading = headingRef.current as { focus?: (options: { preventScroll: boolean }) => void } | null;
      if (typeof HTMLElement !== "undefined" && shell instanceof HTMLElement) {
        shell.scrollIntoView?.({ block: "start", behavior: prefersReducedMotion() ? "auto" : "smooth" });
        heading?.focus?.({ preventScroll: true });
        return;
      }
      const scrollView = scrollViewRef.current as {
        scrollTo?: (options: { animated: boolean; y: number }) => void;
      } | null;
      scrollView?.scrollTo?.({ y: 0, animated: !prefersReducedMotion() });
    }, [snapshot.currentSection.name, view]);

    const switchSection = (sectionName: string) => {
      setDrawerOpen(false);
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

    useEffect(() => {
      onDraftController?.({ draftId, saveDraft });
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

    const renderQuestion = (question: InstrumentQuestion) => {
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
      const incompleteDates = snapshot.questions
        .map((question) => draftIssues[question.name])
        .filter((issue): issue is ValidationIssue => issue != null);
      if (incompleteDates.length) {
        void saveDraft();
        props.onValidation?.(incompleteDates);
        scrollToIssue(incompleteDates[0]);
        return;
      }
      const result = session.next();
      void saveDraft();
      if (result.issues.length) {
        props.onValidation?.(result.issues);
        scrollToIssue(result.issues[0]);
      }
      if (result.status === "completed") props.onComplete?.(result.result);
    };

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
        draftStatus={draftStatus}
        messages={messages}
        narrow={compact}
        onBack={() => {
          void saveDraft().then(() => {
            session.previous();
          });
        }}
        onNext={advance}
        onPreview={() => {
          void saveDraft().then(() => {
            primitives.navigation?.push({
              instrumentId: instrument.id,
              draftId,
              currentSection: snapshot.currentSection.name,
              view: "preview"
            });
            setView("preview");
          });
        }}
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
        <View style={styles.sectionCard}>{snapshot.questions.map(renderQuestion)}</View>
        {navigation}
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
        >
          {medium ? (
            <>
              <SectionHeaderBar
                current={snapshot.currentSectionIndex + 1}
                items={navItems}
                messages={messages}
                moreToCome={moreToCome}
                onOpen={() => setDrawerOpen(true)}
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
          toggleRef={drawerToggleRef}
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
