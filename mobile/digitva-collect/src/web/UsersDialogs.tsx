import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Image, Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { ApiError } from "../api";
import { t, type StringKey } from "../i18n";
import { controls, radius, spacing, typography, useTheme } from "../theme";
import { Button, useUiStyles } from "../ui";
import {
  getSignInQrs, getUserStatus, issueSignInQr, revokeSignInQr,
  type DirectoryUser, type SignInQrItem, type SignInQrShown, type UserStatus,
} from "../users/api";
import type { JsonRequester } from "../workspace/api";
import { browserErrorText } from "./common";
import { formatWhen } from "../ui/interviewRows";

/**
 * The Users page dialogs (digitva-9npt): the Status popup (GET /users/<id>/status, never a secret or a code) and the
 * sign-in QR dialog (docs/policy/mobile-sign-in.md section 8: email or show once, revoke the pending one).
 * RN-web's Modal traps focus and closes on Escape through onRequestClose.
 */

const QR_VALID_SECONDS = 6 * 3600;

function useDialogStyles() {
  const { colors } = useTheme();
  return useMemo(() => StyleSheet.create({
    backdrop: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.sm, backgroundColor: "rgba(0,0,0,0.5)" },
    dialog: { width: "100%", maxWidth: 560, maxHeight: "92%", borderRadius: radius.lg, backgroundColor: colors.surface },
    body: { gap: spacing.sm, padding: spacing.md },
    section: { gap: spacing.xxs, paddingTop: spacing.xs, borderTopWidth: 1, borderColor: colors.border },
    sectionTitle: { ...typography.caption, fontWeight: "700", color: colors.textMuted, fontFamily: controls.fontFamily, textTransform: "uppercase" },
    qr: { width: 240, height: 240, alignSelf: "center" },
    code: { ...typography.subhead, color: colors.text, fontFamily: controls.fontFamily, textAlign: "center" },
    warn: { ...typography.subhead, fontWeight: "600", color: colors.danger, fontFamily: controls.fontFamily },
    actions: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
  }), [colors]);
}

