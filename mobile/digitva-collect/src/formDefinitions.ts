import * as Crypto from "expo-crypto";
import {
  compileInstrumentDefinition,
  ENGINE_VERSION,
  type InstrumentDefinition,
} from "@drguptavivek/who-2022-va";

import type { RawApiResponse } from "./api";

export interface DefinitionIdentity {
  accountId: string;
  projectId: string;
  instrumentCode: "WHO_2022_VA";
  composedVersion: string;
  sha256: string;
}

export interface VerifiedFormDefinition {
  identity: DefinitionIdentity;
  etag: string | null;
  engineVersion: number;
  rawJson: string;
  definition: InstrumentDefinition;
}

export type DefinitionRequest = (
  path: string,
  options: { ifNoneMatch?: string },
) => Promise<RawApiResponse>;

export interface CurrentDefinitionDownload {
  kind: "downloaded" | "not-modified";
  value: VerifiedFormDefinition;
}

export class FormDefinitionError extends Error {
  constructor(
    public readonly code:
      | "invalid_identity"
      | "invalid_definition"
      | "definition_hash_mismatch"
      | "definition_version_mismatch"
      | "incompatible_engine"
      | "invalid_narration_languages",
  ) {
    super(code);
    this.name = "FormDefinitionError";
  }
}

const SHA256_PATTERN = /^[0-9a-f]{64}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function assertIdentity(identity: DefinitionIdentity): void {
  if (
    !identity ||
    typeof identity.accountId !== "string" ||
    !identity.accountId.trim() ||
    typeof identity.projectId !== "string" ||
    !identity.projectId.trim() ||
    identity.instrumentCode !== "WHO_2022_VA" ||
    typeof identity.composedVersion !== "string" ||
    !identity.composedVersion.trim() ||
    typeof identity.sha256 !== "string" ||
    !SHA256_PATTERN.test(identity.sha256)
  ) {
    throw new FormDefinitionError("invalid_identity");
  }
}

function sameIdentity(
  left: DefinitionIdentity,
  right: DefinitionIdentity,
): boolean {
  return (
    left.accountId === right.accountId &&
    left.projectId === right.projectId &&
    left.instrumentCode === right.instrumentCode &&
    left.composedVersion === right.composedVersion &&
    left.sha256 === right.sha256
  );
}

/** Verify exact response text and compile its schema and expressions before use. */
export async function verifyAndCompileDefinition(input: {
  rawJson: string;
  identity: DefinitionIdentity;
  responseSha256: string | null;
  etag: string | null;
}): Promise<VerifiedFormDefinition> {
  assertIdentity(input.identity);
  if (
    typeof input.rawJson !== "string" ||
    !input.responseSha256 ||
    !SHA256_PATTERN.test(input.responseSha256) ||
    input.responseSha256 !== input.identity.sha256
  ) {
    throw new FormDefinitionError("definition_hash_mismatch");
  }
  const digest = await Crypto.digestStringAsync(
    Crypto.CryptoDigestAlgorithm.SHA256,
    input.rawJson,
    { encoding: Crypto.CryptoEncoding.HEX },
  );
  if (digest !== input.identity.sha256) {
    throw new FormDefinitionError("definition_hash_mismatch");
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(input.rawJson);
  } catch {
    throw new FormDefinitionError("invalid_definition");
  }
  if (
    !isRecord(parsed) ||
    typeof parsed.id !== "string" ||
    !parsed.id.trim() ||
    !Array.isArray(parsed.sections) ||
    !Array.isArray(parsed.questions)
  ) {
    throw new FormDefinitionError("invalid_definition");
  }
  if (parsed.version !== input.identity.composedVersion) {
    throw new FormDefinitionError("definition_version_mismatch");
  }
  if (
    !Number.isInteger(parsed.engineVersion) ||
    Number(parsed.engineVersion) < 1
  ) {
    throw new FormDefinitionError("invalid_definition");
  }
  const engineVersion = Number(parsed.engineVersion);
  if (engineVersion > ENGINE_VERSION) {
    throw new FormDefinitionError("incompatible_engine");
  }

  let definition: InstrumentDefinition;
  try {
    definition = parsed as unknown as InstrumentDefinition;
    compileInstrumentDefinition(definition);
  } catch {
    throw new FormDefinitionError("invalid_definition");
  }
  return Object.freeze({
    identity: Object.freeze({ ...input.identity }),
    etag: input.etag,
    engineVersion,
    rawJson: input.rawJson,
    definition,
  });
}

