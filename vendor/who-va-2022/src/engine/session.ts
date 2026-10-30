/**
 * Stateful, UI-independent interview session engine for answers, calculations,
 * section navigation, localization, and submission validation.
 */
import { evaluateExpression } from "./expression.js";
import { getInstrumentRuntimeIndex } from "./instrument-index.js";
import { compileInstrumentDefinition, getCompiledExpressionAst } from "./instrument-model.js";
import {
  applyCalculations,
  getQuestion,
  isQuestionRelevantWithCalculatedData,
  isSectionRelevantWithCalculatedData,
  validateAnswer,
  validateSubmission
} from "./validation.js";
import { formatLocalDate } from "./date.js";
import { reduceNationalIdData } from "../national-id.js";
import type {
  AnswerValue,
  InstrumentDefinition,
  InstrumentQuestion,
  InstrumentSection,
  SessionNavigationResult,
  SessionSnapshot,
  SubmissionData,
  SubmissionValidationResult,
  ValidationIssue,
  GoToQuestionResult,
  WhoVaSession,
  WhoVaSessionOptions
} from "../types.js";
import { resolveUiMessages, type WhoVaUiMessages, type WhoVaUiTranslations } from "../i18n.js";

function directQuestions(
  instrument: InstrumentDefinition,
  section: InstrumentSection
): readonly InstrumentQuestion[] {
  return getInstrumentRuntimeIndex(instrument).questionsBySection.get(section.name) ?? [];
}

function sectionIsRelevant(
  instrument: InstrumentDefinition,
  section: InstrumentSection,
  data: SubmissionData
): boolean {
  return isSectionRelevantWithCalculatedData(instrument, section, data);
}

function isEmptyAnswer(value: unknown): boolean {
  return value == null || value === "" || (Array.isArray(value) && value.length === 0);
}

function blocksDraftMutation(issue: ValidationIssue): boolean {
  return issue.code === "type" || issue.code === "choice" || issue.code === "unsupported-expression";
}

function issueSection(
  instrument: InstrumentDefinition,
  visibleSections: readonly InstrumentSection[],
  issue: ValidationIssue
): InstrumentSection | undefined {
  const question = getInstrumentRuntimeIndex(instrument).questionsByName.get(issue.question);
  if (!question) return undefined;
  const visibleByName = new Map(visibleSections.map((section) => [section.name, section]));
  for (const sectionName of [...question.sectionPath].reverse()) {
    const section = visibleByName.get(sectionName);
    if (section) return section;
  }
  return undefined;
}

/** Every question name an expression refers to, in order of appearance. */
function referencedNames(node: unknown, found: string[] = []): string[] {
  if (Array.isArray(node)) node.forEach((child) => referencedNames(child, found));
  else if (node && typeof node === "object") {
    const record = node as Record<string, unknown>;
    if (record.type === "reference" && typeof record.name === "string") found.push(record.name);
    else Object.values(record).forEach((child) => referencedNames(child, found));
  }
  return found;
}

class UniversalWhoVaSession implements WhoVaSession {
  private data: SubmissionData;
  private currentSectionName: string;
  private issues: ValidationIssue[] = [];
  private visibleSectionsCache:
    { instrument: InstrumentDefinition; data: SubmissionData; sections: InstrumentSection[] } | undefined;
  private readonly listeners = new Set<(snapshot: SessionSnapshot) => void>();
  /** The host's locks; only those holding an answer are enforced (lockedQuestionNames). */
  private requestedLocks: ReadonlySet<string>;
  private lockedQuestionNames: ReadonlySet<string>;
  private readonly now: () => Date;
  private locale: string;
  private messages: WhoVaUiMessages;

