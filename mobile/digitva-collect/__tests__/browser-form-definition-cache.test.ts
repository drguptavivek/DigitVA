import * as Crypto from "expo-crypto";
import { createWhoVa2022Instrument } from "@drguptavivek/who-2022-va";

jest.mock("expo-crypto", () => {
  const { createHash } = require("node:crypto");
  return {
    CryptoDigestAlgorithm: { SHA256: "SHA-256" },
    CryptoEncoding: { HEX: "hex" },
    digestStringAsync: jest.fn(async (_algorithm: string, value: string) =>
      createHash("sha256").update(value, "utf8").digest("hex"),
    ),
  };
});

import {
  FormDefinitionError,
  verifyAndCompileDefinition,
  type DefinitionIdentity,
  type VerifiedFormDefinition,
} from "../src/formDefinitions";
import { createBrowserDefinitionCache } from "../src/client/formDefinitionCache";

const baseDefinition = createWhoVa2022Instrument(["narration_language"]);

async function digest(rawJson: string): Promise<string> {
  return Crypto.digestStringAsync(
    Crypto.CryptoDigestAlgorithm.SHA256,
    rawJson,
    { encoding: Crypto.CryptoEncoding.HEX },
  );
}

async function verified(input: {
  accountId?: string;
  projectId?: string;
  version?: string;
  title?: string;
} = {}): Promise<VerifiedFormDefinition> {
  const identity: DefinitionIdentity = {
    accountId: input.accountId ?? "account-1",
    projectId: input.projectId ?? "project-1",
    instrumentCode: "WHO_2022_VA",
    composedVersion: input.version ?? "20261005-a1b2c3d4e5",
    sha256: "",
  };
  const rawJson = JSON.stringify({
    ...baseDefinition,
    title: input.title ?? "WHO VA",
    version: identity.composedVersion,
    engineVersion: 1,
    extensions: [],
  });
  identity.sha256 = await digest(rawJson);
  return verifyAndCompileDefinition({
    rawJson,
    identity,
    responseSha256: identity.sha256,
    etag: '"form"',
  });
}

function deferred<T>(): {
  promise: Promise<T>;
  resolve(value: T): void;
} {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

it("isolates cache entries by the full definition identity and retains versions", async () => {
  const cache = createBrowserDefinitionCache("account-1");
  const first = await verified();
  const secondVersion = await verified({ version: "20261006-b2c3d4e5f6" });
  const sameVersionDifferentHash = await verified({ title: "Changed form" });
  const otherProject = await verified({ projectId: "project-2" });
  await Promise.all([
    cache.put(first),
    cache.put(secondVersion),
    cache.put(sameVersionDifferentHash),
    cache.put(otherProject),
  ]);

  await expect(cache.get(first.identity)).resolves.toMatchObject({ rawJson: first.rawJson });
  await expect(cache.get(secondVersion.identity)).resolves.toMatchObject({ rawJson: secondVersion.rawJson });
  await expect(cache.get(sameVersionDifferentHash.identity)).resolves.toMatchObject({ rawJson: sameVersionDifferentHash.rawJson });
  await expect(cache.get(otherProject.identity)).resolves.toMatchObject({ rawJson: otherProject.rawJson });
});

it("rejects identities from another account on read and write", async () => {
  const cache = createBrowserDefinitionCache("account-1");
  const otherAccount = await verified({ accountId: "account-2" });

  await expect(cache.put(otherAccount)).rejects.toMatchObject({ code: "invalid_identity" });
  await expect(cache.get(otherAccount.identity)).rejects.toMatchObject({ code: "invalid_identity" });
});

it("rejects a corrupted definition without replacing an existing entry", async () => {
  const cache = createBrowserDefinitionCache("account-1");
  const original = await verified();
  await cache.put(original);
  const corrupt: VerifiedFormDefinition = {
    ...original,
    rawJson: `${original.rawJson} `,
  };

  await expect(cache.put(corrupt)).rejects.toBeInstanceOf(FormDefinitionError);
  await expect(cache.get(original.identity)).resolves.toMatchObject({ rawJson: original.rawJson });
});

it("returns a fresh compiled object and preserves the caller's input identity", async () => {
  const cache = createBrowserDefinitionCache("account-1");
  const original = await verified();
  const input: VerifiedFormDefinition = {
    ...original,
    identity: { ...original.identity },
  };
  const put = cache.put(input);
  input.identity.projectId = "project-mutated";
  await put;

  const firstRead = await cache.get(original.identity);
  expect(firstRead?.identity.projectId).toBe("project-1");
  firstRead!.definition.title = "caller mutation";
  const nextRead = await cache.get(original.identity);
  expect(nextRead?.definition.title).toBe("WHO VA");
});

it("removes every version for one project and leaves other projects intact", async () => {
  const cache = createBrowserDefinitionCache("account-1");
  const projectOne = await verified();
  const projectOneOlder = await verified({ version: "20261004-z9y8x7w6v5" });
  const projectTwo = await verified({ projectId: "project-2" });
  await Promise.all([cache.put(projectOne), cache.put(projectOneOlder), cache.put(projectTwo)]);

  cache.removeProject("project-1");

  await expect(cache.get(projectOne.identity)).resolves.toBeUndefined();
  await expect(cache.get(projectOneOlder.identity)).resolves.toBeUndefined();
  await expect(cache.get(projectTwo.identity)).resolves.toMatchObject({ rawJson: projectTwo.rawJson });
});

it.each(["clear", "removeProject"] as const)("cancels a pending put when %s runs", async (action) => {
  const cache = createBrowserDefinitionCache("account-1");
  const value = await verified();
  const digestMock = Crypto.digestStringAsync as jest.MockedFunction<typeof Crypto.digestStringAsync>;
  const pendingDigest = deferred<string>();
  digestMock.mockImplementationOnce(() => pendingDigest.promise);

  const put = cache.put(value);
  await Promise.resolve();
  if (action === "clear") cache.clear();
  else cache.removeProject(value.identity.projectId);
  pendingDigest.resolve(value.identity.sha256);
  await put;

  await expect(cache.get(value.identity)).resolves.toBeUndefined();
});

it("clears entries and invalidates in-flight writes", async () => {
  const cache = createBrowserDefinitionCache("account-1");
  const first = await verified();
  const next = await verified({ projectId: "project-2" });
  await cache.put(first);
  cache.clear();

  await expect(cache.get(first.identity)).resolves.toBeUndefined();
  await cache.put(next);
  await expect(cache.get(next.identity)).resolves.toMatchObject({ rawJson: next.rawJson });
});