/** A centred dialog: backdrop press, Escape and the Close button all call onClose. */
export function DialogFrame({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const styles = useUiStyles();
  const s = useDialogStyles();
  return (
    <Modal visible transparent animationType="fade" onRequestClose={onClose}>
      <View style={s.backdrop}>
        <Pressable accessibilityRole="button" accessibilityLabel={t("usersCodeClose")} onPress={onClose} style={StyleSheet.absoluteFill} />
        <View style={s.dialog} accessibilityViewIsModal accessibilityLabel={title} role="dialog" aria-modal={true}>
          <ScrollView contentContainerStyle={s.body} keyboardShouldPersistTaps="handled">
            <Text style={styles.headline} accessibilityRole="header">{title}</Text>
            {children}
            <Button kind="secondary" label={t("usersCodeClose")} onPress={onClose} />
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const when = (value: string | null | undefined) => (value ? formatWhen(value) : t("usersStNever"));

function Section({ title, children }: { title: string; children: ReactNode }) {
  const s = useDialogStyles();
  return (
    <View style={s.section}>
      <Text style={s.sectionTitle} accessibilityRole="header">{title}</Text>
      {children}
    </View>
  );
}

const CODE_STATUS: Record<string, StringKey> = {
  valid: "usersStCodeValid", used: "usersStCodeUsed", expired: "usersStCodeExpired", revoked: "usersStCodeRevoked", unknown: "usersStCodeUnknown",
};
const QR_STATUS: Record<string, StringKey> = {
  pending: "usersQrPending", expired: "usersQrExpired", redeemed: "usersQrRedeemed", revoked: "usersQrRevokedStatus",
};
const MOBILE_STATUS: Record<string, StringKey> = { enrolled: "usersEnrolled", revoked: "usersEnrolRevoked", none: "usersEnrolNone" };

export function StatusDialog({ request, user, onClose }: { request: JsonRequester; user: Pick<DirectoryUser, "user_id" | "name">; onClose: () => void }) {
  const styles = useUiStyles();
  const [status, setStatus] = useState<UserStatus>();
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    getUserStatus(request, user.user_id)
      .then((body) => { if (active) setStatus(body); })
      .catch((caught) => { if (active) setError(browserErrorText(caught)); });
    return () => { active = false; };
  }, [request, user.user_id]);

  return (
    <DialogFrame title={t("usersStatusTitle", { name: user.name })} onClose={onClose}>
      {error ? <Text style={styles.error} accessibilityRole="alert">{error}</Text> : null}
      {!status && !error ? <Text style={styles.muted}>{t("loading")}</Text> : null}
      {status ? (
        <View testID="user-status" style={{ gap: spacing.xs }}>
          <Section title={t("usersFilterStatus")}>
            <Text style={styles.text}>{status.active ? t("usersStAccountActive") : t("usersStAccountInactive")}</Text>
            <Text style={styles.muted}>{status.created_at ? t("usersStCreated", { when: when(status.created_at) }) : t("usersStCreatedUnknown")}</Text>
            <Text style={styles.text}>
              {status.terms_accepted
                ? (status.terms_accepted_at ? t("usersStTermsAcceptedAt", { when: when(status.terms_accepted_at) }) : t("usersStTermsAccepted"))
                : t("usersStTermsNot")}
            </Text>
          </Section>
          <Section title={t("usersFilterEmailVerified")}>
            <Text style={styles.text}>
              {status.email_verified
                ? (status.email_verified_at ? t("usersStEmailVerifiedAt", { when: when(status.email_verified_at) }) : t("usersStEmailVerified"))
                : t("usersStEmailNotVerified")}
            </Text>
            {status.verification_email_sent_at ? <Text style={styles.muted}>{t("usersStVerificationSent", { when: when(status.verification_email_sent_at) })}</Text> : null}
          </Section>
          <Section title={t("usersFilterPasswordSet")}>
            <Text style={styles.text}>{status.password_set ? t("usersStPasswordSet") : t("usersStPasswordNotSet")}</Text>
            <Text style={styles.muted}>
              {status.password_emailed_at ? t("usersStPasswordEmailed", { when: when(status.password_emailed_at) }) : t("usersStNoPasswordEmail")}
            </Text>
          </Section>
          <Section title={t("usersStPasskeys")}>
            {status.passkeys.count ? (
              <Text style={styles.text}>
                {`${t("usersStPasskeyCount", { count: status.passkeys.count })} · ${t("usersStPasskeyLast", { when: when(status.passkeys.last_used_at) })}`}
              </Text>
            ) : <Text style={styles.muted}>{t("usersStPasskeyNone")}</Text>}
          </Section>
          <Section title={t("usersStCodes")}>
            {status.enrolment_codes.length ? status.enrolment_codes.map((code, index) => (
              <Text key={index} style={styles.text} testID="status-code-row">
                {t("usersStCodeRow", {
                  status: t(CODE_STATUS[code.status] ?? "usersStCodeUnknown"),
                  generated: when(code.generated_at),
                  project: code.project_id ?? "-",
                  expires: when(code.expires_at),
                })}
              </Text>
            )) : <Text style={styles.muted}>{t("usersStCodesNone")}</Text>}
          </Section>
          <Section title={t("usersStMobile")}>
            <Text style={styles.text}>
              {t("usersStMobileLine", {
                status: t(MOBILE_STATUS[status.mobile.status] ?? "usersEnrolNone"),
                devices: status.mobile.devices,
                revoked: status.mobile.revoked_devices,
              })}
            </Text>
            {status.mobile.last_seen_at ? <Text style={styles.muted}>{t("usersLastSeen", { when: when(status.mobile.last_seen_at) })}</Text> : null}
          </Section>
          <Section title={t("usersStQrs")}>
            {status.sign_in_qrs.length ? status.sign_in_qrs.map((qr, index) => (
              <Text key={index} style={styles.text} testID="status-qr-row">
                {t("usersStQrRow", { status: t(QR_STATUS[qr.status] ?? "usersQrExpired"), issued: when(qr.issued_at), expires: when(qr.expires_at) })}
                {qr.redeemed_at ? t("usersStQrRedeemed", { when: when(qr.redeemed_at) }) : ""}
              </Text>
            )) : <Text style={styles.muted}>{t("usersStQrNone")}</Text>}
          </Section>
          <Section title={t("usersStTraining")}>
            {status.training.length ? status.training.map((row, index) => (
              <Text key={index} style={styles.text}>
                {t("usersStTrainingRow", {
                  session: row.session_name ?? row.session_code,
                  status: row.session_status ?? "-",
                  role: row.role ?? "-",
                  slot: row.coder_slot ?? "-",
                  onboarded: row.onboarded ? t("usersStOnboarded", { when: when(row.onboarded_at) }) : t("usersStNotOnboarded"),
                })}
              </Text>
            )) : <Text style={styles.muted}>{t("usersStTrainingNone")}</Text>}
          </Section>
        </View>
      ) : null}
    </DialogFrame>
  );
}

/** "H:MM:SS" left until *expiresAt*, ticking each second; 0 once past. */
function useSecondsLeft(expiresAt: string | undefined): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!expiresAt) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [expiresAt]);
  if (!expiresAt) return 0;
  const end = Date.parse(expiresAt);
  return Number.isNaN(end) ? QR_VALID_SECONDS : Math.max(0, Math.floor((end - now) / 1000));
}