  constructor(
    private instrument: InstrumentDefinition,
    options: WhoVaSessionOptions = {}
  ) {
    this.now = options.now ?? (() => new Date());
    this.locale = options.locale ?? "en";
    this.messages = resolveUiMessages(this.locale, options.uiTranslations);
    const startedAt = this.now();
    this.data = {};
    const initialData = reduceNationalIdData(options.initialData ?? {});
    const { choiceValuesByQuestionName, questionsByName } = getInstrumentRuntimeIndex(instrument);
    this.requestedLocks = new Set(
      [...(options.lockedQuestionNames ?? [])].filter((name) => questionsByName.has(name))
    );
    for (const [name, value] of Object.entries(initialData)) {
      const question = questionsByName.get(name);
      if (!question) continue;
      const errors = validateAnswer(
        question,
        value,
        initialData,
        this.locale,
        this.messages,
        choiceValuesByQuestionName.get(name)
      ).filter(blocksDraftMutation);
      if (errors.length) throw new Error(errors[0]?.message ?? `${name} is invalid`);
      this.data[name] = value;
    }
    for (const question of instrument.questions) {
      // Literal defaults only (not XLSForm ${...} references); prefill and
      // saved answers win because the key is already present.
      if (question.defaultValue && !question.defaultValue.includes("${") && this.data[question.name] == null)
        this.data[question.name] = question.defaultValue;
      if (question.sourceType === "today" && this.data[question.name] == null)
        this.data[question.name] = formatLocalDate(startedAt);
      if (question.sourceType === "start" && this.data[question.name] == null)
        this.data[question.name] = startedAt.toISOString();
      if (question.sourceType === "audit" && options.audit && this.data[question.name] == null)
        this.data[question.name] = options.audit;
    }
    this.data = applyCalculations(instrument, this.data);
    this.lockedQuestionNames = this.enforcedLocks();
    const first = this.visibleSections()[0];
    if (!first) throw new Error("Instrument has no visible sections");
    const requested = options.initialSection
      ? this.visibleSections().find((section) => section.name === options.initialSection)
      : undefined;
    this.currentSectionName = requested?.name ?? first.name;
  }

  private visibleSections(): InstrumentSection[] {
    if (
      this.visibleSectionsCache?.instrument === this.instrument &&
      this.visibleSectionsCache.data === this.data
    ) {
      return this.visibleSectionsCache.sections;
    }
    const sections = getInstrumentRuntimeIndex(this.instrument).sectionsWithQuestions.filter((section) =>
      sectionIsRelevant(this.instrument, section, this.data)
    );
    this.visibleSectionsCache = { instrument: this.instrument, data: this.data, sections };
    return sections;
  }

  private currentSection(visible = this.visibleSections()): InstrumentSection {
    return (
      visible.find((section) => section.name === this.currentSectionName) ??
      visible[0] ??
      (this.instrument.sections[0] as InstrumentSection)
    );
  }

  private presentQuestion(question: InstrumentQuestion): InstrumentQuestion {
    return this.lockedQuestionNames.has(question.name) && !question.readOnly
      ? { ...question, readOnly: true }
      : question;
  }

  private currentQuestions(section = this.currentSection()): InstrumentQuestion[] {
    return directQuestions(this.instrument, section)
      .filter(
        (question) =>
          !["calculated", "system"].includes(question.control) &&
          isQuestionRelevantWithCalculatedData(this.instrument, question, this.data)
      )
      .map((question) => this.presentQuestion(question));
  }

  private notify(): void {
    const snapshot = this.getSnapshot();
    for (const listener of this.listeners) listener(snapshot);
  }

  getSnapshot(): SessionSnapshot {
    const sections = this.visibleSections();
    const currentSection = this.currentSection(sections);
    const index = Math.max(
      0,
      sections.findIndex((section) => section.name === currentSection.name)
    );
    return {
      data: { ...this.data },
      currentSection,
      currentSectionIndex: index,
      visibleSectionCount: sections.length,
      visibleSections: [...sections],
      questions: this.currentQuestions(currentSection),
      lockedQuestionNames: [...this.lockedQuestionNames],
      issues: [...this.issues],
      canGoBack: index > 0,
      canGoForward: index < sections.length - 1
    };
  }

  setLockedQuestionNames(names: Iterable<string>): void {
    const { questionsByName } = getInstrumentRuntimeIndex(this.instrument);
    this.requestedLocks = new Set([...names].filter((name) => questionsByName.has(name)));
    this.lockedQuestionNames = this.enforcedLocks();
    this.notify();
  }

