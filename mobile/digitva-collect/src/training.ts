/**
 * Training in the Expo app (docs/policy/training-demo-project.md, "Onboarding and the public page").
 *
 * The Training screens ask the server for the training scope with `training=1`; the server re-checks the active
 * participation on every request. The scope comes from the route a screen sits on, never from a query a user edits.
 */
import type { AccessSummary, ClientBootstrap, ClientCsrf, TrainingArea } from "./api";
import { accessCapabilities, requestClientJson } from "./api";
import type { JsonRequester } from "./workspace/api";

/** Canonical browser routes.  The area keys intentionally remain the server's stable scope names. */
export const TRAINING_ROUTES: Record<TrainingArea, string> = {
  interview: "/training/interview",
  coding: "/training/coding",
  review: "/training/reviewing",
};

export const TRAINING_REPORTING_ROUTE = "/training/reporting";
export const TRAINING_INTERVIEW_CASE_ROUTE = "/training/interview/case";
export const TRAINING_INTERVIEW_FORM_ROUTE = "/training/interview/form";
export const TRAINING_CODING_CASE_ROUTE = "/training/coding/case";
export const TRAINING_REVIEWING_CASE_ROUTE = "/training/reviewing/case";

/** Legacy compatibility only: canonical routes never infer scope from a query parameter. */
export function hasLegacyTrainingParam(value: unknown): boolean {
  return (Array.isArray(value) ? value[0] : value) === "1";
}

/** Where an interview, once left, returns to. */
export const TRAINING_INTERVIEW_HOME = TRAINING_ROUTES.interview;

/** The Training sub-menus the signed-in user's participations open (empty without a participation). */
export function trainingAreas(access: Pick<AccessSummary, "training"> | undefined): TrainingArea[] {
  return access?.training?.areas ?? [];
}

/** Whether *projectId* is the training project. */
export function isTrainingProject(access: Pick<AccessSummary, "training"> | undefined, projectId: string | undefined | null): boolean {
  return Boolean(projectId) && access?.training?.project_id === projectId;
}

/**
 * The bootstrap the Training screens run on: the same user and CSRF, but only the training project, only the roles
 * held there, and `scope: "training"`, so the ordinary Interview screens (lists, registration, supervision) offer
 * nothing else and ask the server for `training=1`. Undefined without a participation. The server still checks the
 * participation on every request.
 */
export function trainingBootstrap(bootstrap: ClientBootstrap): ClientBootstrap | undefined {
  const project = bootstrap.access.training?.project;
  if (!project || trainingAreas(bootstrap.access).length === 0) return undefined;
  const roles = [...new Set(project.grants.filter((grant) => grant.active).map((grant) => grant.role))].sort();
  const access: AccessSummary = {
    ...bootstrap.access, roles, projects: [project], demo_coding: { available: false, project_ids: [] },
  };
  return { ...bootstrap, csrf: { ...bootstrap.csrf, training: true }, access, capabilities: accessCapabilities(access), scope: "training" };
}

/**
 * Whether a request for *projectId* takes the training scope (plan N10): exactly when it is the training project.
 * *trainingProjectId* is `access.training.project_id` (or the phone's remembered copy of it).
 */
export function scopeFor(trainingProjectId: string | null | undefined, projectId: string | null | undefined): boolean {
  return Boolean(projectId) && trainingProjectId === projectId;
}

/** *path* with `training=1` when *training*, unless it already names a scope. */
export function trainingScopedPath(path: string, training: boolean): string {
  if (!training || /[?&]training=/.test(path)) return path;
  return `${path}${path.includes("?") ? "&" : "?"}training=1`;
}

/**
 * The phone's collection access (training mode): the user's projects plus the training project while a
 * participation gives grants there, appended last so the default project choice is unchanged. Unchanged without one,
 * or from an older server (no `session_types`).
 */
export function withTrainingCollection<T extends Pick<AccessSummary, "projects" | "training">>(access: T): T {
  const project = access.training?.project;
  // `session_types` marks a server with session types: before them a legacy (S001) participation never trained on
  // the phone, and a new APK on such a server keeps today's behaviour.
  if (!project || !Array.isArray(access.training?.session_types) || access.projects.some((entry) => entry.project_id === project.project_id)) return access;
  return { ...access, projects: [...access.projects, project] };
}

/** Whether the user holds a typed (non-legacy) training session: the training queue buttons need one. */
export function hasTypedTrainingSession(access: Pick<AccessSummary, "training"> | undefined): boolean {
  return (access?.training?.session_types ?? []).some((type) => typeof type === "string" && type.length > 0);
}

/** A requester that asks every list, count and allocation route for the training scope (`?training=1`). */
export function trainingRequester(request: JsonRequester): JsonRequester {
  return (path, init) => request(`${path}${path.includes("?") ? "&" : "?"}training=1`, init);
}

export interface TrainingParticipation {
  role: string;
  coder_slot: number | null;
  onboarded_at: string | null;
  session_code: string;
  session_name: string;
  /** interviewer, coder or self_coding; null for a legacy session; absent from older servers. */
  session_type?: string | null;
}

export interface TrainingMe {
  project_id: string | null;
  areas: TrainingArea[];
  pending: boolean;
  participations: TrainingParticipation[];
}

/** `GET /api/v1/training/me`: the caller's own active participations. */
export function getTrainingMe(csrf: ClientCsrf): Promise<TrainingMe> {
  return requestClientJson<TrainingMe>("/api/v1/training/me", { csrf });
}

/** `POST /api/v1/training/me/start`: records `onboarded_at`; idempotent. */
export function startTraining(csrf: ClientCsrf): Promise<TrainingMe> {
  return requestClientJson<TrainingMe>("/api/v1/training/me/start", { method: "POST", csrf });
}

const REDIRECT_KEY = "digitva.training.redirected";

/**
 * Whether the Expo home should send a trainee with a pending Start to `/training`: once per browser session
 * (sessionStorage; where it is unavailable, once per page load). Marks the redirect as used when it says yes.
 */
let redirectedInMemory = false;
export function takeTrainingRedirect(access: Pick<AccessSummary, "training"> | undefined): boolean {
  if (!access?.training?.pending || access.training.areas.length === 0) return false;
  try {
    if (typeof sessionStorage !== "undefined") {
      if (sessionStorage.getItem(REDIRECT_KEY)) return false;
      sessionStorage.setItem(REDIRECT_KEY, "1");
      return true;
    }
  } catch {
    // Storage blocked: fall back to the in-memory flag.
  }
  if (redirectedInMemory) return false;
  redirectedInMemory = true;
  return true;
}
