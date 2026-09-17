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
import {
  createWhoVaQuestionControls,
  questionControlStyles,
  type WhoVaPlatformServices
} from "./question-controls.js";
import {
  FooterIcon,
  formStyles as styles,
  hasAnswer,
  interpolateSubmissionReferences,
  interviewerQuestionLabel,
  localized,
  previewAnswer
} from "./form-presentation.js";

export type { WhoVaPlatformServices } from "./question-controls.js";

interface WhoVaFormCommonProps {
  locale?: string;
  uiTranslations?: WhoVaUiTranslations;
  showSourceGuidance?: boolean;
  platform?: WhoVaPlatformServices;
  draftId?: string;
  draftStore?: WhoVaDraftStore;
  lockedQuestionNames?: Iterable<string>;
  onReady?: (session: WhoVaSession) => void;
  onChange?: (data: SubmissionData, snapshot: SessionSnapshot) => void;
  onValidation?: (issues: ValidationIssue[]) => void;
  onDraftSaved?: (draft: WhoVaDraft) => void;
  onDraftError?: (error: Error) => void;
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
  Pressable: React.ElementType;
  ScrollView: React.ElementType;
  Image?: React.ElementType;
  Svg?: React.ElementType;
  SvgCircle?: React.ElementType;
  SvgPath?: React.ElementType;
  platform?: WhoVaPlatformServices;
  draftStore?: WhoVaDraftStore;
  navigation?: WhoVaNavigationAdapter;
  scrollToQuestion?: (questionNode: unknown, scrollViewNode: unknown, y: number) => void;
}

type FormView = "form" | "preview";
type SectionProgressStatus = "empty" | "started" | "complete";

function isAnswerableQuestion(question: InstrumentQuestion): boolean {
  return !["calculated", "note", "system"].includes(question.control);
}

