/**
 * Parser and evaluator for the supported XLSForm expression subset, operating
 * on the canonical submission data without a browser or ODK dependency.
 */
import type { AnswerValue, ExpressionCallNode, ExpressionNode, SubmissionData } from "../types.js";
import { formatLocalDate } from "./date.js";

type TokenType =
  "number" | "string" | "reference" | "identifier" | "dot" | "operator" | "left" | "right" | "comma" | "eof";
interface Token {
  type: TokenType;
  value: string;
}

const binaryPrecedence: Record<string, number> = {
  or: 1,
  and: 2,
  "=": 3,
  "!=": 3,
  ">": 3,
  ">=": 3,
  "<": 3,
  "<=": 3,
  "+": 4,
  "-": 4,
  "*": 5,
  div: 5,
  mod: 5
};

function tokenize(source: string): Token[] {
  const tokens: Token[] = [];
  let index = 0;
  while (index < source.length) {
    const character = source[index];
    if (!character) break;
    if (/\s/.test(character)) {
      index += 1;
      continue;
    }
    if (source.startsWith("${", index)) {
      const end = source.indexOf("}", index + 2);
      if (end < 0) throw new Error(`Unclosed reference at character ${index}`);
      tokens.push({ type: "reference", value: source.slice(index + 2, end) });
      index = end + 1;
      continue;
    }
    if (character === "'" || character === '"') {
      const quote = character;
      let value = "";
      index += 1;
      while (index < source.length) {
        const next = source[index];
        if (next === quote) {
          if (source[index + 1] === quote) {
            value += quote;
            index += 2;
            continue;
          }
          index += 1;
          break;
        }
        if (next === "\\" && source[index + 1]) {
          value += source[index + 1];
          index += 2;
          continue;
        }
        value += next;
        index += 1;
      }
      tokens.push({ type: "string", value });
      continue;
    }
    if (/\d/.test(character) || (character === "." && /\d/.test(source[index + 1] ?? ""))) {
      const match = source.slice(index).match(/^\d*\.?\d+(?:[eE][+-]?\d+)?/);
      if (!match) throw new Error(`Invalid number at character ${index}`);
      tokens.push({ type: "number", value: match[0] });
      index += match[0].length;
      continue;
    }
    const doubleOperator = source.slice(index, index + 2);
    if (["!=", ">=", "<="].includes(doubleOperator)) {
      tokens.push({ type: "operator", value: doubleOperator });
      index += 2;
      continue;
    }
    if (["=", ">", "<", "+", "-", "*"].includes(character)) {
      tokens.push({ type: "operator", value: character });
      index += 1;
      continue;
    }
    if (character === ".") {
      tokens.push({ type: "dot", value: character });
      index += 1;
      continue;
    }
    if (character === "(") {
      tokens.push({ type: "left", value: character });
      index += 1;
      continue;
    }
    if (character === ")") {
      tokens.push({ type: "right", value: character });
      index += 1;
      continue;
    }
    if (character === ",") {
      tokens.push({ type: "comma", value: character });
      index += 1;
      continue;
    }
    const identifier = source.slice(index).match(/^[A-Za-z_][A-Za-z0-9_-]*/);
    if (identifier) {
      const value = identifier[0];
      tokens.push({ type: value in binaryPrecedence ? "operator" : "identifier", value });
      index += value.length;
      continue;
    }
    throw new Error(`Unsupported character '${character}' at character ${index}`);
  }
  tokens.push({ type: "eof", value: "" });
  return tokens;
}

class Parser {
  private index = 0;
  constructor(private readonly tokens: Token[]) {}

  parse(): ExpressionNode {
    const result = this.parseBinary(1);
    if (this.peek().type !== "eof") throw new Error(`Unexpected token '${this.peek().value}'`);
    return result;
  }

  private peek(): Token {
    return this.tokens[this.index] ?? { type: "eof", value: "" };
  }

