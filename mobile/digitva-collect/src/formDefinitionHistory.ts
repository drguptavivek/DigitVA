import {
  FormDefinitionError,
  verifyAndCompileDefinition,
  type CurrentDefinitionDownload,
  type DefinitionIdentity,
  type DefinitionRequest,
  type VerifiedFormDefinition,
} from "./formDefinitions";
import type { RawApiResponse } from "./api";

/** Errors raised when a historical definition slice is invalid or unavailable. */
export class FormDefinitionHistoryError extends Error {
  constructor(
    public readonly code:
      | "invalid_extensions"
      | "definition_slice_mismatch"
      | "invalid_definition",
  ) {
    super(code);
    this.name = "FormDefinitionHistoryError";
  }
}

const EXTENSION_PATTERN = /^[a-z][a-z0-9_]{0,31}$/;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;

/** Read the sorted top-level extension names from the verified response body. */
export function readDefinitionExtensions(
  value: VerifiedFormDefinition,
): readonly string[] {
  const definition = value.definition as unknown as { extensions?: unknown };
  return normalizeExtensions(definition.extensions);
}

/** Recover one exact historical project slice, using only a fully matching verified cache. */
export async function downloadHistoricalDefinition(input: {
  identity: DefinitionIdentity;
  extensions: readonly string[];
  request: DefinitionRequest;
  cached?: VerifiedFormDefinition;
}): Promise<CurrentDefinitionDownload> {
  assertIdentity(input.identity);
  const requestedExtensions = normalizeExtensions(input.extensions);
  let cached: VerifiedFormDefinition | undefined;

  if (input.cached && sameIdentity(input.cached.identity, input.identity)) {
    try {
      const verified = await verifyAndCompileDefinition({
        rawJson: input.cached.rawJson,
        identity: input.cached.identity,
        responseSha256: input.cached.identity.sha256,
        etag: input.cached.etag,
      });
      if (sameExtensions(readDefinitionExtensions(verified), requestedExtensions)) {
        cached = verified;
      }
    } catch {
      // A stale or corrupt cache must not prevent an unconditional recovery.
    }
  }

  const path = historicalDefinitionPath(input.identity, requestedExtensions);
  const firstResponse = await input.request(
    path,
    cached?.etag ? { ifNoneMatch: cached.etag } : {},
  );
  if (firstResponse.status === 304) {
    if (cached) {
      if (firstResponse.headers.definitionSha256 !== input.identity.sha256) {
        throw new FormDefinitionError("definition_hash_mismatch");
      }
      if (firstResponse.headers.etag && firstResponse.headers.etag !== cached.etag) {
        throw new FormDefinitionHistoryError("invalid_definition");
      }
      return { kind: "not-modified", value: cached };
    }

    const retry = await input.request(path, {});
    if (retry.status === 304) {
      throw new FormDefinitionHistoryError("invalid_definition");
    }
    return downloadedDefinition(retry, input.identity, requestedExtensions);
  }
  return downloadedDefinition(firstResponse, input.identity, requestedExtensions);
}

function assertIdentity(identity: DefinitionIdentity): void {
  if (
    !identity ||
    typeof identity.accountId !== "string" || !identity.accountId.trim() ||
    typeof identity.projectId !== "string" || !identity.projectId.trim() ||
    identity.instrumentCode !== "WHO_2022_VA" ||
    typeof identity.composedVersion !== "string" || !identity.composedVersion.trim() ||
    typeof identity.sha256 !== "string" || !SHA256_PATTERN.test(identity.sha256)
  ) {
    throw new FormDefinitionError("invalid_identity");
  }
}

function normalizeExtensions(value: unknown): readonly string[] {
  if (
    !Array.isArray(value) ||
    value.length > 16 ||
    value.some((name) => typeof name !== "string" || !EXTENSION_PATTERN.test(name)) ||
    new Set(value).size !== value.length
  ) {
    throw new FormDefinitionHistoryError("invalid_extensions");
  }
  return Object.freeze([...value].sort());
}

function sameExtensions(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((name, index) => name === right[index]);
}

function sameIdentity(left: DefinitionIdentity, right: DefinitionIdentity): boolean {
  return left.accountId === right.accountId &&
    left.projectId === right.projectId &&
    left.instrumentCode === right.instrumentCode &&
    left.composedVersion === right.composedVersion &&
    left.sha256 === right.sha256;
}

function historicalDefinitionPath(
  identity: DefinitionIdentity,
  extensions: readonly string[],
): string {
  return `/api/v1/instruments/${encodeURIComponent(identity.instrumentCode)}/definition` +
    `?project_id=${encodeURIComponent(identity.projectId)}` +
    `&version=${encodeURIComponent(identity.composedVersion)}` +
    `&extensions=${encodeURIComponent(extensions.join(","))}`;
}

async function downloadedDefinition(
  response: RawApiResponse,
  identity: DefinitionIdentity,
  requestedExtensions: readonly string[],
): Promise<CurrentDefinitionDownload> {
  if (response.status !== 200 || response.body === null) {
    throw new FormDefinitionHistoryError("invalid_definition");
  }
  const value = await verifyAndCompileDefinition({
    rawJson: response.body,
    identity,
    responseSha256: response.headers.definitionSha256,
    etag: response.headers.etag,
  });
  if (!sameExtensions(readDefinitionExtensions(value), requestedExtensions)) {
    throw new FormDefinitionHistoryError("definition_slice_mismatch");
  }
  return { kind: "downloaded", value };
}
