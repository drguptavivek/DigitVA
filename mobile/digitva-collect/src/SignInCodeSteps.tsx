/**
 * "I have a sign-in code" (docs/policy/mobile-sign-in.md section 3), shared by the welcome screen (src/nativeRoutes/
 * enrol.tsx) and the sign-in screen (src/nativeRoutes/sign-in.tsx): the code form, then "Code accepted" showing the
 * generated password once. The screens own the state, the identifier fields and what signing in with the password means.
 */
import { ErrorCode } from "./errorCodes";
import type { ReactNode } from "react";
import { Text, TextInput } from "react-native";

import { ApiError } from "./api";
import { t } from "./i18n";
import { formatSignInCode, looksLikeSignInCode } from "./nativeAuthLinks";
import { Button, Card, ListRow, monoFont, Notice, Screen, TextLink, ThemedSwitch, useUiStyles } from "./ui";
import { spacing } from "./theme";

/** A refused redemption's message; `fallback` maps everything but a wrong code and a server without the endpoint. */
export function signInCodeErrorText(caught: unknown, fallback: (caught: unknown) => string): string {
  if (caught instanceof ApiError && caught.code === ErrorCode.INVALID_CODE) return t("errSignInCodeInvalid");
  if (caught instanceof ApiError && caught.status === 404) return t("errSignInCodeUnsupported");
  return fallback(caught);
}

/** The code form: `identifierFields` above the code, then the terms, which the server requires (`accept_terms`). */
export function SignInCodeForm({ fromPassword, identifierFields, identifierReady, code, onCodeChange, acceptTerms,
  onAcceptTermsChange, busy, error, onSubmit, onCancel }: {
  /** Opened by a code typed into a Password box: says so instead of the intro. */
  fromPassword?: boolean;
  identifierFields: ReactNode;
  identifierReady: boolean;
  code: string;
  onCodeChange(code: string): void;
  acceptTerms: boolean;
  onAcceptTermsChange(accepted: boolean): void;
  busy: boolean;
  error: ReactNode;
  onSubmit(): void;
  onCancel(): void;
}) {
  const styles = useUiStyles();
  return (
    <Screen title={t("redeemCode")}>
      {fromPassword ? <Notice tone="info">{t("signInCodeFromPassword")}</Notice> : <Text style={styles.muted}>{t("signInCodeIntro")}</Text>}
      {identifierFields}
      <Text style={styles.muted}>{t("signInCodeLabel")}</Text>
      <TextInput accessibilityLabel={t("signInCodeLabel")} style={[styles.input, { fontFamily: monoFont }]} autoCapitalize="characters"
        autoCorrect={false} spellCheck={false} autoComplete="off" placeholder="XXXX-XXXX" editable={!busy} value={code}
        onChangeText={(value) => onCodeChange(formatSignInCode(value))} />
      <Text style={styles.muted}>{t("termsConfidential")} {t("termsNoSharing")} {t("termsPurpose")}</Text>
      <Card grouped>
        <ListRow label={t("acceptTerms")} trailing={
          <ThemedSwitch accessibilityLabel={t("acceptTerms")} value={acceptTerms} disabled={busy} onValueChange={onAcceptTermsChange} />
        } />
      </Card>
      <Button label={t("signInCodeSubmit")} loading={busy}
        disabled={busy || !identifierReady || !looksLikeSignInCode(code) || !acceptTerms}
        onPress={onSubmit} />
      {error}
      <TextLink label={t("cancel")} disabled={busy} onPress={onCancel} />
    </Screen>
  );
}

/** Code accepted: the generated password once; "I have saved it" signs in with it. */
export function CodeAccepted({ password, busy, error, onContinue, onCancel }: {
  password: string;
  busy: boolean;
  error: ReactNode;
  onContinue(): void;
  onCancel(): void;
}) {
  const styles = useUiStyles();
  return (
    <Screen title={t("enrolCodeAccepted")}>
      <Text style={styles.text}>{t("signInCodePasswordIntro")}</Text>
      <Card>
        <Text selectable style={[styles.headline, { fontFamily: monoFont, textAlign: "center", paddingVertical: spacing.sm }]}>
          {password}
        </Text>
      </Card>
      <Notice tone="warning">{t("signInCodePasswordKeep")}</Notice>
      <Button label={t("signInCodeSaved")} loading={busy} disabled={busy} onPress={onContinue} />
      {error}
      <TextLink label={t("cancel")} disabled={busy} onPress={onCancel} />
    </Screen>
  );
}
