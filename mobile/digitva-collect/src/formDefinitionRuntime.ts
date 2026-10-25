import type { InstrumentDefinition, WhoVaDraft } from "@drguptavivek/who-2022-va";

import {
  FormDefinitionError,
  downloadCurrentDefinition,
  prepareProjectInstrument,
  type DefinitionIdentity,
  type DefinitionRequest,
  type VerifiedFormDefinition,
} from "./formDefinitions";
import {
  downloadHistoricalDefinition,
  readDefinitionExtensions,
} from "./formDefinitionHistory";
import { loadWhoCoreRuntime } from "./whoCoreRuntime";

const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const EXTENSION_PATTERN = /^[a-z][a-z0-9_]{0,31}$/;

export interface DefinitionPin {
  readonly instrumentVersion: string;
  readonly definitionSha256: string;
  readonly definitionExtensions: readonly string[];
}

export interface ResolvedInstrument {
  readonly instrument: InstrumentDefinition;
  readonly provenance: "served" | "bundled-original";
  readonly pin: DefinitionPin | null;
}

export interface DefinitionCache {
  get(identity: DefinitionIdentity): Promise<VerifiedFormDefinition | undefined>;
  put(value: VerifiedFormDefinition): Promise<void>;
}

export class PinnedDefinitionError extends Error {
  constructor(
    public readonly code:
      | "partial_definition_pin"
      | "invalid_definition_pin"
      | "unknown_saved_definition"
      | "current_definition_unavailable",
  ) {
    super(code);
    this.name = "PinnedDefinitionError";
  }
}

class OptionalDefinitionRefreshError extends Error {
  constructor() {
    super("definition_unavailable");
    this.name = "OptionalDefinitionRefreshError";
  }
}

/** Parse the complete immutable server-form identity from an envelope. */
export function readDefinitionPin(envelope: unknown): DefinitionPin | null {
  if (!isRecord(envelope)) return null;
  const hasHash = Object.prototype.hasOwnProperty.call(envelope, "definitionSha256");
  const hasExtensions = Object.prototype.hasOwnProperty.call(envelope, "definitionExtensions");
  if (!hasHash && !hasExtensions) return null;
  if (!hasHash || !hasExtensions || typeof envelope.instrumentVersion !== "string" || !envelope.instrumentVersion.trim()) {
    throw new PinnedDefinitionError("partial_definition_pin");
  }
  const extensions = envelope.definitionExtensions;
  if (
    typeof envelope.definitionSha256 !== "string" ||
    !SHA256_PATTERN.test(envelope.definitionSha256) ||
    !Array.isArray(extensions) ||
    extensions.length > 16 ||
    extensions.some((extension) => typeof extension !== "string" || !EXTENSION_PATTERN.test(extension)) ||
    new Set(extensions).size !== extensions.length
  ) {
    throw new PinnedDefinitionError("invalid_definition_pin");
  }
  return Object.freeze({
    instrumentVersion: envelope.instrumentVersion,
    definitionSha256: envelope.definitionSha256,
    definitionExtensions: Object.freeze([...extensions].sort()),
  });
}

/** Add a validated pin without changing answer data or host timing metadata. */
export function withDefinitionPin<T extends WhoVaDraft>(envelope: T, pin: DefinitionPin | null): T {
  if (!pin) return { ...envelope };
  const validated = readDefinitionPin({
    instrumentVersion: pin.instrumentVersion,
    definitionSha256: pin.definitionSha256,
    definitionExtensions: pin.definitionExtensions,
  });
  if (!validated) throw new PinnedDefinitionError("invalid_definition_pin");
  return {
    ...envelope,
    instrumentVersion: validated.instrumentVersion,
    definitionSha256: validated.definitionSha256,
    definitionExtensions: [...validated.definitionExtensions],
  } as T;
}

export interface CurrentDefinitionOptions {
  instrumentVersion: string | null;
  definitionSha256: string | null;
  extensions: readonly string[];
}

/** Form-options values after mapping `instrument_version` and `definition_sha256`. */
export type RuntimeFormOptions = CurrentDefinitionOptions;

export interface BundledDefinitionCompatibility {
  instrument: InstrumentDefinition;
  instrumentVersion: string;
  extensions: readonly string[];
}

export interface ResolveNewInterviewDefinitionInput {
  accountId: string;
  projectId: string;
  options: RuntimeFormOptions;
  request: DefinitionRequest;
  cache: DefinitionCache;
  narrationLanguageCodes: readonly string[];
  bundledOriginal: BundledDefinitionCompatibility;
  canUseBundledFallback(): Promise<boolean>;
  onServedDefinition(): Promise<void>;
}

