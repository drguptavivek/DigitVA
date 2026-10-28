import { useState } from "react";
import { Linking, Text, View } from "react-native";

import { t } from "../i18n";
import { DIGITVA_MIT_NOTICE, formatThirdPartyNotices, SMARTVA_MIT_NOTICE, WHO_VA_NOTICE, type ThirdPartyNoticeBundle } from "../openSourceLicenses";
import { Button, Screen, useUiStyles } from "../ui";

export const WHO_ICD11_SOFTWARE_TERMS_URL = "https://icd.who.int/en/docs/icd11-license.pdf";
export const WHO_ICD11_CONTENT_LICENSE_URL = "https://creativecommons.org/licenses/by-nd/3.0/igo/";

export default function OpenSourceLicenses() {
  const styles = useUiStyles();
  const [linkError, setLinkError] = useState("");
  const [showThirdParty, setShowThirdParty] = useState(false);
  const [thirdPartyText, setThirdPartyText] = useState("");

  async function openExternalTerms(url: string) {
    setLinkError("");
    try {
      await Linking.openURL(url);
    } catch {
      setLinkError(t("licenseOpenTermsError"));
    }
  }

  function toggleThirdPartyNotices() {
    if (!showThirdParty && !thirdPartyText) {
      const generated = require("../../assets/third-party-notices.json") as ThirdPartyNoticeBundle;
      setThirdPartyText(formatThirdPartyNotices(generated));
    }
    setShowThirdParty((visible) => !visible);
  }

  return (
    <Screen title={t("openSourceLicensesTitle")}>
      <Text accessibilityRole="header" style={styles.headline}>DigitVA</Text>
      <Text style={styles.muted}>MIT License</Text>
      <Text selectable style={styles.text}>{DIGITVA_MIT_NOTICE}</Text>

      <Text accessibilityRole="header" style={styles.headline}>SmartVA Analyze</Text>
      <Text style={styles.muted}>MIT License · Copyright 2018 University of Washington</Text>
      <Text style={styles.muted}>{t("licenseSmartVaDescription")}</Text>
      <Text selectable style={styles.text}>{SMARTVA_MIT_NOTICE}</Text>

      <Text accessibilityRole="header" style={styles.headline}>{t("licenseWhoVaTitle")}</Text>
      <Text selectable style={styles.text}>{WHO_VA_NOTICE}</Text>

      <Text accessibilityRole="header" style={styles.headline}>{t("licenseWhoIcd11Title")}</Text>
      <Text style={styles.text}>{t("icd11Citation")}</Text>
      <Text style={styles.muted}>
        {t("licenseWhoIcd11TermsNote")}
      </Text>
      <Button kind="secondary" label={t("licenseViewContentTerms")} onPress={() => void openExternalTerms(WHO_ICD11_CONTENT_LICENSE_URL)} />
      <Button kind="secondary" label={t("licenseViewSoftwareTerms")} onPress={() => void openExternalTerms(WHO_ICD11_SOFTWARE_TERMS_URL)} />
      <Text accessibilityRole="header" style={styles.headline}>{t("licenseThirdPartyNotices")}</Text>
      <Text style={styles.muted}>{t("licenseThirdPartyScope")}</Text>
      <Button
        kind="secondary"
        label={t(showThirdParty ? "licenseThirdPartyHide" : "licenseThirdPartyNotices")}
        expanded={showThirdParty}
        onPress={toggleThirdPartyNotices}
      />
      {showThirdParty ? <Text selectable style={styles.text}>{thirdPartyText}</Text> : null}
      {linkError ? <Text accessibilityRole="alert" style={styles.error}>{linkError}</Text> : null}
    </Screen>
  );
}
