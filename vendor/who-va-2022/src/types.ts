/**
 * Canonical, platform-neutral data contracts for the compiled instrument,
 * answers, drafts, validation results, and interview sessions.
 */
import type { WhoVaUiTranslations } from "./i18n.js";

export type AnswerDataType =
  | "string"
  | "number"
  | "boolean"
  | "date"
  | "dateTime"
  | "string[]"
  | "attachment"
  | "audit"
  | "calculated"
  | "none";

export type QuestionControl =
  | "text"
  | "integer"
  | "singleChoice"
  | "multipleChoice"
  | "date"
  | "audio"
  | "image"
  | "file"
  | "confirm"
  | "note"
  | "calculated"
  | "system";

export interface LocalizedText {
  en?: string;
  fr?: string;
  [locale: string]: string | undefined;
}

export interface InstrumentChoice {
  value: string;
  label: LocalizedText;
  sourceRow: number;
}

export interface SourceExpression {
  source: string;
  ast?: ExpressionNode;
}

export type ExpressionCallNode =
  | { type: "call"; name: "selected"; arguments: [ExpressionNode, ExpressionNode] }
  | { type: "call"; name: "regex"; arguments: [ExpressionNode, ExpressionNode] }
  | { type: "call"; name: "count-selected" | "string-length" | "int" | "date"; arguments: [ExpressionNode] }
  | { type: "call"; name: "if"; arguments: [ExpressionNode, ExpressionNode, ExpressionNode] }
  | { type: "call"; name: "today"; arguments: [] };

export type ExpressionNode =
  | { type: "literal"; value: string | number | boolean | null }
  | { type: "reference"; name: string }
  | { type: "current" }
  | { type: "unary"; operator: "not" | "negative"; operand: ExpressionNode }
  | {
      type: "binary";
      operator: "and" | "or" | "=" | "!=" | ">" | ">=" | "<" | "<=" | "+" | "-" | "*" | "div" | "mod";
      left: ExpressionNode;
      right: ExpressionNode;
    }
  | ExpressionCallNode;

export interface InstrumentQuestionValidation {
  required: boolean;
  dataType: AnswerDataType;
  choiceValues?: string[];
  constraint?: SourceExpression;
  constraintMessage: LocalizedText;
}

export interface InstrumentQuestion {
  name: string;
  order: number;
  sourceRow: number;
  sourceType: string;
  ageGroup?: string;
  dataType: AnswerDataType;
  control: QuestionControl;
  listName?: string;
  label: LocalizedText;
  hint: LocalizedText;
  guidance: LocalizedText;
  required: boolean;
  readOnly: boolean;
  appearance?: string;
  parameters?: string;
  defaultValue?: string;
  choices?: InstrumentChoice[];
  relevant?: SourceExpression;
  constraint?: SourceExpression;
  constraintMessage: LocalizedText;
  validation?: InstrumentQuestionValidation;
  calculation?: SourceExpression;
  sectionPath: string[];
}

export interface InstrumentSection {
  name: string;
  sourceRow: number;
  order: number;
  label: LocalizedText;
  ageGroup?: string;
  parent?: string;
  relevant?: SourceExpression;
}

export interface InstrumentDefinition {
  id: string;
  title: string;
  version: string;
  defaultLanguage: string;
  sourceFile: string;
  sections: InstrumentSection[];
  questions: InstrumentQuestion[];
}

export interface AttachmentReferenceBase {
  uri: string;
  id?: string;
  name?: string;
  originalName?: string;
  mimeType?: string;
  size?: number;
}

export interface ExternalAttachmentReference extends AttachmentReferenceBase {
  processed?: never;
  originalRetained?: never;
}

export interface ProcessedImageAttachmentReference extends AttachmentReferenceBase {
  id: string;
  name: string;
  originalName: string;
  mimeType: "image/jpeg";
  size: number;
  width: number;
  height: number;
  processed: true;
  durationMs?: never;
}

export interface RetainedPdfAttachmentReference extends AttachmentReferenceBase {
  id: string;
  name: string;
  originalName: string;
  mimeType: "application/pdf";
  size: number;
  originalRetained: true;
  processed: false;
  serverSideValidationRequired: true;
}

