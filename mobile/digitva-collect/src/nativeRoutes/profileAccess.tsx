import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Text, View } from "react-native";

import { accessProfileDisplayText, loadAccessProfile, profileAccountAvailable, profileQuestionnaireLanguages, type LoadedAccessProfile } from "../accessProfile";
import { useAppState } from "../AppState";
import { useIcd11DorisPreference } from "../icd11DorisPreference";
import { isUnlocked } from "../interviewerDb";
import { useShell } from "../nativeShell/shellContext";
import { t } from "../i18n";
import { Button, Screen, useUiStyles } from "../ui";

/** Account-scoped display only: freshness never changes the server's authorization decisions. */
export default function ProfileAccess() {
  const styles = useUiStyles();
  const shell = useShell();
  const { accounts, slot = "active", lockVersion, uiLocale = "en" } = useAppState();
  const preference = useIcd11DorisPreference();
  const account = accounts.find((entry) => entry.user_id === shell.userId);
  const available = profileAccountAvailable(account) && isUnlocked(account.user_id);
  const [loaded, setLoaded] = useState<LoadedAccessProfile>();
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const userId = shell.userId;
  const server = account?.standalone ? undefined : shell.server;
  useFocusEffect(useCallback(() => {
    let active = true;
    setLoaded(undefined);
    setFailed(false);
    if (!available || !userId) return;
    void loadAccessProfile(userId, slot, server, shell.sync.offline).then((result) => {
      if (active) setLoaded(result);
    }).catch(() => {
      if (active) setFailed(true);
    });
    return () => { active = false; };
  }, [available, userId, slot, server, shell.sync.offline, lockVersion, attempt]));
  const visible = available && loaded && (loaded.kind === "standalone" ? account?.standalone && loaded.userId === userId && loaded.slot === slot :
    loaded.profile.slot === slot && loaded.profile.server === server && loaded.profile.userId === userId &&
      loaded.profile.accessDigest === account?.coding_history_access) ? loaded : undefined;

  return <Screen title={t("profileAccessTitle")}>
    {!available ? <Text accessibilityRole="alert" style={styles.error}>{t("profileAccessSignInRequired")}</Text> :
      !visible ? <>
        <Text style={styles.muted}>{failed || loaded ? t("profileAccessUnavailable") : t("profileAccessLoading")}</Text>
        {failed || loaded ? <Button kind="secondary" label={t("retry")} onPress={() => setAttempt((value) => value + 1)} /> : null}
      </> : visible.kind === "standalone" ? <>
        <Text accessibilityRole="header" style={styles.headline}>{visible.profile?.name ?? visible.name}</Text>
        <Text style={styles.text}>{t("profileMode")}: {t("profileStandalone")}</Text>
        <Text style={styles.text}>{t("profileServer")}: {t("profileDisabled")}</Text>
        {visible.profile ? <>
          <Text style={styles.text}>{t("profileDesignation")}: {visible.profile.designation || t("profileNotSaved")}</Text>
          <Text style={styles.text}>{t("profileFacility")}: {visible.profile.facility_name || t("profileNotSaved")}</Text>
          <Text style={styles.text}>{t("profileCountry")}: {visible.profile.country}</Text>
          <Text style={styles.text}>{t("profileState")}: {visible.profile.state || t("profileNotSaved")}</Text>
          <Text style={styles.text}>{t("profileUnitCode")}: {visible.profile.org_code || t("profileNotSaved")}</Text>
        </> : <Text style={styles.muted}>{t("profileOfflineNotSaved")}</Text>}
      </> : <>
        <Text accessibilityRole="header" style={styles.headline}>{visible.profile.name}</Text>
        <Text style={styles.text}>{t("profileMode")}: {slot === "demo" ? t("profileDemo") : t("profileServerEnrolled")}</Text>
        <Text style={styles.text} selectable>{t("profileServer")}: {visible.profile.server}</Text>
        <Text style={styles.muted}>{t(visible.current ? "profileCurrent" : "profileSavedOnPhone")} · {new Date(visible.profile.refreshedAt).toLocaleString(uiLocale)}</Text>
        <Text style={styles.text}>{t("profileRoles")}: {visible.profile.roles.map(accessProfileDisplayText).join(", ") || t("profileNone")}</Text>
        <Text style={styles.text}>{t("profileCodingLanguages")}: {visible.profile.codingLanguages.join(", ") || t("profileNotSupplied")}</Text>
        {!visible.profile.projects.length ? <Text style={styles.muted}>{t("profileNoProjectAccess")}</Text> : null}
        {visible.profile.projects.map((project) => {
          const languages = profileQuestionnaireLanguages(project.id, visible.reference);
          return <View key={project.id} style={styles.card}>
            <Text accessibilityRole="header" style={styles.headline}>{project.name}</Text>
            {project.rights.map((right, index) => <Text key={index} style={styles.text}>{accessProfileDisplayText(right)}</Text>)}
            <Text style={styles.text}>{t("profileIntake")}: {accessProfileDisplayText(project.intake)}</Text>
            <Text style={styles.text}>{t("profileCodingMode")}: {accessProfileDisplayText(project.codingMode)}</Text>
            <Text style={styles.text}>{t("profileClassification")}: {accessProfileDisplayText(project.classification)}</Text>
            <Text style={styles.text}>{t("profileCodingScope")}: {accessProfileDisplayText(project.codingScope)}</Text>
            <Text style={styles.text}>{t("profileProjectSelfCoding")}: {accessProfileDisplayText(project.selfCoding)}</Text>
            <Text style={styles.text}>{t("profileLocalCoding")}: {accessProfileDisplayText(project.localCoding)}</Text>
            <Text style={styles.text}>{languages ? `${t("profileQuestionnaireLanguages")}: ${accessProfileDisplayText(languages)}` : t("profileQuestionnaireLanguagesNotSaved")}</Text>
          </View>;
        })}
      </>}
    {visible ? <>
      <Text style={styles.text}>{t("profileDeviceCodingTools")}: {preference.ready ? preference.enabled ? t("profileOn") : t("profileOff") : t("profileLoading")}</Text>
      <Text style={styles.muted}>{t("profileDeviceSwitchNote")}</Text>
    </> : null}
  </Screen>;
}
