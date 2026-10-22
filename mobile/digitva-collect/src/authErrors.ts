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