  /**
   * The requested locks that hold an answer. A locked question left empty (its
   * prefill lost or never sent) would trap the interviewer on a required
   * question, so it stays editable until data is next loaded; the host
   * restores the authoritative value on save. Typing never re-locks it.
   */
  private enforcedLocks(): ReadonlySet<string> {
    return new Set([...this.requestedLocks].filter((name) => !isEmptyAnswer(this.data[name])));
  }

  setInstrument(instrument: InstrumentDefinition): void {
    if (instrument === this.instrument) return;
    if (instrument.id !== this.instrument.id || instrument.version !== this.instrument.version) {
      throw new Error("A session language change must use the same instrument id and version");
    }
    if (
      compileInstrumentDefinition(instrument).semanticSignature !==
      compileInstrumentDefinition(this.instrument).semanticSignature
    ) {
      throw new Error("A session language change cannot alter the instrument semantic contract");
    }
    this.instrument = instrument;
    this.data = applyCalculations(instrument, this.data);
    this.notify();
  }

  setAnswer(name: string, value: AnswerValue | undefined): void {
    const question = getQuestion(this.instrument, name);
    if (
      question.readOnly ||
      this.lockedQuestionNames.has(name) ||
      ["note", "calculated", "system"].includes(question.control)
    ) {
      throw new Error(`${name} cannot be edited by the respondent`);
    }
    const nextData = { ...this.data };
    if (value == null || value === "" || (Array.isArray(value) && value.length === 0)) delete nextData[name];
    else nextData[name] = value;
    // The full national ID never enters session data (and so no draft).
    const calculatedNextData = applyCalculations(this.instrument, reduceNationalIdData(nextData));
    const fieldIssues = validateAnswer(
      question,
      value,
      calculatedNextData,
      this.locale,
      this.messages,
      getInstrumentRuntimeIndex(this.instrument).choiceValuesByQuestionName.get(question.name)
    );
    const blocking = fieldIssues.filter(blocksDraftMutation);
    if (blocking.length) throw new Error(blocking[0]?.message ?? `${name} is invalid`);
    this.data = calculatedNextData;
    this.issues = [...this.issues.filter((issue) => issue.question !== name), ...fieldIssues];
    this.notify();
  }

  replaceData(data: SubmissionData): void {
    const replacement = { ...this.data };
    const { choiceValuesByQuestionName, questionsByName } = getInstrumentRuntimeIndex(this.instrument);
    for (const question of this.instrument.questions) {
      if (["calculated", "system"].includes(question.control)) continue;
      delete replacement[question.name];
    }
    for (const [name, value] of Object.entries(reduceNationalIdData(data))) {
      const question = questionsByName.get(name);
      if (!question) continue;
      if (["calculated", "system"].includes(question.control)) continue;
      const errors = validateAnswer(
        question,
        value,
        { ...replacement, [name]: value },
        this.locale,
        this.messages,
        choiceValuesByQuestionName.get(question.name)
      ).filter(blocksDraftMutation);
      if (errors.length) throw new Error(errors[0]?.message ?? `${name} is invalid`);
      replacement[name] = value;
    }
    this.data = applyCalculations(this.instrument, replacement);
    this.lockedQuestionNames = this.enforcedLocks();
    this.issues = [];
    const current = this.currentSection();
    this.currentSectionName = current.name;
    this.notify();
  }

  goToSection(name: string): boolean {
    const section = this.visibleSections().find((candidate) => candidate.name === name);
    if (!section) return false;
    if (section.name === this.currentSectionName) return true;
    this.currentSectionName = section.name;
    this.issues = [];
    this.notify();
    return true;
  }

