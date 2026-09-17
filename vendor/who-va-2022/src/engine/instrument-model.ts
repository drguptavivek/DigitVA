import { parseExpression } from "./expression.js";
import type {
  AnswerDataType,
  ExpressionNode,
  InstrumentDefinition,
  InstrumentQuestion,
  InstrumentSection,
  QuestionControl,
  SourceExpression
} from "../types.js";

export interface InstrumentRuntimeIndex {
  questionsByName: ReadonlyMap<string, InstrumentQuestion>;
  questionsBySection: ReadonlyMap<string, readonly InstrumentQuestion[]>;
  sectionsByName: ReadonlyMap<string, InstrumentSection>;
  sectionsWithQuestions: readonly InstrumentSection[];
  calculatedQuestions: readonly InstrumentQuestion[];
  choiceValuesByQuestionName: ReadonlyMap<string, ReadonlySet<string>>;
}

export interface CompiledInstrumentDefinition {
  readonly definition: InstrumentDefinition;
  readonly runtimeIndex: InstrumentRuntimeIndex;
  readonly semanticSignature: string;
}

const compiledInstruments = new WeakMap<InstrumentDefinition, CompiledInstrumentDefinition>();
const compiledExpressions = new WeakMap<SourceExpression, ExpressionNode>();

const DATA_TYPES_BY_CONTROL: Readonly<Record<QuestionControl, readonly AnswerDataType[]>> = {
  text: ["string"],
  integer: ["number"],
  singleChoice: ["string"],
  multipleChoice: ["string[]"],
  date: ["date"],
  audio: ["attachment"],
  image: ["attachment"],
  file: ["attachment"],
  confirm: ["boolean"],
  note: ["none"],
  calculated: ["calculated"],
  system: ["string", "number", "boolean", "date", "dateTime", "string[]", "attachment", "audit", "none"]
};

function sameExpressionNode(left: ExpressionNode, right: ExpressionNode): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function compileExpression(expression: SourceExpression, owner: string): ExpressionNode {
  const cached = compiledExpressions.get(expression);
  if (cached) return cached;
  const parsed = parseExpression(expression.source);
  if (expression.ast && !sameExpressionNode(parsed, expression.ast)) {
    throw new Error(`${owner} expression source and AST differ`);
  }
  freezeExpressionNode(parsed);
  compiledExpressions.set(expression, parsed);
  return parsed;
}

/** Returns the canonical AST derived from expression source, cached by expression identity. */
export function getCompiledExpressionAst(expression: SourceExpression): ExpressionNode {
  return compileExpression(expression, "Runtime");
}

function sameLocalizedText(
  left: Record<string, string | undefined>,
  right: Record<string, string | undefined>
): boolean {
  const keys = new Set([...Object.keys(left), ...Object.keys(right)]);
  for (const key of keys) {
    if ((left[key] ?? undefined) !== (right[key] ?? undefined)) return false;
  }
  return true;
}

