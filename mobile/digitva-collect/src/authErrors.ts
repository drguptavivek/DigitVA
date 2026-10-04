/** Error identities shared by native and browser clients without native auth imports. */
export class SessionRevokedError extends Error {
  constructor() {
    super("session_revoked");
    this.name = "SessionRevokedError";
  }
}

/** The session must be re-established; native local interview data remains intact. */
export class SignInRequiredError extends Error {
  constructor() {
    super("sign_in_required");
    this.name = "SignInRequiredError";
  }
}