  private consume(type?: TokenType, value?: string): Token {
    const token = this.peek();
    if (type && token.type !== type) throw new Error(`Expected ${type}, found '${token.value}'`);
    if (value && token.value !== value) throw new Error(`Expected '${value}', found '${token.value}'`);
    this.index += 1;
    return token;
  }

  private parseBinary(minimumPrecedence: number): ExpressionNode {
    let left = this.parseUnary();
    while (true) {
      const token = this.peek();
      const precedence = token.type === "operator" ? binaryPrecedence[token.value] : undefined;
      if (precedence == null || precedence < minimumPrecedence) break;
      this.consume("operator");
      const right = this.parseBinary(precedence + 1);
      left = {
        type: "binary",
        operator: token.value as Extract<ExpressionNode, { type: "binary" }>["operator"],
        left,
        right
      };
    }
    return left;
  }

  private parseUnary(): ExpressionNode {
    if (this.peek().type === "operator" && this.peek().value === "-") {
      this.consume("operator", "-");
      return { type: "unary", operator: "negative", operand: this.parseUnary() };
    }
    return this.parsePrimary();
  }

  private parsePrimary(): ExpressionNode {
    const token = this.peek();
    if (token.type === "number") {
      this.consume();
      return { type: "literal", value: Number(token.value) };
    }
    if (token.type === "string") {
      this.consume();
      return { type: "literal", value: token.value };
    }
    if (token.type === "reference") {
      this.consume();
      return { type: "reference", name: token.value };
    }
    if (token.type === "dot") {
      this.consume();
      return { type: "current" };
    }
    if (token.type === "left") {
      this.consume("left");
      const nested = this.parseBinary(1);
      this.consume("right");
      return nested;
    }
    if (token.type === "identifier") {
      this.consume("identifier");
      if (token.value === "true" || token.value === "false")
        return { type: "literal", value: token.value === "true" };
      if (token.value === "null") return { type: "literal", value: null };
      this.consume("left");
      const arguments_: ExpressionNode[] = [];
      if (this.peek().type !== "right") {
        while (true) {
          arguments_.push(this.parseBinary(1));
          if (this.peek().type !== "comma") break;
          this.consume("comma");
        }
      }
      this.consume("right");
      if (token.value === "not") {
        if (arguments_.length !== 1 || !arguments_[0]) throw new Error("not() requires one argument");
        return { type: "unary", operator: "not", operand: arguments_[0] };
      }
      const supported = [
        "selected",
        "regex",
        "count-selected",
        "string-length",
        "int",
        "if",
        "today",
        "date"
      ] as const;
      if (!supported.includes(token.value as (typeof supported)[number]))
        throw new Error(`Unsupported function '${token.value}'`);
      return callNode(token.value as (typeof supported)[number], arguments_);
    }
    throw new Error(`Unexpected token '${token.value}'`);
  }
}

function callNode(name: ExpressionCallNode["name"], arguments_: ExpressionNode[]): ExpressionCallNode {
  const expectedArguments =
    name === "selected" || name === "regex" ? 2 : name === "if" ? 3 : name === "today" ? 0 : 1;
  if (arguments_.length !== expectedArguments) {
    throw new Error(`${name}() requires ${expectedArguments} arguments`);
  }
  switch (name) {
    case "selected":
    case "regex":
      return { type: "call", name, arguments: [arguments_[0]!, arguments_[1]!] };
    case "if":
      return { type: "call", name, arguments: [arguments_[0]!, arguments_[1]!, arguments_[2]!] };
    case "today":
      return { type: "call", name, arguments: [] };
    case "count-selected":
    case "string-length":
    case "int":
    case "date":
      return { type: "call", name, arguments: [arguments_[0]!] };
  }
}

export function parseExpression(source: string): ExpressionNode {
  return new Parser(tokenize(source.trim())).parse();
}

export interface ExpressionEvaluationOptions {
  currentValue?: AnswerValue | undefined;
  now?: Date | undefined;
}

function isEmpty(value: unknown): boolean {
  return value == null || value === "" || (Array.isArray(value) && value.length === 0);
}