function validateQuestionValidationMetadata(question: InstrumentQuestion): void {
  if (!question.validation) return;
  if (question.validation.required !== question.required) {
    throw new Error(`Question '${question.name}' validation.required must match required`);
  }
  if (question.validation.dataType !== question.dataType) {
    throw new Error(`Question '${question.name}' validation.dataType must match dataType`);
  }
  const expectedChoiceValues = question.choices?.map((choice) => choice.value) ?? [];
  const actualChoiceValues = question.validation.choiceValues ?? [];
  if (JSON.stringify(actualChoiceValues) !== JSON.stringify(expectedChoiceValues)) {
    throw new Error(`Question '${question.name}' validation.choiceValues must match choices`);
  }
  if ((question.validation.constraint?.source ?? undefined) !== (question.constraint?.source ?? undefined)) {
    throw new Error(`Question '${question.name}' validation.constraint must match constraint`);
  }
  if (!sameLocalizedText(question.validation.constraintMessage, question.constraintMessage)) {
    throw new Error(`Question '${question.name}' validation.constraintMessage must match constraintMessage`);
  }
}
function validateQuestion(
  question: InstrumentQuestion,
  sectionNames: ReadonlySet<string>,
  allowSectionlessQuestions: boolean
): void {
  const allowedDataTypes = DATA_TYPES_BY_CONTROL[question.control];
  if (!allowedDataTypes.includes(question.dataType)) {
    throw new Error(
      `Question '${question.name}' uses ${question.control} control; expected ${allowedDataTypes.join(" or ")} data, received ${question.dataType}`
    );
  }
  if (question.sectionPath.length === 0 && question.control !== "system" && !allowSectionlessQuestions) {
    throw new Error(`Question '${question.name}' must belong to at least one section`);
  }
  for (const sectionName of question.sectionPath) {
    if (!sectionNames.has(sectionName)) {
      throw new Error(`Question '${question.name}' references unknown section '${sectionName}'`);
    }
  }
  const choiceQuestion = question.control === "singleChoice" || question.control === "multipleChoice";
  if (choiceQuestion && !question.choices?.length) {
    throw new Error(`Choice question '${question.name}' requires at least one choice`);
  }
  if (!choiceQuestion && question.choices) {
    throw new Error(`Non-choice question '${question.name}' cannot declare choices`);
  }
  if (question.choices) {
    const values = new Set<string>();
    for (const choice of question.choices) {
      if (values.has(choice.value)) {
        throw new Error(`Question '${question.name}' contains duplicate choice '${choice.value}'`);
      }
      values.add(choice.value);
    }
  }
  if (question.relevant) compileExpression(question.relevant, `Question '${question.name}' relevance`);
  if (question.constraint) compileExpression(question.constraint, `Question '${question.name}' constraint`);
  if (question.calculation)
    compileExpression(question.calculation, `Question '${question.name}' calculation`);
  if (question.validation?.constraint)
    compileExpression(question.validation.constraint, `Question '${question.name}' validation constraint`);
  validateQuestionValidationMetadata(question);
}

function validateSectionHierarchy(
  sections: readonly InstrumentSection[],
  sectionsByName: ReadonlyMap<string, InstrumentSection>
): void {
  for (const section of sections) {
    if (section.parent && !sectionsByName.has(section.parent)) {
      throw new Error(`Section '${section.name}' references unknown parent '${section.parent}'`);
    }
    const visited = new Set<string>();
    let current: InstrumentSection | undefined = section;
    while (current?.parent) {
      if (visited.has(current.name)) throw new Error(`Circular section hierarchy at '${current.name}'`);
      visited.add(current.name);
      current = sectionsByName.get(current.parent);
    }
    if (section.relevant) compileExpression(section.relevant, `Section '${section.name}' relevance`);
  }
}

function expressionSignature(expression: SourceExpression | undefined): string | undefined {
  return expression?.source.trim();
}

function semanticSignature(instrument: InstrumentDefinition): string {
  return JSON.stringify({
    id: instrument.id,
    version: instrument.version,
    sections: instrument.sections.map(({ label: _label, ...section }) => ({
      ...section,
      relevant: expressionSignature(section.relevant)
    })),
    questions: instrument.questions.map(
      ({
        label: _label,
        hint: _hint,
        guidance: _guidance,
        constraintMessage: _constraintMessage,
        validation: _validation,
        ...question
      }) => ({
        ...question,
        choices: question.choices?.map(({ label: _choiceLabel, ...choice }) => choice),
        relevant: expressionSignature(question.relevant),
        constraint: expressionSignature(question.constraint),
        calculation: expressionSignature(question.calculation)
      })
    )
  });
}

function freezeExpressionNode(node: ExpressionNode): void {
  if (node.type === "unary") freezeExpressionNode(node.operand);
  if (node.type === "binary") {
    freezeExpressionNode(node.left);
    freezeExpressionNode(node.right);
  }
  if (node.type === "call") {
    for (const argument of node.arguments) freezeExpressionNode(argument);
    Object.freeze(node.arguments);
  }
  Object.freeze(node);
}

