import { ApiError } from "../../api";
import type { JsonRequester } from "../api";
import { WorkspaceContractError, type JsonObject, type WorkspaceIdentity } from "../contracts";

export interface DorisOption {
  code: string;
  title: string;
  uri: string;
  has_children: boolean;
  block_uri?: string;
}

export interface DorisAxis {
  id: string;
  label: string;
  required: boolean;
  allow_multiple_values: "AllowAlways" | "NotAllowed" | "AllowedExceptFromSameBlock";
  options: DorisOption[];
  subtree_uris: string[];
  truncated: boolean;
}

export interface DorisPostcoordination {
  stem: DorisOption;
  axes: DorisAxis[];
  other_postcoordination: null | { subtree_uris: string[] };
  truncated: boolean;
}

export interface DorisRelated {
  composite: DorisOption | null;
  terms: Array<DorisOption & { requires_postcoordination: boolean }>;
  truncated: boolean;
}

export interface DorisHierarchy {
  selected: DorisOption;
  ancestors: DorisOption[];
  siblings: DorisOption[];
  children: DorisOption[];
  related_maternal: DorisOption[];
  related_perinatal: DorisOption[];
  truncated: boolean;
}

function record(value: unknown, field: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error(`Invalid DORIS response: ${field}`);
  return value as Record<string, unknown>;
}

function text(value: unknown, field: string): string {
  if (typeof value !== "string") throw new Error(`Invalid DORIS response: ${field}`);
  return value;
}

function boolean(value: unknown, field: string): boolean {
  if (typeof value !== "boolean") throw new Error(`Invalid DORIS response: ${field}`);
  return value;
}

function option(value: unknown, field: string): DorisOption {
  const source = record(value, field);
  return {
    code: text(source.code, `${field}.code`),
    title: text(source.title, `${field}.title`),
    uri: text(source.uri, `${field}.uri`),
    has_children: source.has_children === undefined ? false : boolean(source.has_children, `${field}.has_children`),
    ...(typeof source.block_uri === "string" ? { block_uri: source.block_uri } : {}),
  };
}

function options(value: unknown, field: string): DorisOption[] {
  if (!Array.isArray(value)) throw new Error(`Invalid DORIS response: ${field}`);
  return value.map((item, index) => option(item, `${field}[${index}]`));
}

function stringList(value: unknown, field: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) throw new Error(`Invalid DORIS response: ${field}`);
  return value as string[];
}

function nestedDorisError(error: unknown): never {
  if (!(error instanceof ApiError) || !error.payload) throw error;
  const nested = error.payload.error;
  if (!nested || typeof nested !== "object" || Array.isArray(nested)) throw error;
  const source = nested as Record<string, unknown>;
  if (error.payload.schema_version !== 1 || typeof source.code !== "string" || typeof source.message !== "string") throw new WorkspaceContractError("doris.error");
  const normalized = new ApiError(error.status, source.code, error.redirectUrl, error.csrf, error.payload);
  normalized.message = source.message;
  throw normalized;
}

/** Calls a case-scoped guidance endpoint and rejects malformed or stale-shaped replies. */
export async function dorisGuidance<T>(
  request: JsonRequester,
  identity: WorkspaceIdentity,
  endpoint: "postcoordination" | "postcoordination-options" | "hierarchy" | "related",
  body: JsonObject,
  parse: (value: unknown) => T,
): Promise<T> {
  try {
    const result = await request(`/api/v1/doris-clinical/${endpoint}/${encodeURIComponent(identity.vaSid)}`, {
      method: "POST",
      json: { schema_version: 1, ...body },
    });
    return parse(result);
  } catch (error) {
    return nestedDorisError(error);
  }
}

/** Validates the WHO stem and axes needed to build a complete expression. */
export function parseDorisPostcoordination(value: unknown): DorisPostcoordination {
  const source = record(value, "postcoordination");
  if (source.schema_version !== 1 || !Array.isArray(source.axes)) throw new Error("Invalid DORIS postcoordination response.");
  const other = source.other_postcoordination === null ? null : record(source.other_postcoordination, "other_postcoordination");
  return {
    stem: option(source.stem, "stem"),
    axes: source.axes.map((raw, index) => {
      const axis = record(raw, `axes[${index}]`);
      const multiple = text(axis.allow_multiple_values, `axes[${index}].allow_multiple_values`);
      if (!["AllowAlways", "NotAllowed", "AllowedExceptFromSameBlock"].includes(multiple)) throw new Error("Invalid DORIS axis rule.");
      return {
        id: text(axis.id, `axes[${index}].id`),
        label: text(axis.label, `axes[${index}].label`),
        required: boolean(axis.required, `axes[${index}].required`),
        allow_multiple_values: multiple as DorisAxis["allow_multiple_values"],
        options: options(axis.options, `axes[${index}].options`),
        subtree_uris: stringList(axis.subtree_uris, `axes[${index}].subtree_uris`),
        truncated: boolean(axis.truncated, `axes[${index}].truncated`),
      };
    }),
    other_postcoordination: other ? { subtree_uris: stringList(other.subtree_uris, "other_postcoordination.subtree_uris") } : null,
    truncated: boolean(source.truncated, "truncated"),
  };
}

/** Validates one bounded WHO axis-option page before presenting its items. */
export function parseDorisOptions(value: unknown): { items: DorisOption[]; truncated: boolean } {
  const source = record(value, "postcoordination_options");
  if (source.schema_version !== 1) throw new Error("Invalid DORIS option response.");
  return { items: options(source.items, "items"), truncated: boolean(source.truncated, "truncated") };
}

/** Validates the WHO hierarchy and related lists used by the selector. */
export function parseDorisHierarchy(value: unknown): DorisHierarchy {
  const source = record(value, "hierarchy");
  if (source.schema_version !== 1) throw new Error("Invalid DORIS hierarchy response.");
  return {
    selected: option(source.selected, "selected"),
    ancestors: options(source.ancestors, "ancestors"),
    siblings: options(source.siblings, "siblings"),
    children: options(source.children, "children"),
    related_maternal: options(source.related_maternal, "related_maternal"),
    related_perinatal: options(source.related_perinatal, "related_perinatal"),
    truncated: boolean(source.truncated, "truncated"),
  };
}

/** Validates WHO maternal/perinatal terms and their optional composite. */
export function parseDorisRelated(value: unknown): DorisRelated {
  const source = record(value, "related");
  if (source.schema_version !== 1 || !Array.isArray(source.terms)) throw new Error("Invalid DORIS related response.");
  return {
    composite: source.composite === null ? null : option(source.composite, "composite"),
    terms: source.terms.map((raw, index) => {
      const item = record(raw, `terms[${index}]`);
      return { ...option(item, `terms[${index}]`), requires_postcoordination: boolean(item.requires_postcoordination, `terms[${index}].requires_postcoordination`) };
    }),
    truncated: boolean(source.truncated, "truncated"),
  };
}
