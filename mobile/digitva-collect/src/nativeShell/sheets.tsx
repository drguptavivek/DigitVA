/** The three shell sheets: Account menu, Help and Sync. Open state lives in the ShellProvider (shell.tsx). */
import { usePathname, useRouter } from "expo-router";
import { useState } from "react";
import { Linking, Pressable, Text, TextInput, View } from "react-native";

import { useAppState } from "../AppState";
import { signOut } from "../auth";
import { t, UI_LOCALES } from "../i18n";
import { isUnlocked } from "../interviewerDb";
import { confirmSignOut } from "../signOutConfirm";
import { radius, spacing, typography, useTheme } from "../theme";
import { useToast } from "../toast";
import { APP_VERSION } from "../appVersion";
import { Button } from "../ui";
import { RoleChip, RoleChips } from "../ui/RoleChip";
import { BottomSheet, SheetRow } from "./BottomSheet";
import { faqEntries, type FaqTarget } from "./faq";
import { helpContent, helpGuideUrl, helpScreenFor } from "./helpContent";
import { clock, useShell, type SyncStatus } from "./shellContext";

/** "Synced 14:05 · 3 unsent" (parts that are not known yet are left out). */
export function syncSummary(sync: SyncStatus): string {
  const parts = [sync.lastAt ? t("syncChipSynced", { time: clock(sync.lastAt) }) : t("syncChipNever")];
  if (sync.work) parts.push(t("syncUnsentCount", { count: sync.work.unsent }));
  return parts.join(" · ");
}

/** The account's phone roles as chips, then the project name. */
function RoleLine({ account, project }: { account: { collection_access?: boolean; registration_access?: boolean }; project?: string }) {
  const { ui } = useTheme();
  const roles = [account.collection_access ? "interviewer" : "", account.registration_access ? "death_reporter" : ""].filter(Boolean);
  return (
    <RoleChips>
      {roles.map((role) => <RoleChip key={role} role={role} />)}
      {project ? <Text style={{ ...typography.subhead, color: ui.mutedForeground }}>{project}</Text> : null}
    </RoleChips>
  );
}

export function AccountSheet() {
  const shell = useShell();
  const router = useRouter();
  const { accounts, device, uiLocale, chooseUiLocale, lockNow, reload } = useAppState();
  const { ui } = useTheme();
  const toast = useToast();
  const lockFailed = () => toast.show({ kind: "error", text: t("errGeneric") });
  const account = accounts.find((item) => item.user_id === shell.userId);
  const userId = account?.user_id;
  const go = (action: () => void) => () => {
    shell.closeSheet();
    action();
  };
  async function doSignOut() {
    if (!userId) return;
    try {
      // Save open work and close every store first: sign-out keeps the data.
      if (!(await lockNow())) {
        lockFailed();
        return;
      }
      await signOut(userId);
      await reload();
      router.replace("/");
    } catch {
      // The sign-out confirmation already told the worker; a failure leaves them signed in.
    }
  }
  return (
    <BottomSheet visible={shell.sheet === "account"} title={account?.name ?? t("accountsTitle")} onClose={shell.closeSheet}>
      {account ? <RoleLine account={account} project={shell.server ? device?.project_name : undefined} /> : null}
      <Text style={{ ...typography.caption, color: ui.mutedForeground, marginBottom: spacing.xs }}>{syncSummary(shell.sync)}</Text>
      <SheetRow label={t("settings")} onPress={go(() => router.push({ pathname: "/settings", params: { userId } }))} />
      <SheetRow label={t("formHelp")} onPress={() => shell.openSheet("help")} />
      <View style={{ minHeight: 52, flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm }}>
        <Text style={{ ...typography.body, color: ui.popoverForeground }}>{t("languageLabel")}</Text>
        <View style={{ flexDirection: "row", borderWidth: 1, borderColor: ui.input, borderRadius: radius.md, overflow: "hidden" }}>
          {UI_LOCALES.map((locale) => (
            <Pressable
              key={locale.code}
              accessibilityRole="button"
              accessibilityLabel={locale.label}
              accessibilityState={{ selected: locale.code === uiLocale }}
              onPress={() => void chooseUiLocale(locale.code)}
              style={{ minHeight: 40, minWidth: 80, alignItems: "center", justifyContent: "center", backgroundColor: locale.code === uiLocale ? ui.accent : ui.popover }}
            >
              <Text style={{ ...typography.subhead, color: locale.code === uiLocale ? ui.accentForeground : ui.popoverForeground, fontWeight: locale.code === uiLocale ? "700" : "400" }}>{locale.label}</Text>
            </Pressable>
          ))}
        </View>
      </View>
      <SheetRow label={t("lockNow")} disabled={!userId || !isUnlocked(userId)} onPress={go(() => void lockNow())} />
      <SheetRow label={t("switchInterviewer")} onPress={go(() => void lockNow().then((locked) => (locked ? router.replace("/") : lockFailed())))} />
      <SheetRow label={t("signOut")} tone="danger" disabled={!userId} onPress={go(() => userId && void confirmSignOut(userId, () => void doSignOut()))} />
      <Text style={{ ...typography.caption, color: ui.mutedForeground, marginTop: spacing.xs }}>{t("appVersionLabel", { version: APP_VERSION })}</Text>
    </BottomSheet>
  );
}

