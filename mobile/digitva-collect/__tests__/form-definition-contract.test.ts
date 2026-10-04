import * as Crypto from "expo-crypto";
import { createWhoVa2022Instrument } from "@drguptavivek/who-2022-va";

jest.mock("expo-crypto", () => {
  const { createHash } = require("node:crypto");
  return {
    CryptoDigestAlgorithm: { SHA256: "SHA-256" },
    CryptoEncoding: { HEX: "hex" },
    digestStringAsync: async (_algorithm: string, value: string) =>
      createHash("sha256").update(value, "utf8").digest("hex"),
  };
});

import {
  downloadCurrentDefinition,
  FormDefinitionError,
  prepareProjectInstrument,
  verifyAndCompileDefinition,
  type DefinitionIdentity,
  type VerifiedFormDefinition,
} from "../src/formDefinitions";
import type { RawApiResponse } from "../src/api";

const composedVersion = "20261005-a1b2c3d4e5";
const baseDefinition = createWhoVa2022Instrument(["narration_language"]);

async function digest(rawJson: string): Promise<string> {
  return Crypto.digestStringAsync(
    Crypto.CryptoDigestAlgorithm.SHA256,
    rawJson,
    { encoding: Crypto.CryptoEncoding.HEX },
  );
}

async function definition(
  engineVersion = 1,
): Promise<{ identity: DefinitionIdentity; rawJson: string }> {
  const rawJson = JSON.stringify({
    ...baseDefinition,
    title: "WHO VA survey — सर्वेक्षण",
    version: composedVersion,
    engineVersion,
  });
  return {
    identity: {
      accountId: "account-1",
      projectId: "Project / One",
      instrumentCode: "WHO_2022_VA",
      composedVersion,
      sha256: await digest(rawJson),
    },
    rawJson,
  };
}

function rawResponse(
  status: number,
  body: string | null,
  sha256: string | null,
  etag: string | null,
): RawApiResponse {
  return {
    status,
    body,
    headers: { etag, definitionSha256: sha256, contentEncoding: null },
  };
}

it("hashes exact UTF-8 JSON text, including non-ASCII labels, and preserves it", async () => {
  const { identity, rawJson } = await definition();
  const verified = await verifyAndCompileDefinition({
    rawJson,
    identity,
    responseSha256: identity.sha256,
    etag: '"current"',
  });
  expect(verified.rawJson).toBe(rawJson);
  expect(verified.definition.title).toContain("सर्वेक्षण");
  expect(Object.isFrozen(verified.definition)).toBe(true);
  expect(Object.isFrozen(verified.definition.questions)).toBe(true);
});

it("fails closed on BOM text, corrupt text, mismatched hashes, and versions", async () => {
  const { identity, rawJson } = await definition();
  await expect(
    verifyAndCompileDefinition({
      rawJson: `\uFEFF${rawJson}`,
      identity: { ...identity, sha256: await digest(`\uFEFF${rawJson}`) },
      responseSha256: await digest(`\uFEFF${rawJson}`),
      etag: null,
    }),
  ).rejects.toMatchObject({ code: "invalid_definition" });
  await expect(
    verifyAndCompileDefinition({
      rawJson: `${rawJson} `,
      identity,
      responseSha256: identity.sha256,
      etag: null,
    }),
  ).rejects.toBeInstanceOf(FormDefinitionError);
  await expect(
    verifyAndCompileDefinition({
      rawJson,
      identity,
      responseSha256: "f".repeat(64),
      etag: null,
    }),
  ).rejects.toMatchObject({ code: "definition_hash_mismatch" });
  await expect(
    verifyAndCompileDefinition({
      rawJson,
      identity: { ...identity, composedVersion: "older-version" },
      responseSha256: identity.sha256,
      etag: null,
    }),
  ).rejects.toMatchObject({ code: "definition_version_mismatch" });
});

it("distinguishes an engine update from malformed controls and expressions", async () => {
  const tooNew = await definition(2);
  await expect(
    verifyAndCompileDefinition({
      rawJson: tooNew.rawJson,
      identity: tooNew.identity,
      responseSha256: tooNew.identity.sha256,
      etag: null,
    }),
  ).rejects.toMatchObject({ code: "incompatible_engine" });

  const { identity, rawJson } = await definition();
  const parsed = JSON.parse(rawJson) as typeof baseDefinition & {
    engineVersion: number;
  };
  const unsupported = JSON.stringify({
    ...parsed,
    questions: parsed.questions.map((question, index) =>
      index === 0 ? { ...question, control: "unsupported" } : question,
    ),
  });
  const unsupportedIdentity = {
    ...identity,
    sha256: await digest(unsupported),
  };
  await expect(
    verifyAndCompileDefinition({
      rawJson: unsupported,
      identity: unsupportedIdentity,
      responseSha256: unsupportedIdentity.sha256,
      etag: null,
    }),
  ).rejects.toMatchObject({ code: "invalid_definition" });

  const invalidExpression = JSON.stringify({
    ...parsed,
    questions: parsed.questions.map((question, index) =>
      index === 0 ? { ...question, relevant: { source: "(" } } : question,
    ),
  });
  const expressionIdentity = {
    ...identity,
    sha256: await digest(invalidExpression),
  };
  await expect(
    verifyAndCompileDefinition({
      rawJson: invalidExpression,
      identity: expressionIdentity,
      responseSha256: expressionIdentity.sha256,
      etag: null,
    }),
  ).rejects.toMatchObject({ code: "invalid_definition" });
});

