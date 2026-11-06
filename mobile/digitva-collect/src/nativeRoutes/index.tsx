/**
 * Profiles on this phone: one grouped card with a row per profile (display name, lock state, and for an unlocked
 * standalone profile the amber count of records it has not sent), then Add profile and a Settings link.
 */
import { Redirect, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Platform, Text, View } from "react-native";

import { useAppState } from "../AppState";
import type { Account } from "../auth";
import { t } from "../i18n";
import { homeRoute } from "../standalone/home";
import { standaloneCounts } from "../standalone/adopt";
import { isUnlocked, openInterviewerDb } from "../interviewerDb";
import DemoPanel from "../DemoPanel";
import { displayProjectName } from "../projectName";
import { spacing } from "../theme";
import { Button, Card, ListRow, Screen, Separator, TextLink, useUiStyles } from "../ui";
import { WorkspaceScreen } from "../browserScreens";

/**
 * Completed standalone interviews not yet sent, read only while the profile is unlocked (a locked store cannot be
 * read); undefined otherwise. Codings are not counted: they go with their interviews.
 */
function useStandaloneUnsent(account: Account, enrolled: boolean): number | undefined {
  const [count, setCount] = useState<number>();
  const readable = enrolled && account.standalone === true && isUnlocked(account.user_id);
  useEffect(() => {
    let active = true;
    setCount(undefined);
    if (readable) {
      void openInterviewerDb(account.user_id)
        .then((db) => standaloneCounts(db, ""))
        .then((counts) => { if (active) setCount(counts.interviews); })
        .catch(() => undefined);
    }
    return () => { active = false; };
  }, [account.user_id, readable]);
  return count;
}

/** One profile: name, then its state (or why it needs attention); the row opens it. */
function ProfileRow({ account, enrolled }: { account: Account; enrolled: boolean }) {
  const router = useRouter();
  const unsent = useStandaloneUnsent(account, enrolled);
  const unlocked = isUnlocked(account.user_id);
  const state = account.signed_out ? t("signedOutKept")
    : account.access_removed ? t("accessRemovedKept")
    : account.needs_sign_in ? t("signInAgain")
    : unlocked ? t("unlockedState") : t("locked");
  return (
    <ListRow
      emphasis
      label={account.name}
      secondary={state}
      secondaryTone={account.access_removed && !account.signed_out ? "destructive" : undefined}
      value={unsent ? t("syncUnsentScoped", { count: unsent }) : undefined}
      badge
      chevron
      // A signed-out profile signs in (password), then its PIN opens the kept data.
      onPress={() => router.push({ pathname: account.signed_out ? "/sign-in" : unlocked ? homeRoute(account) : "/unlock", params: { userId: account.user_id } })}
      // Sign-in keeps this account's store; sign-out would wipe it.
      trailing={account.needs_sign_in && !account.signed_out ? (
        <TextLink label={t("signInAgainAction")} onPress={() => router.push({ pathname: "/sign-in", params: { userId: account.user_id } })} />
      ) : undefined}
    />
  );
}

export default function Home() {
  const styles = useUiStyles();
  if (Platform.OS === "web") return <WorkspaceScreen />;
  const router = useRouter();
  // The context value changes on every lock and unlock, so this re-renders.
  const { ready, device, accounts, slot, switchSlot } = useAppState();
  // An empty Demo slot is never offered QR enrolment (that fills Active): it hands the phone back to Active.
  const emptyDemo = ready && slot === "demo" && !device;
  useEffect(() => {
    if (emptyDemo) void switchSlot?.("active");
  }, [emptyDemo, switchSlot]);
  if (!ready || emptyDemo) return <ActivityIndicator style={{ flex: 1 }} />;
  const standaloneAccount = accounts.find((account) => account.standalone);
  const standalone = standaloneAccount !== undefined;
  if (!device && !standalone) return <Redirect href="/enrol" />;
  // "GUJ026 · Gujarat Health System": the 15pt sub-line other screens use under their title.
  const projectLine = device ? [device.project_id, displayProjectName(device.project_name)].filter(Boolean).join(" · ") : "";
  return (
    // The emblem and name sit in the top bar (design sheet 01), so the profiles start above the fold.
    <Screen title={t("accountsTitle")}>
      {projectLine ? <Text style={styles.muted}>{projectLine}</Text> : null}
      {device ? <DemoPanel server={device.server} /> : null}
      {accounts.length === 0 ? <Text style={styles.text}>{t("accountsEmpty")}</Text> : (
        <Card grouped>
          {accounts.map((account, index) => (
            <View key={account.user_id}>
              {index ? <Separator /> : null}
              <ProfileRow account={account} enrolled={Boolean(device)} />
            </View>
          ))}
        </Card>
      )}
      <View style={{ gap: spacing.xs }}>
        {device ? <Button label={t("addInterviewer")} onPress={() => router.push("/sign-in")} /> : <Button label={t("standaloneEnrol")} onPress={() => router.push("/enrol")} />}
        <TextLink label={t("settings")} onPress={() => router.push(
          standaloneAccount && !device
            ? { pathname: "/settings", params: { userId: standaloneAccount.user_id } }
            : "/settings",
        )} />
      </View>
    </Screen>
  );
}
