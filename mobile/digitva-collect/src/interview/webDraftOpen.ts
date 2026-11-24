/**
 * Finding or starting the server draft the browser interview screen (src/web/InterviewScreen.tsx) opens, and
 * resolving the form definition it is answered on. Moved out of the screen's initialise with every request, its
 * order and its staleness checks unchanged: a superseded open returns undefined where the screen used to return,
 * and failures reject as they did.
 *
 * Web only (the server draft API); imports nothing native.
 */
import {
  ClientApiError,
  getCaseDetail,
  getProjectFormOptions,
  startDraft,
  type DraftResponse,
  type FormOptions,
  type IntakeBootstrap,
} from "../client/api";
import { getRevisionDetail, type RevisionDetail } from "../client/revisions";
import {
  readDefinitionPin,
  resolveNewInterviewDefinition,
  resolveSavedEnvelopeDefinition,
  type DefinitionCache,
  type ResolvedInstrument,
} from "../formDefinitionRuntime";
import type { DefinitionRequest } from "../formDefinitions";
import type { WhoCoreRuntime } from "../whoCoreRuntime";

type Csrf = Parameters<typeof getProjectFormOptions>[1];

/** The session one open runs in. */
export interface WebDraftOpenContext {
  core: WhoCoreRuntime;
  accountId: string;
  links: { intakeDrafts: string; intakeCases: string };
  csrf: Csrf;
  request: DefinitionRequest;
  cache: DefinitionCache;
  /** False once the account, session or route changed under this open. */
  isCurrent(): boolean;
  hasServedDefinition(projectId: string): boolean;
  markServedDefinition(projectId: string): Promise<void>;
}

/** The route params that name what to open. */
export interface WebDraftParams {
  draftId?: string;
  revisionDraftId?: string;
  revisionProjectId?: string;
  revisionSiteId?: string;
  revisionVaSid?: string;
  deathId?: string;
  projectId?: string;
  siteId?: string;
  orgUnitId?: string;
}

/** The project's default instrument code; only WHO_2022_VA is supported. */
export function instrumentCode(options: FormOptions): string {
  const code = options.form_types?.find((formType) => formType.is_default)?.instrument_code;
  if (code !== "WHO_2022_VA") throw new Error("unsupported_instrument");
  return code;
}

function narrationLanguageCodes(options: FormOptions): string[] {
  return (options.narration_languages ?? []).map((language) => language.code);
}

function definitionOptions(options: FormOptions) {
  return {
    instrumentVersion: options.instrument_version ?? null,
    definitionSha256: options.definition_sha256 ?? null,
    extensions: options.enabled_extensions ?? [],
  };
}

/** The project's current served form for a new draft; the bundled one only before any was served. */
export async function resolveNewDefinition(context: WebDraftOpenContext, projectId: string, formOptions: FormOptions): Promise<ResolvedInstrument> {
  const { isCurrent } = context;
  instrumentCode(formOptions);
  const bundled = context.core.createWhoVa2022Instrument(formOptions.enabled_extensions ?? []);
  return resolveNewInterviewDefinition({
    accountId: context.accountId,
    projectId,
    options: definitionOptions(formOptions),
    request: context.request,
    cache: context.cache,
    narrationLanguageCodes: narrationLanguageCodes(formOptions),
    interviewLanguages: formOptions.narration_languages ?? [],
    bundledOriginal: {
      instrument: bundled,
      instrumentVersion: bundled.version,
      extensions: formOptions.enabled_extensions ?? [],
    },
    canUseBundledFallback: async () => isCurrent() && !context.hasServedDefinition(projectId),
    onServedDefinition: async () => {
      if (!isCurrent()) throw new Error("request_superseded");
      await context.markServedDefinition(projectId);
      if (!isCurrent()) throw new Error("request_superseded");
    },
  });
}

/** The draft an open lands on; `options` and `resolved` are set when a new draft was started on them. */
export interface OpenedDraft {
  draftId: string;
  revision?: RevisionDetail;
  options?: FormOptions;
  resolved?: ResolvedInstrument;
}

/**
 * The draft the route names: a revision's, the interviewer's own on a case (started when there is none), or a new
 * direct start on a project and site. `onDraftId` hears each id as soon as it is known. Undefined when superseded;
 * rejects with `draft_missing` when the route names nothing to open.
 */