it("uses only a same-identity ETag and retries an uncached 304 once without it", async () => {
  const { identity, rawJson } = await definition();
  const cached = await verifyAndCompileDefinition({
    rawJson,
    identity,
    responseSha256: identity.sha256,
    etag: '"cached"',
  });
  const request = jest
    .fn<Promise<RawApiResponse>, [string, { ifNoneMatch?: string }]>()
    .mockResolvedValue(rawResponse(304, null, identity.sha256, '"cached"'));
  await expect(
    downloadCurrentDefinition({ identity, request, cached }),
  ).resolves.toMatchObject({
    kind: "not-modified",
    value: { rawJson, identity, etag: '"cached"' },
  });
  expect(request).toHaveBeenCalledWith(
    "/api/v1/instruments/WHO_2022_VA/definition?project_id=Project%20%2F%20One",
    { ifNoneMatch: '"cached"' },
  );

  const downloaded = jest
    .fn<Promise<RawApiResponse>, [string, { ifNoneMatch?: string }]>()
    .mockResolvedValueOnce(rawResponse(304, null, null, null))
    .mockResolvedValueOnce(
      rawResponse(200, rawJson, identity.sha256, '"fresh"'),
    );
  await expect(
    downloadCurrentDefinition({ identity, request: downloaded }),
  ).resolves.toMatchObject({ kind: "downloaded" });
  expect(downloaded.mock.calls.map(([, options]) => options)).toEqual([{}, {}]);
});

it("treats a corrupted same-identity cache as a miss and downloads unconditionally", async () => {
  const { identity, rawJson } = await definition();
  const cached = {
    identity,
    rawJson: `${rawJson} `,
    definition: JSON.parse(rawJson),
    engineVersion: 1,
    etag: '"corrupt-cache"',
  } as VerifiedFormDefinition;
  const request = jest
    .fn<Promise<RawApiResponse>, [string, { ifNoneMatch?: string }]>()
    .mockResolvedValue(rawResponse(200, rawJson, identity.sha256, '"current"'));

  await expect(
    downloadCurrentDefinition({ identity, request, cached }),
  ).resolves.toMatchObject({ kind: "downloaded", value: { rawJson } });
  expect(request).toHaveBeenCalledWith(
    "/api/v1/instruments/WHO_2022_VA/definition?project_id=Project%20%2F%20One",
    {},
  );
});

it("treats invalid JSON and uncompilable same-identity caches as misses", async () => {
  const { identity, rawJson } = await definition();
  const parsed = JSON.parse(rawJson) as typeof baseDefinition & {
    engineVersion: number;
  };
  const uncompilable = JSON.stringify({
    ...parsed,
    questions: parsed.questions.map((question, index) =>
      index === 0 ? { ...question, control: "unsupported" } : question,
    ),
  });
  const originalDigest = Crypto.digestStringAsync.bind(Crypto);

  for (const cachedRawJson of ["{", uncompilable]) {
    const digestSpy = jest
      .spyOn(Crypto, "digestStringAsync")
      .mockImplementation(async (_algorithm, value) =>
        value === cachedRawJson ? identity.sha256 : originalDigest(
          Crypto.CryptoDigestAlgorithm.SHA256,
          value,
          { encoding: Crypto.CryptoEncoding.HEX },
        ),
      );
    const cached = {
      identity,
      rawJson: cachedRawJson,
      definition: JSON.parse(rawJson),
      engineVersion: 1,
      etag: '"corrupt-cache"',
    } as VerifiedFormDefinition;
    const request = jest
      .fn<Promise<RawApiResponse>, [string, { ifNoneMatch?: string }]>()
      .mockResolvedValue(rawResponse(200, rawJson, identity.sha256, '"current"'));

    await expect(
      downloadCurrentDefinition({ identity, request, cached }),
    ).resolves.toMatchObject({ kind: "downloaded", value: { rawJson } });
    expect(request).toHaveBeenCalledWith(
      "/api/v1/instruments/WHO_2022_VA/definition?project_id=Project%20%2F%20One",
      {},
    );
    digestSpy.mockRestore();
  }
});

it("rejects a response header mismatch and narrows narration choices on a copy", async () => {
  const { identity, rawJson } = await definition();
  const mismatched = jest
    .fn<Promise<RawApiResponse>, [string, { ifNoneMatch?: string }]>()
    .mockResolvedValue(rawResponse(200, rawJson, "d".repeat(64), '"current"'));
  await expect(
    downloadCurrentDefinition({ identity, request: mismatched }),
  ).rejects.toMatchObject({ code: "definition_hash_mismatch" });

  const verified = await verifyAndCompileDefinition({
    rawJson,
    identity,
    responseSha256: identity.sha256,
    etag: null,
  });
  const before = verified.definition.questions.find(
    (question) => question.name === "narr_language",
  )!;
  const originalValues = before.choices?.map((choice) => choice.value);
  const prepared = prepareProjectInstrument(verified, ["hindi"]);
  const narrowed = prepared.questions.find(
    (question) => question.name === "narr_language",
  )!;
  expect(narrowed.choices?.map((choice) => choice.value)).toEqual(["hindi"]);
  expect(narrowed.validation?.choiceValues).toEqual(["hindi"]);
  expect(before.choices?.map((choice) => choice.value)).toEqual(originalValues);
  expect(prepared).not.toBe(verified.definition);
  expect(() => prepareProjectInstrument(verified, [])).toThrow(
    FormDefinitionError,
  );
});
