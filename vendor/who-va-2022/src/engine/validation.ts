/**
 * Canonical answer and submission validation, relevance evaluation, and
 * calculated-field normalization for the canonical instrument contract.
 */
import { evaluateExpression } from "./expression.js";
import { getCompiledExpressionAst } from "./instrument-model.js";
import { getInstrumentRuntimeIndex } from "./instrument-index.js";
import type {
  AnswerValue,
  InstrumentDefinition,
  InstrumentQuestion,
  InstrumentSection,
  SubmissionData,
  SubmissionValidationResult,
  ValidationIssue
} from "../types.js";
import { ENGLISH_UI_MESSAGES, localizeText, type WhoVaUiMessages } from "../i18n.js";
import { isValidIsoDate } from "../date.js";
import { WHO_VA_FORM_VERSION } from "../version.js";

const expressionAst = getCompiledExpressionAst;

function isEmpty(value: unknown): boolean {
  return value == null || value === "" || (Array.isArray(value) && value.length === 0);
}

function message(question: InstrumentQuestion, locale: string, fallback: string): string {
  return localizeText(question.constraintMessage, locale, fallback);
}

function validationLabel(question: InstrumentQuestion, locale: string): string {
  return localizeText(question.label, locale, question.name).replace(/\[([^\]]+)\]/g, "$1");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value != null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function typeIsValid(question: InstrumentQuestion, value: unknown): boolean {
  switch (question.dataType) {
    case "string":
      return typeof value === "string";
    case "number":
      return typeof value === "number" && Number.isFinite(value) && Number.isInteger(value);
    case "boolean":
      return typeof value === "boolean";
    case "date":
      return isValidIsoDate(value);
    case "dateTime":
      return typeof value === "string" && !Number.isNaN(Date.parse(value));
    case "string[]":
      return Array.isArray(value) && value.every((item) => typeof item === "string");
    case "attachment":
      return isNonEmptyString(value) || (isRecord(value) && isNonEmptyString(value.uri));
    case "audit":
      return (
        isRecord(value) &&
        isNonEmptyString(value.startedAt) &&
        /^\d{4}-\d{2}-\d{2}T/.test(value.startedAt) &&
        !Number.isNaN(Date.parse(value.startedAt))
      );
    case "calculated":
    case "none":
      return true;
  }
}

export function getQuestion(instrument: InstrumentDefinition, name: string): InstrumentQuestion {
  const question = getInstrumentRuntimeIndex(instrument).questionsByName.get(name);
  if (!question) throw new Error(`Unknown question '${name}'`);
  return question;
}

export function applyCalculations(instrument: InstrumentDefinition, data: SubmissionData): SubmissionData {
  const calculated: SubmissionData = { ...data };
  for (const question of getInstrumentRuntimeIndex(instrument).calculatedQuestions) {
    if (!question.calculation) continue;
    calculated[question.name] = evaluateExpression(
      expressionAst(question.calculation),
      calculated
    ) as AnswerValue;
  }
  return calculated;
}

export function isQuestionRelevant(
  instrument: InstrumentDefinition,
  question: InstrumentQuestion,
  data: SubmissionData
): boolean {
  const calculated = applyCalculations(instrument, data);
  return isQuestionRelevantWithCalculatedData(instrument, question, calculated);
}

/** Internal fast path for callers that already hold freshly calculated data. */
export function isQuestionRelevantWithCalculatedData(
  instrument: InstrumentDefinition,
  question: InstrumentQuestion,
  calculated: SubmissionData
): boolean {
  const { sectionsByName } = getInstrumentRuntimeIndex(instrument);
  for (const sectionName of question.sectionPath) {
    const section = sectionsByName.get(sectionName);
    if (section?.relevant && !evaluateExpression(expressionAst(section.relevant), calculated)) return false;
  }
  if (question.relevant && !evaluateExpression(expressionAst(question.relevant), calculated)) return false;
  return true;
}