function asBoolean(value: unknown): boolean {
  if (isEmpty(value) || value === false || value === 0 || value === "0" || value === "false") return false;
  return true;
}

function isIsoDate(value: unknown): value is string {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}(?:T.*)?$/.test(value);
}

function dateNumber(value: string): number {
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? Number.NaN : timestamp / 86_400_000;
}

function asNumber(value: unknown): number {
  if (typeof value === "number") return value;
  if (typeof value === "boolean") return value ? 1 : 0;
  if (isIsoDate(value)) return dateNumber(value);
  if (typeof value === "string" && value.trim() !== "") return Number(value);
  return Number.NaN;
}

function equal(left: unknown, right: unknown): boolean {
  if (isEmpty(left) && isEmpty(right)) return true;
  if (typeof left === "number" || typeof right === "number") {
    const leftNumber = asNumber(left);
    const rightNumber = asNumber(right);
    if (!Number.isNaN(leftNumber) && !Number.isNaN(rightNumber)) return leftNumber === rightNumber;
  }
  return String(left) === String(right);
}

export function evaluateExpression(
  node: ExpressionNode,
  data: SubmissionData,
  options: ExpressionEvaluationOptions = {}
): unknown {
  switch (node.type) {
    case "literal":
      return node.value;
    case "reference":
      return data[node.name];
    case "current":
      return options.currentValue;
    case "unary": {
      const value = evaluateExpression(node.operand, data, options);
      return node.operator === "not" ? !asBoolean(value) : -asNumber(value);
    }
    case "binary": {
      if (node.operator === "and")
        return (
          asBoolean(evaluateExpression(node.left, data, options)) &&
          asBoolean(evaluateExpression(node.right, data, options))
        );
      if (node.operator === "or")
        return (
          asBoolean(evaluateExpression(node.left, data, options)) ||
          asBoolean(evaluateExpression(node.right, data, options))
        );
      const left = evaluateExpression(node.left, data, options);
      const right = evaluateExpression(node.right, data, options);
      switch (node.operator) {
        case "=":
          return equal(left, right);
        case "!=":
          return !equal(left, right);
        case ">":
          return asNumber(left) > asNumber(right);
        case ">=":
          return asNumber(left) >= asNumber(right);
        case "<":
          return asNumber(left) < asNumber(right);
        case "<=":
          return asNumber(left) <= asNumber(right);
        case "+":
          return asNumber(left) + asNumber(right);
        case "-":
          return asNumber(left) - asNumber(right);
        case "*":
          return asNumber(left) * asNumber(right);
        case "div":
          return asNumber(left) / asNumber(right);
        case "mod":
          return asNumber(left) % asNumber(right);
      }
      return undefined;
    }
    case "call": {
      if (node.name === "if") {
        const condition = node.arguments[0];
        if (!condition) return undefined;
        const branch = asBoolean(evaluateExpression(condition, data, options))
          ? node.arguments[1]
          : node.arguments[2];
        return branch ? evaluateExpression(branch, data, options) : undefined;
      }
      const arguments_ = node.arguments.map((argument) => evaluateExpression(argument, data, options));
      switch (node.name) {
        case "selected": {
          const [value, wanted] = arguments_;
          if (Array.isArray(value)) return value.some((item) => equal(item, wanted));
          return equal(value, wanted);
        }
        case "regex": {
          const [value, pattern] = arguments_;
          if (isEmpty(value)) return false;
          return new RegExp(String(pattern)).test(String(value));
        }
        case "count-selected": {
          const value = arguments_[0];
          if (Array.isArray(value)) return value.length;
          if (typeof value === "string" && value.trim()) return value.trim().split(/\s+/).length;
          return 0;
        }
        case "string-length":
          return isEmpty(arguments_[0]) ? 0 : String(arguments_[0]).length;
        case "int":
          return Math.trunc(asNumber(arguments_[0]));
        case "today":
          return formatLocalDate(options.now ?? new Date());
        case "date": {
          const value = arguments_[0];
          if (isIsoDate(value)) return value.slice(0, 10);
          return value;
        }
      }
    }
  }
}
