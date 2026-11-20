import { Platform } from "react-native";

import { t } from "../i18n";
import { Button } from "../ui";
import type { WorkspacePayload } from "./contracts";

/**
 * "Certificate (PDF)": opens the server's printable cause-of-death certificate
 * (`/coding/area/<sid>/certificate`) in a new tab. Web only (the native app has
 * no web pages) and only when the server says the case is coded in an
 * organization project (`case.certificate_available`); the page re-checks.
 */
export function CertificateButton({ workspace }: { workspace: WorkspacePayload }) {
  if (Platform.OS !== "web" || !workspace.case.certificate_available) return null;
  return (
    <Button
      label={t("certificateButton")}
      accessibilityLabel={t("certificateButton")}
      onPress={() => window.open(`/coding/area/${encodeURIComponent(workspace.case.va_sid)}/certificate`, "_blank", "noopener")}
    />
  );
}