/** Evaluates an XLSForm group independently from the questions it contains. */
export function isSectionRelevantWithCalculatedData(
  instrument: InstrumentDefinition,
  section: InstrumentSection,
  calculated: SubmissionData
): boolean {
  const { sectionsByName } = getInstrumentRuntimeIndex(instrument);
  let current: InstrumentSection | undefined = section;
  const visited = new Set<string>();
  while (current) {
    if (visited.has(current.name)) throw new Error(`Circular section hierarchy at '${current.name}'`);
    visited.add(current.name);
    if (current.relevant && !evaluateExpression(expressionAst(current.relevant), calculated)) return false;
    current = current.parent ? sectionsByName.get(current.parent) : undefined;
  }
  return true;
}

export function validateAnswer(
  question: InstrumentQuestion,
  value: AnswerValue | undefined,
  data: SubmissionData,
  locale = "en",
  messages: WhoVaUiMessages = ENGLISH_UI_MESSAGES,
  allowedChoiceValues?: ReadonlySet<string>
): ValidationIssue[] {
  if (["note", "calculated"].includes(question.control)) return [];
  if (isEmpty(value)) {
    return question.required
      ? [
          {
            question: question.name,
            code: "required",
            message: messages.required(validationLabel(question, locale))
          }
        ]
      : [];
  }
  if (!typeIsValid(question, value)) {
    return [
      {
        question: question.name,
        code: "type",
        message: messages.invalidType(question.name, question.dataType)
      }
    ];
  }
  if (question.choices) {
    const allowed = allowedChoiceValues ?? new Set(question.choices.map((choice) => choice.value));
    const values = Array.isArray(value) ? value : [value];
    if (
      values.some((item) => typeof item !== "string" || !allowed.has(item)) ||
      new Set(values).size !== values.length
    ) {
      return [{ question: question.name, code: "choice", message: messages.invalidChoice(question.name) }];
    }
  }
  if (question.constraint) {
    try {
      const valid = evaluateExpression(expressionAst(question.constraint), data, { currentValue: value });
      if (!valid) {
        return [
          {
            question: question.name,
            code: "constraint",
            message: message(question, locale, messages.invalidConstraint(question.name))
          }
        ];
      }
    } catch (error) {
      return [
        {
          question: question.name,
          code: "unsupported-expression",
          message: error instanceof Error ? error.message : String(error)
        }
      ];
    }
  }
  return [];
}

export function validateSubmission(
  instrument: InstrumentDefinition,
  data: SubmissionData,
  locale = "en",
  messages: WhoVaUiMessages = ENGLISH_UI_MESSAGES
): SubmissionValidationResult {
  const calculated = applyCalculations(instrument, data);
  const { choiceValuesByQuestionName } = getInstrumentRuntimeIndex(instrument);
  const normalized: SubmissionData = {};
  const issues: ValidationIssue[] = [];
  for (const question of instrument.questions) {
    if (Object.hasOwn(calculated, question.name)) normalized[question.name] = calculated[question.name];
    if (!isQuestionRelevantWithCalculatedData(instrument, question, calculated)) {
      if (question.control !== "system") delete normalized[question.name];
      continue;
    }
    issues.push(
      ...validateAnswer(
        question,
        calculated[question.name],
        calculated,
        locale,
        messages,
        choiceValuesByQuestionName.get(question.name)
      )
    );
  }
  return issues.length
    ? {
        valid: false,
        formVersion: WHO_VA_FORM_VERSION,
        instrumentId: instrument.id,
        instrumentVersion: instrument.version,
        data: normalized,
        issues: [issues[0]!, ...issues.slice(1)]
      }
    : {
        valid: true,
        formVersion: WHO_VA_FORM_VERSION,
        instrumentId: instrument.id,
        instrumentVersion: instrument.version,
        data: normalized,
        issues: []
      };
}
