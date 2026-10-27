import { ApiError } from "./api";
import { SessionRevokedError, SignInRequiredError } from "./auth";
import { FormDefinitionError } from "./formDefinitions";
import { PinnedDefinitionError } from "./formDefinitionRuntime";
import { t } from "./i18n";
import { errorText } from "./ui";

/** User-facing text for a revision in the attention state, and for a failed revision open. */
export function attentionMessage(code: string | null): string {
  switch (code) {
    case "revision_locked":
      return t("revisionLocked");
    case "case_already_submitted":
      return t("revisionAlreadySubmitted");
    case "case_closed":
      return t("revisionCaseClosed");
    case "case_state_conflict":
      return t("revisionCaseConflict");
    case "invalid_reason":
    case "required_finish_partial":
      return t("revisionInvalidReason");
    case "not_found":
      return t("revisionUnavailable");
    case "invalid_definition_pin":
      return t("revisionPinInvalid");
    case "answers_hash_invalid":
    case "local_hash_mismatch":
    case "invalid_revision_snapshot":
    case "invalid_revision_ack":
      return t("revisionRetry");
    default:
      return t("revisionRetry");
  }
}

export function loadFailureMessage(error: unknown): string {
  if (error instanceof FormDefinitionError && error.code === "incompatible_engine") {
    return "Update the app to open this form. Your saved answers remain on this device.";
  }
  if (error instanceof PinnedDefinitionError && error.code === "unknown_saved_definition") {
    return "This interview's original form is unavailable. Your saved answers remain on this device.";
  }
  if (error instanceof Error && error.message === "revision_project_unavailable") {
    return t("revisionUnavailable");
  }
  if (error instanceof ApiError) {
    if (error.code === "revision_locked") return t("revisionLocked");
    if (error.code === "case_already_submitted") return t("revisionAlreadySubmitted");
    if (error.code === "case_closed") return t("revisionCaseClosed");
    if (error.code === "case_state_conflict") return t("revisionCaseConflict");
    if (error.status === 404) return t("revisionUnavailable");
  }
  if (error instanceof SessionRevokedError || error instanceof SignInRequiredError) {
    return errorText(error);
  }
  // Keep the cause: the bare retry text hid it (digitva-owbz); errorText records it and adds the Ref line.
  return `${t("revisionRetry")}\n${errorText(error).split("\n").pop()}`;
}