/** Resolve the current project definition, using the bundle only before first service. */
export async function resolveNewInterviewDefinition(
  input: ResolveNewInterviewDefinitionInput,
): Promise<ResolvedInstrument> {
  const { options } = input;
  const versionMissing = options.instrumentVersion === null || options.instrumentVersion === undefined;
  const hashMissing = options.definitionSha256 === null || options.definitionSha256 === undefined;
  if (versionMissing && hashMissing) {
    if (await input.canUseBundledFallback()) return bundled(input);
    throw new PinnedDefinitionError("current_definition_unavailable");
  }
  if (versionMissing || hashMissing || !options.instrumentVersion || !options.definitionSha256) {
    throw new FormDefinitionError("invalid_identity");
  }
  if (!SHA256_PATTERN.test(options.definitionSha256)) {
    throw new FormDefinitionError("invalid_identity");
  }
  const identity: DefinitionIdentity = {
    accountId: input.accountId,
    projectId: input.projectId,
    instrumentCode: "WHO_2022_VA",
    composedVersion: options.instrumentVersion,
    sha256: options.definitionSha256,
  };
  const cached = await input.cache.get(identity);
  if (cached) {
    assertExtensions(cached, options.extensions);
    await input.onServedDefinition();
    return served(cached, input.narrationLanguageCodes);
  }

  let downloaded;
  try {
    downloaded = await downloadCurrentDefinition({
      identity,
      request: async (path, options) => {
        let response: Awaited<ReturnType<DefinitionRequest>>;
        try {
          response = await input.request(path, options);
        } catch (error) {
          if (error instanceof TypeError || isAbortError(error) || (isRecord(error) && error.status === 503)) {
            throw new OptionalDefinitionRefreshError();
          }
          throw error;
        }
        if (response.status === 503) {
          throw new OptionalDefinitionRefreshError();
        }
        return response;
      },
    });
  } catch (error) {
    if (!isOptionalRefreshFailure(error)) throw error;
    if (await input.canUseBundledFallback()) {
      return bundled(input);
    }
    throw new PinnedDefinitionError("current_definition_unavailable");
  }
  assertExtensions(downloaded.value, options.extensions);
  await input.cache.put(downloaded.value);
  await input.onServedDefinition();
  return served(downloaded.value, input.narrationLanguageCodes);
}

async function bundled(input: ResolveNewInterviewDefinitionInput): Promise<ResolvedInstrument> {
  return {
    instrument: await prepareBundledInstrument(input.bundledOriginal.instrument, input.narrationLanguageCodes),
    provenance: "bundled-original",
    pin: null,
  };
}

export interface BundledLegacyDefinition {
  instrumentVersion: string;
  extensions: readonly string[];
  instrument: InstrumentDefinition;
}

export interface ResolveSavedEnvelopeDefinitionInput {
  accountId: string;
  projectId: string;
  envelope: unknown;
  request: DefinitionRequest;
  cache: DefinitionCache;
  narrationLanguageCodes: readonly string[];
  bundledLegacyDefinitions: readonly BundledLegacyDefinition[];
  legacyDefinitionExtensions?: readonly string[];
  /**
   * The bundled instrument a new interview would fall back to. A pinless draft
   * started on that fallback saved only `instrumentVersion`; when it matches
   * this bundle's version and the bundle carries no extensions, the draft
   * resumes on the bundle. A pinless draft records no extensions, so an
   * extension-bearing bundle (built from the project's current extensions)
   * could relabel it; that case and any other pinless version go to
   * `adoptCurrentDefinition`, or fail with `unknown_saved_definition` without it.
   */
  bundledOriginal?: BundledDefinitionCompatibility;
  /**
   * The project's current definition, for a pinless draft whose exact form
   * cannot be recovered: a pinless envelope records no fingerprint or
   * extensions, so no historical slice can be verified for it. The caller
   * tells the interviewer the form changed; its draft store pins the draft to
   * the returned definition and keeps answers the current form does not ask.
   */
  adoptCurrentDefinition?: () => Promise<ResolvedInstrument>;
}

const SUPPORTED_SAVED_INSTRUMENT_IDS = new Set(["WHO_2022_VA", "va_who_2022"]);
const NON_TAGGED_FORM_EXTENSIONS = new Set([
  "digitva_core",
  "doris_support_whova_2022",
  "intake_screen",
  "geography",
]);

/** The enabled extensions a served definition records as tags (sorted): the
 * non-tagged ones never appear in the definition, so they must not count when
 * comparing a pin with the project's form options. */
export function formTagExtensions(enabled: readonly string[]): string[] {
  return enabled.filter((ext) => !NON_TAGGED_FORM_EXTENSIONS.has(ext)).sort();
}

