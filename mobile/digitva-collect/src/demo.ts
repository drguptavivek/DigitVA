/**
 * "Try the demo" (docs/policy/public-demo.md sections 2 and 10): sign-up with
 * proof of work, enrolment without a QR code, and the sign-in that follows,
 * all against the compiled demo origin (src/enrolment.ts DEMO_SERVER). The
 * checks here mirror the server's so the user is told early; the server stays
 * authoritative (app/services/user_account_service.py `clean_username`,
 * app/services/public_demo_service.py `_check_password`).
 */
import { ErrorCode } from "./errorCodes";
import Constants from "expo-constants";

import { ApiError, AUTH_API, requestJson } from "./api";
import { APP_VERSION } from "./appVersion";
import { enrolDemoDevice, loadDevice, signIn, type Account } from "./auth";
import { demoServerOrigin } from "./enrolment";
import { normalizeUsername } from "./demoRules";
import { t } from "./i18n";
import { deviceFamilyLabel } from "./platformFamily";
import { solveChallenge } from "./pow";
import { errorText } from "./ui";

/** The origin the demo flow talks to in this build. */
export const demoServer = () => demoServerOrigin(__DEV__, process.env.EXPO_PUBLIC_DEMO_SERVER);

/**
 * What the demo screen says about a refused call. The two limit refusals are
 * final for that action: nothing here (or anywhere in the app) retries them on
 * its own, the user decides. Anything else falls back to the shared mapping.
 */
export function demoErrorText(error: unknown): string {
  if (error instanceof ApiError) {
    const code = error.code;
    if (code === ErrorCode.DEMO_LIMIT) return t("demoLimit");
    if (error.status === 429) return t("demoRateLimited");
    if (code === ErrorCode.CAP_REACHED) return t("demoFull");
    if (code === ErrorCode.CAPTCHA_FAILED) return t("demoCaptchaFailed");
    if (code === ErrorCode.INVALID_USERNAME) return t("demoErrUsernameRule");
    if (code === ErrorCode.USERNAME_TAKEN) return t("demoErrUsernameTaken");
    if (code === ErrorCode.INVALID_PASSWORD) return t("demoErrPasswordShort");
    if (code === ErrorCode.BREACHED_PASSWORD) return t("demoErrBreached");
    if (code === ErrorCode.BREACH_CHECK_UNAVAILABLE) return t("demoErrBreachUnavailable");
    if (code === ErrorCode.INVALID_CREDENTIALS) return t("demoErrCredentials");
    if (code === ErrorCode.WRONG_DATABASE || code === ErrorCode.PROJECT_MISSING || error.status === 404) return t("demoNotAvailable");
  }
  return errorText(error);
}

interface Challenge {
  salt: string;
  difficulty: number;
  expires: number;
  signature: string;
}

const isChallenge = (value: unknown): value is Challenge =>
  !!value && typeof value === "object" &&
  typeof (value as Challenge).salt === "string" && Number.isInteger((value as Challenge).difficulty) &&
  Number.isInteger((value as Challenge).expires) && typeof (value as Challenge).signature === "string";

export interface DemoProgress {
  stage: "challenge" | "solving" | "signup" | "enrol" | "signin";
  /** 0 to 1 while solving. */
  fraction?: number;
}

/**
 * Create a demo account: a fresh challenge, solved here, then POST /demo-signup.
 * Every call fetches its own challenge (a spent or failed one is never reused),
 * so a `captcha_failed` is retried by the user pressing the button again.
 */
export async function signUpDemoAccount(
  username: string,
  password: string,
  options: { onProgress?: (progress: DemoProgress) => void; signal?: { aborted: boolean } } = {},
): Promise<void> {
  const server = demoServer();
  options.onProgress?.({ stage: "challenge" });
  const { body: challenge } = await requestJson<unknown>(server, `${AUTH_API}/demo-signup/challenge`);
  if (!isChallenge(challenge)) throw new ApiError(200, "malformed_response");
  options.onProgress?.({ stage: "solving", fraction: 0 });
  const solution = await solveChallenge(challenge.salt, challenge.difficulty, {
    signal: options.signal,
    onProgress: (done, expected) =>
      options.onProgress?.({ stage: "solving", fraction: Math.min(1, done / expected) }),
  });
  options.onProgress?.({ stage: "signup" });
  await requestJson(server, `${AUTH_API}/demo-signup`, {
    method: "POST",
    body: { username: normalizeUsername(username), password, captcha: { ...challenge, solution } },
  });
}

/**
 * Enrol this phone on the demo server and sign the demo account in (the normal POST /sessions).
 * `replaceDeviceId` retries a `409 device_limit` with the phone chosen to sign out. When that 409 came from
 * the sign-in, the device is already enrolled, so the retry skips enrolment.
 */
export async function enrolAndSignInDemo(
  username: string,
  password: string,
  onProgress?: (progress: DemoProgress) => void,
  replaceDeviceId?: string,
): Promise<Account> {
  const name = normalizeUsername(username);
  if (!(replaceDeviceId && (await loadDevice("demo")))) {
    onProgress?.({ stage: "enrol" });
    await enrolDemoDevice(demoServer(), name, password, Constants.deviceName ?? deviceFamilyLabel(), APP_VERSION, replaceDeviceId);
  }
  onProgress?.({ stage: "signin" });
  // Pinned to Demo: a switch while this ran keeps neither the account nor its tokens.
  return signIn(name, password, "demo", { replaceDeviceId });
}

