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
  FormDefinitionError,
  verifyAndCompileDefinition,
  type DefinitionIdentity,
  type VerifiedFormDefinition,
} from "../src/formDefinitions";
import {
  downloadHistoricalDefinition,
  FormDefinitionHistoryError,
  readDefinitionExtensions,
} from "../src/formDefinitionHistory";
import { ApiError, type RawApiResponse } from "../src/api";

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
  extensions: readonly string[] = [],
): Promise<{ identity: DefinitionIdentity; rawJson: string }> {
  const rawJson = JSON.stringify({
    ...baseDefinition,
    title: "WHO VA survey — सर्वेक्षण",
    version: composedVersion,
    engineVersion: 1,
    extensions: [...extensions],
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

async function verified(
  extensions: readonly string[] = [],
  accountId = "account-1",
): Promise<VerifiedFormDefinition> {
  const result = await definition(extensions);
  const identity = { ...result.identity, accountId };
  return verifyAndCompileDefinition({
    rawJson: result.rawJson,
    identity,
    responseSha256: identity.sha256,
    etag: '"cached"',
  });
}

it("verifies exact raw UTF-8 content and reads the top-level extension slice", async () => {
  const { identity, rawJson } = await definition(["social_autopsy", "geography"]);
  const result = await downloadHistoricalDefinition({
    identity,
    extensions: ["geography", "social_autopsy"],
    request: async () => rawResponse(200, rawJson, identity.sha256, '"history"'),
  });

  expect(result.kind).toBe("downloaded");
  expect(result.value.rawJson).toBe(rawJson);
  expect(result.value.definition.title).toContain("सर्वेक्षण");
  expect(readDefinitionExtensions(result.value)).toEqual(["geography", "social_autopsy"]);
});

it("encodes historical query values and preserves an explicit empty extensions parameter", async () => {
  const empty = await definition();
  const emptyRequest = jest.fn().mockResolvedValue(
    rawResponse(200, empty.rawJson, empty.identity.sha256, '"empty"'),
  );
  await downloadHistoricalDefinition({
    identity: empty.identity,
    extensions: [],
    request: emptyRequest,
  });
  expect(emptyRequest.mock.calls[0][0]).toBe(
    "/api/v1/instruments/WHO_2022_VA/definition?project_id=Project%20%2F%20One" +
      `&version=${encodeURIComponent(composedVersion)}&extensions=`,
  );

  const { identity, rawJson } = await definition(["medical_records", "social_autopsy"]);
  const request = jest.fn().mockResolvedValue(
    rawResponse(200, rawJson, identity.sha256, '"history"'),
  );
  await downloadHistoricalDefinition({ identity, extensions: ["social_autopsy", "medical_records"], request });
  expect(request.mock.calls[0][0]).toContain("&extensions=medical_records%2Csocial_autopsy");
});

it("uses a 304 only for the matching verified project and extension slice", async () => {
  const cached = await verified(["geography"]);
  const request = jest.fn().mockResolvedValue(
    rawResponse(304, null, cached.identity.sha256, cached.etag),
  );
  await expect(downloadHistoricalDefinition({
    identity: cached.identity,
    extensions: ["geography"],
    request,
    cached,
  })).resolves.toMatchObject({ kind: "not-modified", value: { rawJson: cached.rawJson } });
  expect(request.mock.calls[0][1]).toEqual({ ifNoneMatch: '"cached"' });
});

it("does not reuse a same-version cache for another slice or account", async () => {
  const cachedSlice = await verified(["geography"]);
  const { identity, rawJson } = await definition(["social_autopsy"]);
  const request = jest.fn().mockResolvedValue(
    rawResponse(200, rawJson, identity.sha256, '"fresh"'),
  );
  await downloadHistoricalDefinition({ identity, extensions: ["social_autopsy"], request, cached: cachedSlice });
  expect(request.mock.calls[0][1]).toEqual({});

  const otherAccount = await verified(["social_autopsy"], "account-2");
  const sameAccountRequest = jest.fn().mockResolvedValue(
    rawResponse(200, rawJson, identity.sha256, '"fresh"'),
  );
  await downloadHistoricalDefinition({
    identity,
    extensions: ["social_autopsy"],
    request: sameAccountRequest,
    cached: otherAccount,
  });
  expect(sameAccountRequest.mock.calls[0][1]).toEqual({});
});

it("retries one unexpected 304 without a validator and fails on a repeated 304", async () => {
  const { identity, rawJson } = await definition();
  const retry = jest.fn()
    .mockResolvedValueOnce(rawResponse(304, null, identity.sha256, '"old"'))
    .mockResolvedValueOnce(rawResponse(200, rawJson, identity.sha256, '"fresh"'));
  await expect(downloadHistoricalDefinition({ identity, extensions: [], request: retry }))
    .resolves.toMatchObject({ kind: "downloaded" });
  expect(retry.mock.calls.map(([, options]) => options)).toEqual([{}, {}]);

  const repeated = jest.fn().mockResolvedValue(rawResponse(304, null, identity.sha256, '"old"'));
  await expect(downloadHistoricalDefinition({ identity, extensions: [], request: repeated }))
    .rejects.toMatchObject({ code: "invalid_definition" });
  expect(repeated).toHaveBeenCalledTimes(2);
});

it("rejects hash and returned-slice mismatches", async () => {
  const { identity, rawJson } = await definition(["geography"]);
  await expect(downloadHistoricalDefinition({
    identity,
    extensions: ["geography"],
    request: async () => rawResponse(200, rawJson, "f".repeat(64), '"bad"'),
  })).rejects.toBeInstanceOf(FormDefinitionError);

  const wrongSlice = await definition(["social_autopsy"]);
  await expect(downloadHistoricalDefinition({
    identity: wrongSlice.identity,
    extensions: ["geography"],
    request: async () => rawResponse(200, wrongSlice.rawJson, wrongSlice.identity.sha256, '"wrong"'),
  })).rejects.toMatchObject({ code: "definition_slice_mismatch" });

  const cached = await verified(["geography"]);
  const wrong304 = jest.fn().mockResolvedValue(
    rawResponse(304, null, "e".repeat(64), cached.etag),
  );
  await expect(downloadHistoricalDefinition({
    identity: cached.identity,
    extensions: ["geography"],
    request: wrong304,
    cached,
  })).rejects.toMatchObject({ code: "definition_hash_mismatch" });
});

it("rejects malformed extension names, duplicates, and more than sixteen names before requesting", async () => {
  const { identity } = await definition();
  const request = jest.fn();
  const invalid = [
    ["Bad-name"],
    ["a", "a"],
    Array.from({ length: 17 }, (_, index) => `extension_${index}`),
  ];
  for (const extensions of invalid) {
    await expect(downloadHistoricalDefinition({ identity, extensions, request }))
      .rejects.toBeInstanceOf(FormDefinitionHistoryError);
  }
  expect(request).not.toHaveBeenCalled();
});

it("propagates auth, history, extension, and network failures unchanged", async () => {
  const { identity } = await definition();
  const refusals = [
    new ApiError(401, "unauthorized"),
    new ApiError(404, "version_unknown"),
    new ApiError(422, "invalid_extensions"),
  ];
  const network = new Error("network unavailable");
  for (const refusal of refusals) {
    await expect(downloadHistoricalDefinition({
      identity,
      extensions: [],
      request: async () => { throw refusal; },
    })).rejects.toBe(refusal);
  }
  await expect(downloadHistoricalDefinition({
    identity,
    extensions: [],
    request: async () => { throw network; },
  })).rejects.toBe(network);
});