export interface AudioAttachmentReference extends AttachmentReferenceBase {
  id: string;
  name: string;
  originalName: string;
  mimeType: string;
  size: number;
  durationMs: number;
  processed: true;
  width?: never;
  height?: never;
}

export type AttachmentReference =
  | ExternalAttachmentReference
  | ProcessedImageAttachmentReference
  | RetainedPdfAttachmentReference
  | AudioAttachmentReference;

/** A platform picker result that still requires canonical processing. */
export interface AttachmentSelection {
  uri: string;
  name?: string;
  mimeType?: string;
  [key: string]: unknown;
}

export type AttachmentCandidate = AttachmentReference | AttachmentSelection;
/** @deprecated Use AttachmentReference. */
export type AttachmentAnswer = AttachmentReference;

export interface AuditAnswer {
  startedAt: string;
  [key: string]: unknown;
}

export type AnswerValue = string | number | boolean | string[] | AttachmentReference | AuditAnswer | null;
export type SubmissionData = Record<string, AnswerValue | undefined>;

export interface WhoVaDraft {
  schemaVersion: 1;
  formVersion: string;
  id: string;
  instrumentId: string;
  instrumentVersion: string;
  currentSection: string;
  createdAt: string;
  updatedAt: string;
  data: SubmissionData;
}

export interface WhoVaDraftStore {
  save(draft: WhoVaDraft): void | Promise<void>;
  load?(id: string): WhoVaDraft | undefined | Promise<WhoVaDraft | undefined>;
  remove?(id: string): void | Promise<void>;
}

export interface ValidationIssue {
  question: string;
  code: "required" | "type" | "choice" | "constraint" | "unsupported-expression";
  message: string;
}

export type NonEmptyArray<T> = [T, ...T[]];

export interface FormVersionIdentity {
  formVersion: string;
  instrumentId: string;
  instrumentVersion: string;
}

export interface ValidSubmissionResult extends FormVersionIdentity {
  valid: true;
  data: SubmissionData;
  issues: [];
}

export interface InvalidSubmissionResult extends FormVersionIdentity {
  valid: false;
  data: SubmissionData;
  issues: NonEmptyArray<ValidationIssue>;
}

export type SubmissionValidationResult = ValidSubmissionResult | InvalidSubmissionResult;

export interface SessionSnapshot {
  data: SubmissionData;
  currentSection: InstrumentSection;
  currentSectionIndex: number;
  visibleSectionCount: number;
  visibleSections: InstrumentSection[];
  questions: InstrumentQuestion[];
  lockedQuestionNames: string[];
  issues: ValidationIssue[];
  canGoBack: boolean;
  canGoForward: boolean;
}

export type SessionNavigationResult =
  | {
      status: "blocked";
      advanced: false;
      completed: false;
      issues: NonEmptyArray<ValidationIssue>;
    }
  | { status: "advanced"; advanced: true; completed: false; issues: [] }
  | {
      status: "completed";
      advanced: true;
      completed: true;
      issues: [];
      result: ValidSubmissionResult;
    };

export interface WhoVaSessionOptions {
  initialData?: SubmissionData;
  lockedQuestionNames?: Iterable<string>;
  initialSection?: string;
  locale?: string;
  uiTranslations?: WhoVaUiTranslations;
  now?: () => Date;
  audit?: AuditAnswer;
}

export interface WhoVaSession {
  getSnapshot(): SessionSnapshot;
  setInstrument(instrument: InstrumentDefinition): void;
  setLockedQuestionNames(names: Iterable<string>): void;
  setAnswer(name: string, value: AnswerValue | undefined): void;
  replaceData(data: SubmissionData): void;
  goToSection(name: string): boolean;
  setLocale(locale: string, uiTranslations?: WhoVaUiTranslations): void;
  next(): SessionNavigationResult;
  previous(): boolean;
  validate(): SubmissionValidationResult;
  complete(): SubmissionValidationResult;
  subscribe(listener: (snapshot: SessionSnapshot) => void): () => void;
}