  goToQuestion(name: string): GoToQuestionResult {
    const index = getInstrumentRuntimeIndex(this.instrument);
    const open = (question: InstrumentQuestion): string | undefined => {
      const section = issueSection(this.instrument, this.visibleSections(), {
        question: question.name,
        code: "required",
        message: ""
      });
      if (section && section.name !== this.currentSectionName) {
        this.currentSectionName = section.name;
        this.notify();
      }
      return section?.name;
    };
    const requested = index.questionsByName.get(name);
    if (!requested) return { status: "unavailable", requested: name };
    const shown = (question: InstrumentQuestion) =>
      !["calculated", "system"].includes(question.control) &&
      isQuestionRelevantWithCalculatedData(this.instrument, question, this.data);
    if (shown(requested)) {
      const section = open(requested);
      return section
        ? { status: "shown", question: name, section }
        : { status: "unavailable", requested: name };
    }
    // Hidden: walk to the earlier answer its relevance (and its groups') rests on.
    let current = requested;
    for (let depth = 0; depth < 6; depth += 1) {
      // Only the conditions that are false right now hide it.
      const failing = [
        ...current.sectionPath.map((sectionName) => index.sectionsByName.get(sectionName)?.relevant),
        current.relevant
      ].filter(
        (expression): expression is NonNullable<typeof expression> =>
          expression !== undefined && !evaluateExpression(getCompiledExpressionAst(expression), this.data)
      );
      const controller = failing
        .flatMap((expression) => referencedNames(getCompiledExpressionAst(expression)))
        .map((reference) => index.questionsByName.get(reference))
        .find(
          (candidate): candidate is InstrumentQuestion =>
            candidate !== undefined &&
            candidate.name !== current.name &&
            !["calculated", "system", "note"].includes(candidate.control)
        );
      if (!controller) break;
      if (shown(controller)) {
        const section = open(controller);
        return section
          ? { status: "hidden", question: controller.name, requested: name, section }
          : { status: "unavailable", requested: name };
      }
      current = controller;
    }
    return { status: "unavailable", requested: name };
  }

  setLocale(locale: string, uiTranslations?: WhoVaUiTranslations): void {
    this.locale = locale;
    this.messages = resolveUiMessages(locale, uiTranslations);
  }

  next(): SessionNavigationResult {
    const sections = this.visibleSections();
    const currentSection = this.currentSection(sections);
    const currentIssues = this.currentQuestions(currentSection).flatMap((question) =>
      validateAnswer(
        question,
        this.data[question.name],
        this.data,
        this.locale,
        this.messages,
        getInstrumentRuntimeIndex(this.instrument).choiceValuesByQuestionName.get(question.name)
      )
    );
    this.issues = currentIssues;
    if (currentIssues.length) {
      this.notify();
      return {
        status: "blocked",
        advanced: false,
        completed: false,
        issues: [currentIssues[0]!, ...currentIssues.slice(1)]
      };
    }
    const index = sections.findIndex((section) => section.name === currentSection.name);
    const next = sections[index + 1];
    if (!next) {
      const completed = this.complete();
      if (completed.valid) {
        return { status: "completed", advanced: true, completed: true, issues: [], result: completed };
      }
      const firstIssueSection = issueSection(this.instrument, sections, completed.issues[0]);
      if (firstIssueSection && firstIssueSection.name !== this.currentSectionName) {
        this.currentSectionName = firstIssueSection.name;
        this.issues = completed.issues;
        this.notify();
      }
      return { status: "blocked", advanced: false, completed: false, issues: completed.issues };
    }
    this.currentSectionName = next.name;
    this.issues = [];
    this.notify();
    return { status: "advanced", advanced: true, completed: false, issues: [] };
  }

  previous(): boolean {
    const sections = this.visibleSections();
    const index = sections.findIndex((section) => section.name === this.currentSection(sections).name);
    const previous = sections[index - 1];
    if (!previous) return false;
    this.currentSectionName = previous.name;
    this.issues = [];
    this.notify();
    return true;
  }

  validate(): SubmissionValidationResult {
    return validateSubmission(this.instrument, this.data, this.locale, this.messages);
  }

  complete(): SubmissionValidationResult {
    const completedAt = this.now().toISOString();
    for (const question of this.instrument.questions)
      if (question.sourceType === "end") this.data[question.name] = completedAt;
    const result = validateSubmission(this.instrument, this.data, this.locale, this.messages);
    this.data = result.data;
    this.issues = result.issues;
    this.notify();
    return result;
  }

  subscribe(listener: (snapshot: SessionSnapshot) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}

export function createWhoVaSession(
  instrument: InstrumentDefinition,
  options: WhoVaSessionOptions = {}
): WhoVaSession {
  return new UniversalWhoVaSession(instrument, options);
}