export function HelpSheet() {
  const shell = useShell();
  const pathname = usePathname();
  const toast = useToast();
  const { ui } = useTheme();
  const screen = helpScreenFor(pathname);
  const help = helpContent(screen, { offline: shell.sync.offline, unsent: shell.sync.work?.unsent });
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [openId, setOpenId] = useState<string>();
  const entries = faqEntries(query);
  // Leaving the open form from here would skip its save, so the "go" buttons that navigate are not offered on it.
  const leavesForm = screen === "form" || screen === "revision";
  /** The two sheets swap in place; the others close Help and open their screen. */
  function goTo(target: FaqTarget) {
    if (target === "account" || target === "sync") return shell.openSheet(target);
    shell.closeSheet();
    const params = { userId: shell.userId };
    if (target === "settings") router.push({ pathname: "/settings", params });
    else router.replace({ pathname: "/worklist", params: { ...params, view: "interviews", filter: target } });
  }
  function openGuide() {
    if (!shell.server) return;
    Linking.openURL(helpGuideUrl(shell.server, help.slug)).catch(() => toast.show({ kind: "error", text: t("helpGuideFailed") }));
  }
  return (
    <BottomSheet visible={shell.sheet === "help"} title={t("formHelp")} onClose={shell.closeSheet}>
      <Text style={{ ...typography.caption, color: ui.mutedForeground, fontWeight: "600" }}>{t("helpWhatFor")}</Text>
      <Text style={{ ...typography.body, color: ui.popoverForeground, marginBottom: spacing.sm }}>{help.what}</Text>
      <Text style={{ ...typography.caption, color: ui.mutedForeground, fontWeight: "600" }}>{t("helpWhatToDo")}</Text>
      {[...help.state, ...help.todo].map((line) => (
        <Text key={line} style={{ ...typography.body, color: ui.popoverForeground, marginTop: spacing.xxs }}>{`• ${line}`}</Text>
      ))}
      <View style={{ marginTop: spacing.md }}>
        <Button label={t("helpOpenGuide")} disabled={!shell.server} onPress={openGuide} />
      </View>
      <Text accessibilityRole="header" style={{ ...typography.headline, color: ui.popoverForeground, marginTop: spacing.lg }}>{t("faqTitle")}</Text>
      <TextInput
        accessibilityLabel={t("faqSearch")}
        placeholder={t("faqSearch")}
        placeholderTextColor={ui.mutedForeground}
        value={query}
        onChangeText={setQuery}
        style={{ ...typography.body, color: ui.popoverForeground, borderWidth: 1, borderColor: ui.input, borderRadius: radius.md, minHeight: 48, paddingHorizontal: spacing.sm, marginVertical: spacing.xs }}
      />
      {entries.length === 0 ? <Text style={{ ...typography.body, color: ui.mutedForeground }}>{t("faqNone")}</Text> : null}
      {entries.map((entry) => (
        <View key={entry.id} testID="faq-entry" style={{ borderTopWidth: 1, borderTopColor: ui.border }}>
          <SheetRow label={entry.question} onPress={() => setOpenId(openId === entry.id ? undefined : entry.id)} />
          {openId === entry.id || query.trim() ? (
            <View style={{ paddingBottom: spacing.sm, gap: spacing.xs }}>
              <Text style={{ ...typography.body, color: ui.popoverForeground }}>{entry.answer}</Text>
              {entry.target && (entry.target === "account" || entry.target === "sync" || (shell.userId && !leavesForm)) ? (
                <Button kind="secondary" label={entry.goLabel!} onPress={() => goTo(entry.target!)} />
              ) : null}
            </View>
          ) : null}
        </View>
      ))}
    </BottomSheet>
  );
}

