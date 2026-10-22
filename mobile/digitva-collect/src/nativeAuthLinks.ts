import { acceptedServerOrigin } from "./enrolment";

export const NATIVE_AUTH_PATHS = {
  signIn: "/vaauth/valogin",
  redeemCode: "/vaauth/valogin/code",
  forgotPassword: "/vaauth/forgot-password"
} as const;

export type NativeAuthPath = (typeof NATIVE_AUTH_PATHS)[keyof typeof NATIVE_AUTH_PATHS];

/**
 * Build a server handoff URL only for a server the enrolment rule accepts
 * (src/enrolment.ts acceptedServerOrigin).
 * No credentials, tokens, or account identifiers are placed in the URL.
 */
export function nativeAuthUrl(server: string, path: NativeAuthPath, isDev: boolean): string {
  const origin = acceptedServerOrigin(server, isDev);
  if (!origin) throw new Error("server_not_allowed");
  return `${origin}${path}`;
}

/**
 * Turn the India UI's optional +91/91/0 prefix into its ten-digit display value.
 * Values with an unexpected length remain invalid and are rejected on submit;
 * this function does not silently discard digits from a malformed paste.
 */
export function mobileDigitsFromInput(value: string): string {
  const digits = value.replace(/\D/g, "");
  if (digits.length === 12 && digits.startsWith("91")) return digits.slice(2);
  if (digits.length === 11 && digits.startsWith("0")) return digits.slice(1);
  return digits;
}

/** Return the existing device API identifier form, or undefined for invalid input. */
export function normalizeMobileIdentifier(value: string): string | undefined {
  const digits = mobileDigitsFromInput(value);
  return /^[6-9]\d{9}$/.test(digits) ? `+91${digits}` : undefined;
}
