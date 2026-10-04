import * as Crypto from "expo-crypto";
import { createWhoVa2022Instrument, type WhoVaDraft } from "@drguptavivek/who-2022-va";

jest.mock("expo-crypto", () => {
  const { createHash } = require("node:crypto");
  return {
    CryptoDigestAlgorithm: { SHA256: "SHA-256" },
    CryptoEncoding: { HEX: "hex" },
    digestStringAsync: async (_algorithm: string, value: string) =>
      createHash("sha256").update(value, "utf8").digest("hex"),
  };
});

import { verifyAndCompileDefinition, type DefinitionIdentity, type VerifiedFormDefinition } from "../src/formDefinitions";
import { FormDefinitionHistoryError } from "../src/formDefinitionHistory";
import {
  PinnedDefinitionError,
  readDefinitionPin,
  resolveNewInterviewDefinition,
  resolveSavedEnvelopeDefinition,
  withDefinitionPin,
  type DefinitionCache,
} from "../src/formDefinitionRuntime";
import type { RawApiResponse } from "../src/api";

const projectId = "Project / One";
const accountId = "account-1";
const version = "20261005-a1b2c3d4e5";
const baseInstrument = createWhoVa2022Instrument(["narration_language"]);

async function verified(extensions: readonly string[] = ["geography"]): Promise<VerifiedFormDefinition> {
  const rawJson = JSON.stringify({
    ...baseInstrument,
    version,
    engineVersion: 1,
    extensions: [...extensions],
  });
  const sha256 = await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, rawJson, { encoding: Crypto.CryptoEncoding.HEX });
  const identity: DefinitionIdentity = {
    accountId,
    projectId,
    instrumentCode: "WHO_2022_VA",
    composedVersion: version,
    sha256,
  };
  return verifyAndCompileDefinition({ rawJson, identity, responseSha256: sha256, etag: '"current"' });
}

function response(value: VerifiedFormDefinition): RawApiResponse {
  return {
    status: 200,
    body: value.rawJson,
    headers: { etag: value.etag, definitionSha256: value.identity.sha256, contentEncoding: null },
  };
}

function cache(): DefinitionCache & { get: jest.Mock; put: jest.Mock } {
  return { get: jest.fn().mockResolvedValue(undefined), put: jest.fn().mockResolvedValue(undefined) };
}

function newInput(value: VerifiedFormDefinition, request: (path: string) => Promise<RawApiResponse>) {
  return {
    accountId,
    projectId,
    options: {
      instrumentVersion: version,
      definitionSha256: value.identity.sha256,
      extensions: ["geography"],
    },
    request: jest.fn(request),
    cache: cache(),
    narrationLanguageCodes: ["hindi"],
    bundledOriginal: { instrument: baseInstrument, instrumentVersion: "2026081401", extensions: [] },
    canUseBundledFallback: jest.fn().mockResolvedValue(false),
    onServedDefinition: jest.fn().mockResolvedValue(undefined),
  };
}

it("parses only complete pins and preserves answers and device times when applying one", () => {
  const envelope = {
    id: "draft-1",
    instrumentVersion: version,
    data: { answer: "kept" },
    startedAt: "2026-10-05T10:00:00+05:30",
    definitionSha256: "a".repeat(64),
    definitionExtensions: ["social_autopsy", "geography"],
  } as unknown as WhoVaDraft;
  expect(readDefinitionPin(envelope)).toEqual({
    instrumentVersion: version,
    definitionSha256: "a".repeat(64),
    definitionExtensions: ["geography", "social_autopsy"],
  });
  expect(readDefinitionPin({ instrumentVersion: version, data: {} })).toBeNull();
  expect(() => readDefinitionPin({ instrumentVersion: version, definitionSha256: "a".repeat(64) })).toThrow(
    PinnedDefinitionError,
  );
  const pinned = withDefinitionPin(envelope, readDefinitionPin(envelope));
  const hostPinned = pinned as WhoVaDraft & { startedAt?: string; definitionExtensions?: readonly string[] };
  expect(hostPinned.data).toEqual({ answer: "kept" });
  expect(hostPinned.startedAt).toBe("2026-10-05T10:00:00+05:30");
  expect(hostPinned.definitionExtensions).toEqual(["geography", "social_autopsy"]);
});

it("downloads, verifies, caches and pins the exact current project slice", async () => {
  const value = await verified();
  const input = newInput(value, async () => response(value));
  const result = await resolveNewInterviewDefinition(input);
  expect(input.request).toHaveBeenCalledWith(
    `/api/v1/instruments/WHO_2022_VA/definition?project_id=${encodeURIComponent(projectId)}`,
    {},
  );
  expect(input.cache.put).toHaveBeenCalledWith(value);
  expect(input.onServedDefinition).toHaveBeenCalledTimes(1);
  expect(result).toMatchObject({
    provenance: "served",
    pin: { instrumentVersion: version, definitionSha256: value.identity.sha256, definitionExtensions: ["geography"] },
  });
  expect(result.instrument.questions.find((question) => question.name === "narr_language")?.choices?.map((choice) => choice.value)).toEqual(["hindi"]);
});

