/** Error identities shared by native and browser clients without native auth imports. */
export class SessionRevokedError extends Error {
  /** True when unsent work kept the store: the account is read-only, not wiped. */
  readonly keptUnsent: boolean;

  constructor(keptUnsent = false) {
    super("session_revoked");
    this.name = "SessionRevokedError";
    this.keptUnsent = keptUnsent;
  }
}

/** The session must be re-established; native local interview data remains intact. */
export class SignInRequiredError extends Error {
  constructor() {
    super("sign_in_required");
    this.name = "SignInRequiredError";
  }
}

/**
 * Native only (docs/policy/public-demo.md section 10.1): the account is not served by the chosen slot's device
 * (it sits in the other slot, is gone, or is bound to another server), or the slot a sign-in started in is no
 * longer the chosen one. Nothing was sent. Background pollers skip it quietly; a screen shows errSlotChanged.
 */
export class NotInSlotError extends Error {
  constructor() {
    super("not_in_slot");
    this.name = "NotInSlotError";
  }
}

/** Native only: that slot already holds an enrolment; replacing it is re-enrolment (src/reEnrolConfirm.ts). */
export class AlreadyEnrolledError extends Error {
  constructor() {
    super("already_enrolled");
    this.name = "AlreadyEnrolledError";
  }
}

/** The same local store identity is retained in more than one server or mode. */
export class AccountStoreCollisionError extends Error {
  constructor() {
    super("account_store_collision");
    this.name = "AccountStoreCollisionError";
  }
}