/** Recover the exact saved definition or fail without rewriting the envelope. */
export async function resolveSavedEnvelopeDefinition(
  input: ResolveSavedEnvelopeDefinitionInput,
): Promise<ResolvedInstrument> {
  if (
    !isRecord(input.envelope) ||
    typeof input.envelope.instrumentId !== "string" ||
    !SUPPORTED_SAVED_INSTRUMENT_IDS.has(input.envelope.instrumentId)
  ) {
    throw new PinnedDefinitionError("unknown_saved_definition");
  }
  const envelope = input.envelope;
  const pin = readDefinitionPin(envelope);
  if (!pin) {
    const legacyExtensions = input.legacyDefinitionExtensions;
    if (typeof envelope.instrumentVersion !== "string" || !envelope.instrumentVersion.trim()) {
      throw new PinnedDefinitionError("unknown_saved_definition");
    }
    const legacy = input.bundledLegacyDefinitions.find((candidate) =>
      candidate.instrumentVersion === envelope.instrumentVersion &&
      legacyExtensions !== undefined &&
      sameExtensions(candidate.extensions, legacyExtensions)
    );
    if (!legacy) {
      const fallback = input.bundledOriginal;
      if (
        fallback &&
        fallback.extensions.length === 0 &&
        fallback.instrumentVersion === envelope.instrumentVersion
      ) {
        return {
          instrument: await prepareBundledInstrument(fallback.instrument, input.narrationLanguageCodes),
          provenance: "bundled-original",
          pin: null,
        };
      }
      if (input.adoptCurrentDefinition) return input.adoptCurrentDefinition();
      throw new PinnedDefinitionError("unknown_saved_definition");
    }
    return {
      instrument: await prepareBundledInstrument(legacy.instrument, input.narrationLanguageCodes),
      provenance: "bundled-original",
      pin: null,
    };
  }

  const identity: DefinitionIdentity = {
    accountId: input.accountId,
    projectId: input.projectId,
    instrumentCode: "WHO_2022_VA",
    composedVersion: pin.instrumentVersion,
    sha256: pin.definitionSha256,
  };
  const cached = await input.cache.get(identity);
  let value = cached;
  if (value && !sameExtensions(readDefinitionExtensions(value), pin.definitionExtensions)) value = undefined;
  if (!value) {
    const downloaded = await downloadHistoricalDefinition({
      identity,
      extensions: pin.definitionExtensions,
      request: input.request,
    });
    value = downloaded.value;
    await input.cache.put(value);
  }
  return served(value, input.narrationLanguageCodes, pin);
}

async function served(
  value: VerifiedFormDefinition,
  narrationLanguageCodes: readonly string[],
  knownPin?: DefinitionPin,
): Promise<ResolvedInstrument> {
  const extensions = readDefinitionExtensions(value);
  return {
    instrument: await compilePreparedProjectInstrument(value, narrationLanguageCodes),
    provenance: "served",
    pin: knownPin ?? Object.freeze({
      instrumentVersion: value.identity.composedVersion,
      definitionSha256: value.identity.sha256,
      definitionExtensions: Object.freeze([...extensions]),
    }),
  };
}

async function compilePreparedProjectInstrument(
  value: VerifiedFormDefinition,
  narrationLanguageCodes: readonly string[],
): Promise<InstrumentDefinition> {
  const copy = prepareProjectInstrument(value, narrationLanguageCodes);
  try {
    const whoRuntime = await loadWhoCoreRuntime();
    whoRuntime.compileInstrumentDefinition(copy);
  } catch {
    throw new FormDefinitionError("invalid_definition");
  }
  return copy;
}

async function prepareBundledInstrument(
  definition: InstrumentDefinition,
  narrationLanguageCodes: readonly string[],
): Promise<InstrumentDefinition> {
  if (narrationLanguageCodes.some((code) => typeof code !== "string" || !code.trim())) {
    throw new FormDefinitionError("invalid_narration_languages");
  }
  const copy = JSON.parse(JSON.stringify(definition)) as InstrumentDefinition;
  const question = copy.questions.find((item) => item.name === "narr_language");
  if (question) {
    const allowed = new Set(narrationLanguageCodes);
    const choices = (question.choices ?? []).filter((choice) => allowed.has(choice.value));
    if (!choices.length) throw new FormDefinitionError("invalid_narration_languages");
    question.choices = choices;
    if (question.validation) question.validation.choiceValues = choices.map((choice) => choice.value);
  }
  try {
    const whoRuntime = await loadWhoCoreRuntime();
    whoRuntime.compileInstrumentDefinition(copy);
  } catch {
    throw new FormDefinitionError("invalid_definition");
  }
  return copy;
}

function assertExtensions(value: VerifiedFormDefinition, expected: readonly string[]): void {
  const actual = readDefinitionExtensions(value);
  if (sameExtensions(actual, expected)) return;
  const tagFilteredExpected = expected.filter((ext) => !NON_TAGGED_FORM_EXTENSIONS.has(ext));
  if (sameExtensions(actual, tagFilteredExpected)) return;
  throw new FormDefinitionError("invalid_definition");
}

function sameExtensions(left: readonly string[], right: readonly string[]): boolean {
  const sorted = [...right].sort();
  return left.length === sorted.length && left.every((extension, index) => extension === sorted[index]);
}

function isOptionalRefreshFailure(error: unknown): boolean {
  return error instanceof OptionalDefinitionRefreshError;
}

function isAbortError(error: unknown): boolean {
  return isRecord(error) && error.name === "AbortError";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}
