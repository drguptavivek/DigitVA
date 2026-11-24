import { ApiError } from "./api";
import { SessionRevokedError, SignInRequiredError } from "./auth";
import { FormDefinitionError } from "./formDefinitions";
import { PinnedDefinitionError } from "./formDefinitionRuntime";
import { revisionOpenKey, revisionRefusalKey } from "./errorMessages";
import { t } from "./i18n";
import { errorText } from "./ui";

/** User-facing text for a revision in the attention state, and for a failed revision open. */
export function attentionMessage(code: string | null): string {
  if (code === "invalid_definition_pin") return t("revisionPinInvalid");
  // answers_hash_invalid, local_hash_mismatch, invalid_revision_snapshot, invalid_revision_ack and any unknown code retry.
  return t(revisionRefusalKey(code) ?? "revisionRetry");
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
    const key = revisionOpenKey(error.code, error.status);
    if (key) return t(key);
  }
  if (error instanceof SessionRevokedError || error instanceof SignInRequiredError) {
    return errorText(error);
  }
  // Keep the cause: the bare retry text hid it (digitva-owbz); errorText records it and adds the Ref line.
  return `${t("revisionRetry")}\n${errorText(error).split("\n").pop()}`;
}