export function formatCountdown(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const sec = seconds % 60;
  return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

const QR_ERRORS: Record<string, StringKey> = {
  not_eligible: "usersQrErrNotEligible",
  no_verified_email: "usersQrErrNoVerified",
  email_failed: "usersQrErrEmailFailed",
  not_found: "usersQrErrNotFound",
};

function qrErrorText(caught: unknown): string {
  const key = caught instanceof ApiError && caught.code ? QR_ERRORS[caught.code] : undefined;
  return key ? t(key) : browserErrorText(caught);
}

/** The code and QR live only in this component's state: Close (or expiry) unmounts or clears them. */
export function SignInQrDialog({ request, user, onClose }: { request: JsonRequester; user: DirectoryUser; onClose: () => void }) {
  const styles = useUiStyles();
  const s = useDialogStyles();
  const [verified, setVerified] = useState<boolean>();
  const [pending, setPending] = useState<SignInQrItem>();
  const [shown, setShown] = useState<SignInQrShown>();
  const [emailedUntil, setEmailedUntil] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [expired, setExpired] = useState(false);
  const left = useSecondsLeft(shown?.expires_at);

  useEffect(() => {
    let active = true;
    getUserStatus(request, user.user_id).then((body) => { if (active) setVerified(body.email_verified); }).catch(() => undefined);
    getSignInQrs(request, user.user_id)
      .then((items) => { if (active) setPending(items.find((item) => item.status === "pending")); })
      .catch((caught) => {
        if (!active) return;
        setError(qrErrorText(caught));
        if (caught instanceof ApiError && (caught.code === "not_found" || caught.status === 404)) setBlocked(true);
      });
    return () => { active = false; };
  }, [request, user.user_id]);

  // A code past its expiry is cleared from memory at once.
  useEffect(() => {
    if (shown && left === 0) {
      setShown(undefined);
      setExpired(true);
    }
  }, [shown, left]);

  async function issue(delivery: "show" | "email") {
    setBusy(true);
    setError("");
    setNote("");
    setExpired(false);
    try {
      const result = await issueSignInQr(request, user.user_id, delivery);
      setPending(undefined);
      if (delivery === "show") setShown(result);
      else setEmailedUntil(result.expires_at);
    } catch (caught) {
      setError(qrErrorText(caught));
    } finally {
      setBusy(false);
    }
  }

  async function revoke() {
    setBusy(true);
    setError("");
    try {
      const revoked = await revokeSignInQr(request, user.user_id);
      setPending(undefined);
      setNote(revoked ? t("usersQrRevoked") : t("usersQrNothingToRevoke"));
    } catch (caught) {
      setError(qrErrorText(caught));
    } finally {
      setBusy(false);
    }
  }

  const close = () => {
    setShown(undefined);
    onClose();
  };
  const noEmail = !user.email;
  const emailBlocked = noEmail || verified === false;

  return (
    <DialogFrame title={t("usersQrTitle", { name: user.name })} onClose={close}>
      {shown ? (
        <View style={{ gap: spacing.xs }} testID="sign-in-qr-shown">
          <Image style={s.qr} accessibilityLabel={t("usersQrImage")} source={{ uri: `data:image/png;base64,${shown.qr_png}` }} />
          <Text style={s.code} selectable>{shown.code}</Text>
          <Text style={styles.text}>{t("usersQrValid", { time: formatCountdown(left) })}</Text>
          <Text style={s.warn} accessibilityRole="alert">{t("usersQrWarn")}</Text>
        </View>
      ) : emailedUntil ? (
        <Text style={styles.text}>{t("usersQrEmailed", { when: when(emailedUntil) })}</Text>
      ) : (
        <>
          <Text style={styles.text}>{t("usersQrIntro")}</Text>
          {pending ? <Text style={styles.muted}>{t("usersQrPendingNote", { when: when(pending.expires_at) })}</Text> : null}
          {emailBlocked && !blocked ? <Text style={styles.muted}>{noEmail ? t("usersQrNoEmail") : t("usersQrNeedVerified")}</Text> : null}
          {!blocked ? (
            <View style={s.actions}>
              <Button label={t("usersQrShow")} loading={busy} onPress={() => void issue("show")} />
              <Button kind="secondary" label={t("usersQrEmail")} disabled={busy || emailBlocked} onPress={() => void issue("email")} />
              {pending ? <Button kind="danger" label={t("usersQrRevoke")} disabled={busy} onPress={() => void revoke()} /> : null}
            </View>
          ) : null}
        </>
      )}
      {expired ? <Text style={styles.muted}>{t("usersQrExpiredNow")}</Text> : null}
      {note ? <Text style={styles.text} accessibilityRole="alert">{note}</Text> : null}
      {error ? <Text style={styles.error} accessibilityRole="alert">{error}</Text> : null}
    </DialogFrame>
  );
}