function sectionStatus({
  draftIssues,
  instrument,
  locale,
  messages,
  section,
  snapshot
}: {
  draftIssues: Record<string, ValidationIssue>;
  instrument: InstrumentDefinition;
  locale: string;
  messages: ReturnType<typeof resolveUiMessages>;
  section: InstrumentSection;
  snapshot: SessionSnapshot;
}): SectionProgressStatus {
  const runtimeIndex = getInstrumentRuntimeIndex(instrument);
  const calculated = applyCalculations(instrument, snapshot.data);
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
  return new Map(
    snapshot.visibleSections.map((section) => [
      section.name,
      sectionStatus({ draftIssues, instrument, locale, messages, section, snapshot })
    ])
  );
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

function sectionSliderState(snapshot: SessionSnapshot) {
  const activeIndex = Math.max(
    0,
    snapshot.visibleSections.findIndex((section) => section.name === snapshot.currentSection.name)
  );
  const sectionCount = snapshot.visibleSections.length;

  return {
    activeIndex,
    canGoBack: activeIndex > 0,
    canGoForward: activeIndex < sectionCount - 1,
    previousSection: snapshot.visibleSections[activeIndex - 1],
    nextSection: snapshot.visibleSections[activeIndex + 1]
  };
}

export function createWhoVaForm(
  primitives: WhoVaPrimitiveSet,
  loadDefaultInstrument?: () => Promise<InstrumentDefinition>
): React.ComponentType<WhoVaFormProps> {
  const { View, Text, Pressable, ScrollView } = primitives;
  const svgPrimitives =
    primitives.Svg && primitives.SvgCircle && primitives.SvgPath
      ? { Svg: primitives.Svg, SvgCircle: primitives.SvgCircle, SvgPath: primitives.SvgPath }
      : undefined;
  const questionControls = createWhoVaQuestionControls({
    View,
    Text,
    TextInput: primitives.TextInput,
    DateInput: primitives.DateInput,
    Pressable,
    Image: primitives.Image,
    platform: primitives.platform
  });

  function SectionSwitcher({
    issueSectionNames,
    locale,
    messages,
    sectionProgress,
    snapshot,
    switchSection
  }: {
    issueSectionNames: ReadonlySet<string>;
    locale: string;
    messages: ReturnType<typeof resolveUiMessages>;
    sectionProgress: ReadonlyMap<string, SectionProgressStatus>;
    snapshot: SessionSnapshot;
    switchSection: (sectionName: string) => void;
  }) {
    const sectionSlider = sectionSliderState(snapshot);
    const sectionTrackRef = useRef<unknown>(null);

    useEffect(() => {
      const scrollView = sectionTrackRef.current as {
        scrollTo?: (options: { animated: boolean; x: number }) => void;
      } | null;
      scrollView?.scrollTo?.({ x: Math.max(sectionSlider.activeIndex - 1, 0) * 120, animated: true });
    }, [sectionSlider.activeIndex]);

    return (
      <View testID="section-switcher" style={styles.sectionSwitcher}>
        <Pressable
          accessibilityLabel={messages.back}
          accessibilityRole="button"
          disabled={!sectionSlider.canGoBack}
          onPress={() => sectionSlider.previousSection && switchSection(sectionSlider.previousSection.name)}
          style={[styles.sectionSliderButton, !sectionSlider.canGoBack && styles.sectionSliderButtonDisabled]}
        >
          <Text
            style={[
              styles.sectionSliderButtonText,
              !sectionSlider.canGoBack && styles.sectionSliderButtonTextDisabled
            ]}
          >
            {"<"}
          </Text>
        </Pressable>
        <ScrollView
          ref={sectionTrackRef}
          testID="section-slider"
          contentContainerStyle={styles.sectionSwitcherTrack}
          horizontal
          keyboardShouldPersistTaps="handled"
          showsHorizontalScrollIndicator={false}
          style={styles.sectionSwitcherViewport}
        >
          {snapshot.visibleSections.map((section, index) => {
            const isActive = section.name === snapshot.currentSection.name;
            const hasSectionIssues = issueSectionNames.has(section.name);
            const progress = sectionProgress.get(section.name) ?? "empty";
            const isComplete = progress === "complete";
            const isStarted = progress === "started";
            const sectionLabel = `${index + 1}. ${localized(section.label, locale, section.name)}`;
            return (
              <Pressable
                accessibilityLabel={`${sectionLabel}${isComplete ? ", completed" : isStarted ? ", started" : ""}`}
                accessibilityRole="button"
                accessibilityState={{ selected: isActive }}
                testID="section-slider-item"
                aria-invalid={hasSectionIssues || undefined}
                key={section.name}
                onPress={() => switchSection(section.name)}
                style={[
                  styles.sectionButton,
                  isStarted && !hasSectionIssues && styles.sectionButtonStarted,
                  isComplete && !hasSectionIssues && styles.sectionButtonComplete,
                  hasSectionIssues && !isActive && styles.sectionButtonError,
                  isActive && styles.sectionButtonActive
                ]}
              >
                {isComplete || isStarted ? (
                  <View
                    aria-hidden="true"
                    style={[
                      styles.sectionStatusBadge,
                      isStarted && styles.sectionStatusBadgeStarted,
                      isActive && styles.sectionStatusBadgeActive
                    ]}
                    testID={`section-status-${section.name}`}
                  >
                    <Text
                      style={[
                        styles.sectionStatusBadgeText,
                        isStarted && styles.sectionStatusBadgeTextStarted,
                        isActive && styles.sectionStatusBadgeTextActive
                      ]}
                    >
                      {isComplete ? "✓" : "•"}
                    </Text>
                  </View>
                ) : null}
                <Text
                  numberOfLines={2}
                  style={[
                    styles.sectionButtonText,
                    hasSectionIssues && !isActive && styles.sectionButtonTextError,
                    isActive && styles.sectionButtonTextActive
                  ]}
                >
                  {sectionLabel}
                </Text>
              </Pressable>
            );
          })}
        </ScrollView>
        <Pressable
          accessibilityLabel={messages.next}
          accessibilityRole="button"
          disabled={!sectionSlider.canGoForward}
          onPress={() => sectionSlider.nextSection && switchSection(sectionSlider.nextSection.name)}
          style={[
            styles.sectionSliderButton,
            !sectionSlider.canGoForward && styles.sectionSliderButtonDisabled
          ]}
        >
          <Text
            style={[
              styles.sectionSliderButtonText,
              !sectionSlider.canGoForward && styles.sectionSliderButtonTextDisabled
            ]}
          >
            {">"}
          </Text>
        </Pressable>
      </View>
    );
  }

  function ReadyForm(props: WhoVaFormProps & { resolvedInstrument: InstrumentDefinition }) {
    if (props.session && props.initialData !== undefined) {
      throw new Error("WhoVaForm cannot combine a caller-owned session with initialData");
    }
    const { draftStore, onChange, onDraftController, onDraftError, onDraftSaved, onReady } = props;
    const instrument = props.resolvedInstrument;
    const locale = props.locale ?? localeFromLanguageName(instrument.defaultLanguage) ?? "en";
    const messages = useMemo(
      () => resolveUiMessages(locale, props.uiTranslations),
      [locale, props.uiTranslations]
    );
    const saveDraftIcon = svgPrimitives ? (
      <FooterIcon name="save" primitives={svgPrimitives} />
    ) : (
      <Text style={questionControlStyles.buttonTextSecondary}>Save</Text>
    );
    const previewIcon = svgPrimitives ? (
      <FooterIcon name="preview" primitives={svgPrimitives} />
    ) : (
      <Text style={questionControlStyles.buttonTextSecondary}>View</Text>
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
    const [draftStatus, setDraftStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
    const autoSaveDraftIntervalMs = props.autoSaveDraftIntervalMs ?? 20_000;
    const draftCreatedAt = useRef(new Date().toISOString());
    const draftSaveQueue = useRef<Promise<void>>(Promise.resolve());
    const latestDraftSaveRequest = useRef(0);
    const onDraftErrorRef = useRef(onDraftError);
    const onDraftSavedRef = useRef(onDraftSaved);
    const scrollViewRef = useRef<unknown>(null);
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

    useEffect(() => {
      if (!restoredNavigation || restoredNavigation.data) return;
      const store = draftStore ?? primitives.draftStore;
      let active = true;
      const restore = async () => {
        const loadedDraft = await store?.load?.(restoredNavigation.draftId);
        const draft = loadedDraft ? decodeWhoVaDraft(loadedDraft) : undefined;
        if (!active) return;
        if (draft && draft.instrumentId === instrument.id && draft.instrumentVersion === instrument.version) {
          session.replaceData(draft.data);
        }
        session.goToSection(restoredNavigation.currentSection);
        setView(restoredNavigation.view);
      };
      void restore().catch((error: unknown) => {
        if (!active) return;
        onDraftError?.(error instanceof Error ? error : new Error(String(error)));
      });
      return () => {
        active = false;
      };
    }, [instrument.id, instrument.version, draftStore, onDraftError, restoredNavigation, session]);

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

    const answer = (question: InstrumentQuestion, value: AnswerValue | undefined) => {
      session.setAnswer(question.name, value);
    };

    const scrollToTop = () => {
      const scrollView = scrollViewRef.current as {
        scrollTo?: (options: { animated: boolean; y: number }) => void;
      } | null;
      scrollView?.scrollTo?.({ y: 0, animated: true });
    };

    const switchSection = (sectionName: string) => {
      if (sectionName === snapshot.currentSection.name) return;
      const moved = session.goToSection(sectionName);
      if (!moved) return;
      void saveDraft();
      if (typeof requestAnimationFrame === "function") requestAnimationFrame(scrollToTop);
      else setTimeout(scrollToTop, 0);
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
    }, [draftId, instrument.id, instrument.version, draftStore, session]);

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
        scrollView?.scrollTo?.({ y: Math.max(0, y - 12), animated: true });
      };
      if (typeof requestAnimationFrame === "function") requestAnimationFrame(performScroll);
      else setTimeout(performScroll, 0);
    };

    const renderQuestion = (question: InstrumentQuestion) => {
      const value = snapshot.data[question.name];
      const draftIssue = draftIssues[question.name];
      const sessionIssues = snapshot.issues.filter(
        (issue) => issue.question === question.name && !(draftIssue && issue.code === "required")
      );
      const issues = draftIssue ? [...sessionIssues, draftIssue] : sessionIssues;
      const label = interviewerQuestionLabel(
        interpolateSubmissionReferences(localized(question.label, locale, question.name), snapshot.data)
      );
      const hint = interpolateSubmissionReferences(localized(question.hint, locale, ""), snapshot.data);
      const guidance = interpolateSubmissionReferences(
        localized(question.guidance, locale, ""),
        snapshot.data
      );
      const hasIssues = issues.length > 0;
      const isQuestionComplete = isAnswerableQuestion(question) && hasAnswer(value) && !hasIssues;

      const control = (
        <questionControls.Control
          question={question}
          value={value}
          data={snapshot.data}
          locale={locale}
          messages={messages}
          issues={issues}
          platform={props.platform}
          onAnswer={(next) => answer(question, next)}
          onDraftIssue={setQuestionDraftIssue}
        />
      );

      return (
        <View
          key={question.name}
          ref={(node: unknown) => {
            if (node == null) delete questionRefs.current[question.name];
            else questionRefs.current[question.name] = node;
          }}
          onLayout={(event: { nativeEvent: { layout: { y: number } } }) => {
            questionPositions.current[question.name] = event.nativeEvent.layout.y;
          }}
          style={[
            styles.question,
            question.control === "note" && styles.note,
            hasIssues && styles.questionError
          ]}
          testID={`question-card-${question.name}`}
        >
          <View style={styles.questionHeader}>
            <Text style={[styles.label, isQuestionComplete && styles.labelWithStatus]}>
              {label}
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
          {hint ? <Text style={styles.hint}>{hint}</Text> : null}
          {props.showSourceGuidance && guidance ? <Text style={styles.guidance}>{guidance}</Text> : null}
          {control}
          {issues.map((issue) => (
            <Text
              key={`${issue.code}-${issue.message}`}
              style={styles.error}
              accessibilityLiveRegion="polite"
              role="alert"
            >
              {issue.message}
            </Text>
          ))}
        </View>
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
      return names;
    }, [draftIssues, instrument.questions, snapshot.issues, snapshot.visibleSections]);
    const sectionProgress = useMemo(
      () => sectionStatuses({ draftIssues, instrument, locale, messages, snapshot }),
      [draftIssues, instrument, locale, messages, snapshot]
    );

    if (view === "preview") {
      return (
        <ScrollView
          style={styles.root}
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
        >
          <Text style={styles.progress}>{messages.answeredQuestions(answeredQuestions.length)}</Text>
          <Text style={styles.sectionTitle}>{messages.answerPreview}</Text>
          <Text style={styles.previewIntro}>{messages.previewIntro}</Text>
          {answeredQuestions.length ? (
            answeredQuestions.map((question) => {
              const value = snapshot.data[question.name];
              if (!hasAnswer(value)) return null;
              const label = interviewerQuestionLabel(
                interpolateSubmissionReferences(
                  localized(question.label, locale, question.name),
                  snapshot.data
                )
              );
              return (
                <View key={question.name} style={styles.question} testID={`preview-answer-${question.name}`}>
                  <Text style={styles.label}>{label}</Text>
                  <Text style={styles.previewAnswer}>{previewAnswer(question, value, locale, messages)}</Text>
                </View>
              );
            })
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

    return (
      <ScrollView
        ref={scrollViewRef}
        style={styles.root}
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
      >
        <Text style={styles.progress}>
          {messages.sectionProgress(snapshot.currentSectionIndex + 1, snapshot.visibleSectionCount)}
        </Text>
        <SectionSwitcher
          issueSectionNames={issueSectionNames}
          locale={locale}
          messages={messages}
          sectionProgress={sectionProgress}
          snapshot={snapshot}
          switchSection={switchSection}
        />
        <Text style={styles.sectionTitle}>
          {localized(snapshot.currentSection.label, locale, snapshot.currentSection.name)}
        </Text>
        {snapshot.questions.map(renderQuestion)}
        <View style={styles.navigation}>
          <Pressable
            accessibilityRole="button"
            disabled={!snapshot.canGoBack}
            style={[
              questionControlStyles.button,
              questionControlStyles.buttonSecondary,
              styles.navButton,
              !snapshot.canGoBack && questionControlStyles.buttonDisabled
            ]}
            onPress={() => {
              void saveDraft().then(() => {
                session.previous();
              });
            }}
          >
            <Text style={questionControlStyles.buttonTextSecondary}>{messages.back}</Text>
          </Pressable>
          <Pressable
            accessibilityRole="button"
            disabled={!(props.draftStore ?? primitives.draftStore) || draftStatus === "saving"}
            style={[
              questionControlStyles.button,
              questionControlStyles.buttonSecondary,
              styles.navIconButton,
              (!(props.draftStore ?? primitives.draftStore) || draftStatus === "saving") &&
                questionControlStyles.buttonDisabled
            ]}
            onPress={() => void saveDraft()}
            accessibilityLabel={draftStatus === "saving" ? messages.saving : messages.saveDraft}
          >
            {saveDraftIcon}
          </Pressable>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={messages.previewAnswers}
            style={[
              questionControlStyles.button,
              questionControlStyles.buttonSecondary,
              styles.navIconButton
            ]}
            onPress={() => {
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
          >
            {previewIcon}
          </Pressable>
          <Pressable
            accessibilityRole="button"
            style={[questionControlStyles.button, styles.navPrimaryButton]}
            onPress={advance}
          >
            <Text style={questionControlStyles.buttonText}>
              {snapshot.canGoForward ? messages.next : messages.complete}
            </Text>
          </Pressable>
        </View>
        <Text style={styles.draftStatus}>
          {draftStatus === "saved"
            ? messages.draftSaved(draftId)
            : draftStatus === "error"
              ? messages.draftSaveFailed
              : messages.draftId(draftId)}
        </Text>
      </ScrollView>
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
