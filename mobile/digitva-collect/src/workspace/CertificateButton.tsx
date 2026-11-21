import { useState } from "react";
import { Platform, Text } from "react-native";

import { ApiError } from "../api";
import { t } from "../i18n";
import { Button, errorText, useUiStyles } from "../ui";
import type { WorkspaceApi } from "./api";
import { certificateHtml } from "./certificate";
import { sharePdf } from "./certificatePdf";
import type { WorkspacePayload } from "./contracts";

/**
 * "COD form (PDF)", only when the server says the case is coded in an organization project
 * (`case.certificate_available`; the server re-checks). Web: opens the printable page
 * (`/coding/area/<sid>/certificate`) in a new tab. Native: fetches the certificate data, prints it to a PDF
 * on the phone and shares it, so it needs a connection; offline cases carry no `certificate_available`.
 */
export function CertificateButton({ workspace, api }: { workspace: WorkspacePayload; api?: WorkspaceApi }) {
  const styles = useUiStyles();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  if (!workspace.case.certificate_available) return null;
  const vaSid = workspace.case.va_sid;
  if (Platform.OS === "web") {
    return (
      <Button
        label={t("certificateButton")}
        accessibilityLabel={t("certificateButton")}
        onPress={() => window.open(`/coding/area/${encodeURIComponent(vaSid)}/certificate`, "_blank", "noopener")}
      />
    );
  }
  if (!api?.getCertificate) return null;
  const getCertificate = api.getCertificate.bind(api);
  async function share() {
    setBusy(true);
    setMessage("");
    try {
      const certificate = await getCertificate(vaSid);
      await sharePdf(certificateHtml(certificate), `COD-form-${certificate.case_id ?? vaSid}`);
    } catch (error) {
      // A non-HTTP failure is the network: the certificate is built from server data, so it needs a connection.
      setMessage(!(error instanceof ApiError) ? t("certificateConnect") : error.status === 404 ? t("certificateUnavailable") : errorText(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Button label={t("certificateButton")} accessibilityLabel={t("certificateButton")} disabled={busy} onPress={share} />
      {message ? <Text style={styles.muted} accessibilityRole="alert">{message}</Text> : null}
    </>
  );
}