it("uses the bundle only before the first verified service on transient failure or missing current metadata", async () => {
  const value = await verified();
  const input = newInput(value, async () => { throw new TypeError("offline"); });
  input.canUseBundledFallback.mockResolvedValue(true);
  await expect(resolveNewInterviewDefinition(input)).resolves.toMatchObject({ provenance: "bundled-original", pin: null });

  const missing = newInput(value, async () => response(value));
  missing.canUseBundledFallback.mockResolvedValue(true);
  await expect(resolveNewInterviewDefinition({
    ...missing,
    options: { instrumentVersion: null, definitionSha256: null, extensions: [] },
  })).resolves.toMatchObject({ provenance: "bundled-original", pin: null });

  const partial = newInput(value, async () => response(value));
  partial.canUseBundledFallback.mockResolvedValue(true);
  await expect(resolveNewInterviewDefinition({
    ...partial,
    options: { instrumentVersion: version, definitionSha256: null, extensions: [] },
  })).rejects.toMatchObject({ code: "invalid_identity" });
  expect(partial.canUseBundledFallback).not.toHaveBeenCalled();

  const unavailable = newInput(value, async () => ({ status: 503, body: null, headers: response(value).headers }));
  unavailable.canUseBundledFallback.mockResolvedValue(true);
  await expect(resolveNewInterviewDefinition(unavailable)).resolves.toMatchObject({ provenance: "bundled-original" });

  const aborted = newInput(value, async () => { throw Object.assign(new Error("aborted"), { name: "AbortError" }); });
  aborted.canUseBundledFallback.mockResolvedValue(true);
  await expect(resolveNewInterviewDefinition(aborted)).resolves.toMatchObject({ provenance: "bundled-original" });

  input.canUseBundledFallback.mockResolvedValue(false);
  await expect(resolveNewInterviewDefinition(input)).rejects.toMatchObject({ code: "current_definition_unavailable" });
});

it.each([404, 408, 429, 500, 401, 403])("does not use the bundle for HTTP %i", async (status) => {
  const value = await verified();
  const input = newInput(value, async () => ({ status, body: null, headers: response(value).headers }));
  input.canUseBundledFallback.mockResolvedValue(true);
  await expect(resolveNewInterviewDefinition(input)).rejects.toBeInstanceOf(Error);
  expect(input.canUseBundledFallback).not.toHaveBeenCalled();
});

it("never hides a corrupt current definition or uses the bundle for a saved pinned definition", async () => {
  const value = await verified();
  const input = newInput(value, async () => ({ ...response(value), headers: { ...response(value).headers, definitionSha256: "f".repeat(64) } }));
  input.canUseBundledFallback.mockResolvedValue(true);
  await expect(resolveNewInterviewDefinition(input)).rejects.toMatchObject({ code: "definition_hash_mismatch" });

  const pin = {
    instrumentVersion: version,
    definitionSha256: value.identity.sha256,
    definitionExtensions: ["geography"],
  };
  const request = jest.fn(async (path: string) => {
    expect(path).toContain(`version=${encodeURIComponent(version)}&extensions=geography`);
    return response(value);
  });
  const saved = await resolveSavedEnvelopeDefinition({
    accountId,
    projectId,
    envelope: { instrumentId: "WHO_2022_VA", ...pin, data: { answer: "kept" } },
    request: jest.fn(request),
    cache: cache(),
    narrationLanguageCodes: ["hindi"],
    bundledLegacyDefinitions: [],
  });
  expect(saved).toMatchObject({ provenance: "served", pin });

  const offline = jest.fn().mockRejectedValue(new FormDefinitionHistoryError("invalid_definition"));
  await expect(resolveSavedEnvelopeDefinition({
    accountId, projectId,
    envelope: { instrumentId: "WHO_2022_VA", ...pin, data: { answer: "kept" } },
    request: offline,
    cache: cache(),
    narrationLanguageCodes: ["hindi"],
    bundledLegacyDefinitions: [],
  })).rejects.toBeInstanceOf(FormDefinitionHistoryError);
});

it("uses an unpinned legacy bundle only for its saved version and saved extensions", async () => {
  const legacy = [{ instrumentVersion: version, extensions: [], instrument: baseInstrument }];
  const input = {
    accountId,
    projectId,
    envelope: { instrumentId: "WHO_2022_VA", instrumentVersion: version, data: { answer: "kept" } },
    request: jest.fn(),
    cache: cache(),
    narrationLanguageCodes: ["hindi"],
    bundledLegacyDefinitions: legacy,
    legacyDefinitionExtensions: [],
  };
  await expect(resolveSavedEnvelopeDefinition(input)).resolves.toMatchObject({ provenance: "bundled-original", pin: null });
  await expect(resolveSavedEnvelopeDefinition({ ...input, envelope: { ...input.envelope, instrumentVersion: "unknown-old" } })).rejects.toMatchObject({
    code: "unknown_saved_definition",
  });
  expect(input.request).not.toHaveBeenCalled();
});