function freezeInstrument(instrument: InstrumentDefinition): void {
  for (const section of instrument.sections) {
    if (section.relevant?.ast) freezeExpressionNode(section.relevant.ast);
    if (section.relevant) Object.freeze(section.relevant);
    Object.freeze(section.label);
    Object.freeze(section);
  }
  for (const question of instrument.questions) {
    for (const expression of [question.relevant, question.constraint, question.calculation]) {
      if (expression?.ast) freezeExpressionNode(expression.ast);
      if (expression) Object.freeze(expression);
    }
    for (const choice of question.choices ?? []) {
      Object.freeze(choice.label);
      Object.freeze(choice);
    }
    if (question.choices) Object.freeze(question.choices);
    Object.freeze(question.label);
    Object.freeze(question.hint);
    Object.freeze(question.guidance);
    Object.freeze(question.constraintMessage);
    if (question.validation?.constraint?.ast) freezeExpressionNode(question.validation.constraint.ast);
    if (question.validation?.constraint) Object.freeze(question.validation.constraint);
    if (question.validation?.choiceValues) Object.freeze(question.validation.choiceValues);
    if (question.validation) {
      Object.freeze(question.validation.constraintMessage);
      Object.freeze(question.validation);
    }
    Object.freeze(question.sectionPath);
    Object.freeze(question);
  }
  Object.freeze(instrument.sections);
  Object.freeze(instrument.questions);
  Object.freeze(instrument);
}

export function compileInstrumentDefinition(instrument: InstrumentDefinition): CompiledInstrumentDefinition {
  const cached = compiledInstruments.get(instrument);
  if (cached) return cached;
  if (!instrument.id.trim() || !instrument.version.trim()) {
    throw new Error("Instrument id and version are required");
  }

  const sectionsByName = new Map<string, InstrumentSection>();
  for (const section of instrument.sections) {
    if (sectionsByName.has(section.name)) throw new Error(`Duplicate section '${section.name}'`);
    sectionsByName.set(section.name, section);
  }
  validateSectionHierarchy(instrument.sections, sectionsByName);

  const sectionNames = new Set(sectionsByName.keys());
  const questionsByName = new Map<string, InstrumentQuestion>();
  const questionsBySection = new Map<string, InstrumentQuestion[]>();
  const calculatedQuestions: InstrumentQuestion[] = [];
  const choiceValuesByQuestionName = new Map<string, ReadonlySet<string>>();
  for (const question of instrument.questions) {
    if (questionsByName.has(question.name)) throw new Error(`Duplicate question '${question.name}'`);
    validateQuestion(question, sectionNames, sectionsByName.size === 0);
    questionsByName.set(question.name, question);
    const sectionName = question.sectionPath.at(-1);
    if (sectionName) {
      const sectionQuestions = questionsBySection.get(sectionName) ?? [];
      sectionQuestions.push(question);
      questionsBySection.set(sectionName, sectionQuestions);
    }
    if (question.calculation) calculatedQuestions.push(question);
    if (question.choices) {
      choiceValuesByQuestionName.set(question.name, new Set(question.choices.map((choice) => choice.value)));
    }
  }
  if (questionsByName.size === 0) throw new Error("Instrument must contain at least one question");

  const sectionsWithQuestions = instrument.sections
    .filter((section) => (questionsBySection.get(section.name)?.length ?? 0) > 0)
    .sort((left, right) => {
      const leftOrder = questionsBySection.get(left.name)?.[0]?.order ?? left.order;
      const rightOrder = questionsBySection.get(right.name)?.[0]?.order ?? right.order;
      return leftOrder - rightOrder;
    });

  const compiled: CompiledInstrumentDefinition = {
    definition: instrument,
    semanticSignature: semanticSignature(instrument),
    runtimeIndex: {
      questionsByName,
      questionsBySection,
      sectionsByName,
      sectionsWithQuestions,
      calculatedQuestions,
      choiceValuesByQuestionName
    }
  };
  freezeInstrument(instrument);
  compiledInstruments.set(instrument, compiled);
  return compiled;
}