export async function openInterviewDraft(
  context: WebDraftOpenContext,
  params: WebDraftParams,
  intake: IntakeBootstrap,
  onDraftId: (draftId: string) => void,
): Promise<OpenedDraft | undefined> {
  const { csrf, isCurrent, links } = context;
  let nextDraftId = params.draftId;
  let nextRevision: RevisionDetail | undefined;
  let options: FormOptions | undefined;
  let resolved: ResolvedInstrument | undefined;
  if (params.revisionDraftId) {
    if (!params.revisionProjectId || !params.revisionSiteId || !params.revisionVaSid) {
      throw new ClientApiError(400, "malformed_response");
    }
    nextRevision = await getRevisionDetail(links.intakeDrafts, params.revisionDraftId, csrf, {
      draft_id: params.revisionDraftId,
      project_id: params.revisionProjectId,
      site_id: params.revisionSiteId,
      va_sid: params.revisionVaSid,
    });
    if (!isCurrent()) return undefined;
    nextDraftId = nextRevision.draft.draft_id;
    onDraftId(nextDraftId);
  }
  if (!nextDraftId && params.deathId) {
    const { case: caseRow } = await getCaseDetail(links.intakeCases, params.deathId, csrf);
    if (!isCurrent()) return undefined;
    if (!caseRow?.prefill) throw new Error("caseActionsUnavailable");
    if (!caseRow.project_id || !caseRow.site_id) throw new Error("case_context_missing");
    if (caseRow.my_draft_id) {
      nextDraftId = caseRow.my_draft_id;
      onDraftId(nextDraftId);
    } else {
      options = await getProjectFormOptions(caseRow.project_id, csrf);
      if (!isCurrent()) return undefined;
      resolved = await resolveNewDefinition(context, caseRow.project_id, options);
      if (!isCurrent()) return undefined;
      const started = await startDraft(
        links.intakeDrafts,
        {
          project_id: caseRow.project_id,
          site_id: caseRow.site_id,
          ...(caseRow.org_unit_id ? { org_unit_id: caseRow.org_unit_id } : {}),
          death_id: params.deathId
        },
        csrf
      );
      if (!isCurrent()) return undefined;
      nextDraftId = started.draft.draft_id;
      onDraftId(nextDraftId);
    }
  }
  if (!nextDraftId && !params.deathId && params.projectId && params.siteId) {
    const site = intake.context.find((entry) => entry.project_id === params.projectId && entry.site_id === params.siteId);
    if (!site || !["direct", "both"].includes(site.web_intake_mode ?? "")) throw new Error("intake_configuration_unavailable");
    options = await getProjectFormOptions(params.projectId, csrf);
    if (!isCurrent()) return undefined;
    resolved = await resolveNewDefinition(context, params.projectId, options);
    if (!isCurrent()) return undefined;
    const started = await startDraft(
      links.intakeDrafts,
      {
        project_id: params.projectId,
        site_id: params.siteId,
        ...(params.orgUnitId ? { org_unit_id: params.orgUnitId } : {})
      },
      csrf
    );
    if (!isCurrent()) return undefined;
    nextDraftId = started.draft.draft_id;
    onDraftId(nextDraftId);
  }
  if (!nextDraftId) throw new Error("draft_missing");
  return { draftId: nextDraftId, revision: nextRevision, options, resolved };
}

/**
 * The form an existing draft or revision is answered on: a pinless draft from before pins gets the current form;
 * otherwise its own pinned form, from the cache or the server. A draft whose form cannot be recovered moves to the
 * current one (`adopted`); a revision never does, it must keep its submitted form.
 */
export async function resolveDraftDefinition(
  context: WebDraftOpenContext,
  draft: DraftResponse | RevisionDetail,
  revision: RevisionDetail | undefined,
  options: FormOptions,
): Promise<{ resolved: ResolvedInstrument; adopted: boolean }> {
  let adopted = false;
  if (!revision && !readDefinitionPin(draft.envelope) && !draft.envelope.instrumentVersion) {
    return { resolved: await resolveNewDefinition(context, draft.draft.project_id, options), adopted };
  }
  const bundledFallback = context.core.createWhoVa2022Instrument(options.enabled_extensions ?? []);
  const projectId = draft.draft.project_id;
  const formOptions = options;
  const resolved = await resolveSavedEnvelopeDefinition({
    accountId: context.accountId,
    projectId: draft.draft.project_id,
    envelope: draft.envelope,
    request: context.request,
    cache: context.cache,
    narrationLanguageCodes: narrationLanguageCodes(options),
    interviewLanguages: options.narration_languages ?? [],
    bundledLegacyDefinitions: [],
    bundledOriginal: {
      instrument: bundledFallback,
      instrumentVersion: bundledFallback.version,
      extensions: options.enabled_extensions ?? [],
    },
    // A revision must keep its submitted form, so only a draft moves on.
    adoptCurrentDefinition: revision ? undefined : async () => {
      adopted = true;
      return resolveNewDefinition(context, projectId, formOptions);
    },
  });
  return { resolved, adopted };
}