export function SyncSheet() {
  const shell = useShell();
  const { accounts } = useAppState();
  const router = useRouter();
  const { ui } = useTheme();
  const { sync } = shell;
  const account = accounts.find((item) => item.user_id === shell.userId);
  const standalone = account?.standalone === true;
  const work = sync.work;
  const openDrafts = () => {
    shell.closeSheet();
    router.replace({ pathname: standalone ? "/standalone" : "/worklist", params: { userId: shell.userId, view: "interviews", filter: "drafts" } });
  };
  return (
    <BottomSheet visible={shell.sheet === "sync"} title={t("tabSync")} onClose={shell.closeSheet}>
      {standalone ? <Text style={{ ...typography.body, color: ui.popoverForeground }}>{t("standaloneWarning")}</Text> : null}
      <Text style={{ ...typography.body, color: ui.popoverForeground }}>{sync.lastAt ? t("syncChipSynced", { time: clock(sync.lastAt) }) : t("syncChipNever")}</Text>
      <Text style={{ ...typography.body, color: ui.popoverForeground }}>{work ? t("syncUnsentScoped", { count: work.unsent }) : t("syncUnsentUnknown")}</Text>
      {work?.attention ? <Text style={{ ...typography.subhead, color: ui.destructiveText }}>{t("syncAttentionCount", { count: work.attention })}</Text> : null}
      {work?.items.map((item) => (
        <View key={item.key} testID="sync-item" style={{ paddingVertical: spacing.xxs }}>
          <Text style={{ ...typography.body, color: ui.popoverForeground }}>{`${t(`unsentKind_${item.kind}`)}: ${item.title}`}</Text>
          <Text style={{ ...typography.caption, color: item.state === "attention" ? ui.destructiveText : ui.mutedForeground }}>{t(`unsentState_${item.state}`)}</Text>
          {item.reason ? <Text style={{ ...typography.caption, color: ui.destructiveText }}>{t("refusalNotAccepted", { reason: item.reason })}</Text> : null}
          {item.error ? <Text style={{ ...typography.caption, color: ui.mutedForeground }}>{t("unsentRef", { ref: item.error })}</Text> : null}
        </View>
      ))}
      {work?.inProgress ? <SheetRow label={t("syncDraftsLink", { count: work.inProgress })} onPress={openDrafts} /> : null}
      {standalone ? <Button kind="secondary" label={t("standaloneEnrol")} onPress={() => { shell.closeSheet(); router.push("/enrol"); }} /> : null}
      {sync.result ? <Text style={{ ...typography.subhead, color: ui.mutedForeground, marginTop: spacing.xs }}>{t("syncLastResult", { text: sync.result })}</Text> : null}
      {account && !standalone ? (
        <View style={{ marginTop: spacing.md, gap: spacing.xs }}>
          <Button label={t("sendNow")} loading={sync.busy} disabled={sync.busy || !shell.userId} onPress={() => void shell.sendNow()} />
          <Button kind="secondary" label={t("refresh")} disabled={sync.busy || !shell.userId} onPress={() => void shell.refreshNow()} />
        </View>
      ) : null}
    </BottomSheet>
  );
}