/** Download only the current project slice, using an ETag from the same verified identity. */
export async function downloadCurrentDefinition(input: {
  identity: DefinitionIdentity;
  request: DefinitionRequest;
  cached?: VerifiedFormDefinition;
}): Promise<CurrentDefinitionDownload> {
  assertIdentity(input.identity);
  let cached: VerifiedFormDefinition | undefined;
  if (input.cached && sameIdentity(input.cached.identity, input.identity)) {
    try {
      cached = await verifyAndCompileDefinition({
        rawJson: input.cached.rawJson,
        identity: input.cached.identity,
        responseSha256: input.cached.identity.sha256,
        etag: input.cached.etag,
      });
    } catch (error) {
      if (
        !(error instanceof FormDefinitionError) ||
        !["definition_hash_mismatch", "invalid_definition", "definition_version_mismatch"].includes(error.code)
      ) {
        throw error;
      }
    }
  }
  const path = `/api/v1/instruments/${encodeURIComponent(input.identity.instrumentCode)}/definition?project_id=${encodeURIComponent(input.identity.projectId)}`;
  const firstResponse = await input.request(
    path,
    cached?.etag ? { ifNoneMatch: cached.etag } : {},
  );
  if (firstResponse.status === 304) {
    if (cached) {
      if (
        (firstResponse.headers.definitionSha256 &&
          firstResponse.headers.definitionSha256 !== input.identity.sha256) ||
        (firstResponse.headers.etag &&
          cached.etag &&
          firstResponse.headers.etag !== cached.etag)
      ) {
        throw new FormDefinitionError("definition_hash_mismatch");
      }
      return { kind: "not-modified", value: cached };
    }
    const retry = await input.request(path, {});
    if (retry.status === 304)
      throw new FormDefinitionError("invalid_definition");
    return downloadedDefinition(retry, input.identity);
  }
  return downloadedDefinition(firstResponse, input.identity);
}

async function downloadedDefinition(
  response: RawApiResponse,
  identity: DefinitionIdentity,
): Promise<CurrentDefinitionDownload> {
  if (response.status !== 200 || response.body === null) {
    throw new FormDefinitionError("invalid_definition");
  }
  const value = await verifyAndCompileDefinition({
    rawJson: response.body,
    identity,
    responseSha256: response.headers.definitionSha256,
    etag: response.headers.etag,
  });
  return { kind: "downloaded", value };
}

/** Copy a verified definition and narrow only the project-specific narration-language choices. */
export function prepareProjectInstrument(
  definition: VerifiedFormDefinition,
  narrationLanguages: readonly string[],
): InstrumentDefinition {
  if (
    !Array.isArray(narrationLanguages) ||
    narrationLanguages.some(
      (language) => typeof language !== "string" || !language.trim(),
    )
  ) {
    throw new FormDefinitionError("invalid_narration_languages");
  }
  const copy = JSON.parse(
    JSON.stringify(definition.definition),
  ) as InstrumentDefinition;
  const question = copy.questions.find((item) => item.name === "narr_language");
  if (question) {
    const allowed = new Set(narrationLanguages);
    const choices = (question.choices ?? []).filter((choice) =>
      allowed.has(choice.value),
    );
    if (!choices.length)
      throw new FormDefinitionError("invalid_narration_languages");
    question.choices = choices;
    if (question.validation)
      question.validation.choiceValues = choices.map((choice) => choice.value);
  }
  try {
    compileInstrumentDefinition(copy);
  } catch {
    throw new FormDefinitionError("invalid_definition");
  }
  return copy;
}
