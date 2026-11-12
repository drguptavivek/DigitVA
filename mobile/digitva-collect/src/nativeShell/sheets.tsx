/** The three shell sheets: Account menu, Help and Sync. Open state lives in the ShellProvider (shell.tsx). */
import { usePathname, useRouter } from "expo-router";
import { useState } from "react";
import { Linking, Text, View } from "react-native";

import { useAppState } from "../AppState";
import { signOut } from "../auth";
import { t } from "../i18n";
import { isUnlocked } from "../interviewerDb";
import { confirmSignOut } from "../signOutConfirm";
import { spacing, useTheme } from "../theme";
import { useToast } from "../toast";
import { APP_VERSION } from "../appVersion";
import { isPlusVariant } from "../appVariant";
import { displayProjectName } from "../projectName";
import { canTryDorisDemo } from "../dorisDemoAccess";
import { icons } from "../Icon";
import { Button, Card, ListRow, Notice, SectionLabel, Separator, TextField } from "../ui";
import { UiLanguageRow } from "../ui/LanguagePicker";
import { BulletItem } from "../ui/controls";
import { RoleChip, RoleChips } from "../ui/RoleChip";
import { BottomSheet, SheetRow } from "./BottomSheet";
import { faqEntries, type FaqTarget } from "./faq";
import { helpContent, helpGuideUrl, helpScreenFor } from "./helpContent";
import { syncedText, useShell, type SyncStatus } from "./shellContext";

/** The unsent count in the Sync sheet's words: "3 unsent", "Nothing to send" at 0. */
export function unsentText(unsent: number): string {
  return unsent > 0 ? t("syncUnsentScoped", { count: unsent }) : t("syncNothingToSend");
}

/** "Synced today, 2:05 pm · 3 unsent" (parts that are not known yet are left out); the Sync sheet's words. */
export function syncSummary(sync: SyncStatus): string {
  const parts = [syncedText(sync.lastAt)];
  if (sync.work) parts.push(unsentText(sync.work.unsent));
  return parts.join(" · ");
}

/** The project on its own line (display name), then the account's phone roles as chips on theirs. */
function RoleLine({ account, project }: { account: { collection_access?: boolean; registration_access?: boolean }; project?: string }) {
  const { ui, typography } = useTheme();
  const roles = [account.collection_access ? "interviewer" : "", account.registration_access ? "death_reporter" : ""].filter(Boolean);
  return (
    <View style={{ gap: spacing.xs }}>
      {project ? <Text style={{ ...typography.subhead, color: ui.mutedForeground }}>{displayProjectName(project)}</Text> : null}
      {roles.length ? <RoleChips>{roles.map((role) => <RoleChip key={role} role={role} plain />)}</RoleChips> : null}
    </View>
  );
}

export function AccountSheet() {
  const shell = useShell();
  const router = useRouter();
  const { accounts, device, lockNow, reload } = useAppState();
  const { ui, typography } = useTheme();
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
    // Two white cards: the sheet takes the canvas tone so they stand apart from it, as on a screen.
    <BottomSheet cards visible={shell.sheet === "account"} title={account?.name ?? t("accountsTitle")} onClose={shell.closeSheet}>
      {account ? <RoleLine account={account} project={shell.server ? device?.project_name : undefined} /> : null}
      <Text style={{ ...typography.subhead, color: ui.mutedForeground, marginTop: spacing.xs, marginBottom: spacing.sm }}>{syncSummary(shell.sync)}</Text>
      <Card grouped>
        <ListRow icon={icons.settings} label={t("settings")} onPress={go(() => router.push({ pathname: "/settings", params: { userId } }))} />
        <Separator icon />
        <ListRow icon={icons.help} label={t("formHelp")} onPress={() => shell.openSheet("help")} />
        <Separator icon />
        {/* The translate glyph (as in the Sign in bar) lines its label up with Settings and Help. */}
        <UiLanguageRow icon={icons.language} label={t("languageLabel")} />
      </Card>
      {/* Actions, not navigation: no chevrons. Sign out keeps the encrypted data (digitva-dxgj), so it is ink, not red. */}
      <Card grouped style={{ marginTop: spacing.md }}>
        <ListRow testID="account-lock-now" icon={icons.lock} label={t("lockNow")} chevron={false} disabled={!userId || !isUnlocked(userId)} onPress={go(() => void lockNow())} />
        <Separator icon />
        <ListRow testID="account-switch-profile" icon={icons.switchUser} label={t("switchInterviewer")} chevron={false} onPress={go(() => void lockNow().then((locked) => (locked ? router.replace("/") : lockFailed())))} />
        <Separator icon />
        <ListRow icon={icons.signOut} label={t("signOut")} chevron={false} disabled={!userId} onPress={go(() => userId && void confirmSignOut(userId, () => void doSignOut()))} />
      </Card>
      <Text style={{ ...typography.subhead, color: ui.mutedForeground, marginTop: spacing.xs, paddingHorizontal: spacing.md }}>
        {isPlusVariant() ? t("appVersionVariant", { version: APP_VERSION, variant: "Plus" }) : t("appVersionLabel", { version: APP_VERSION })}
      </Text>
    </BottomSheet>
  );
}

export function HelpSheet() {
  const shell = useShell();
  const pathname = usePathname();
  const { accounts } = useAppState();
  const toast = useToast();
  const { ui, typography } = useTheme();
  const screen = helpScreenFor(pathname);
  // Standalone has no server and no Sync tab, so its Help never points at either.
  const standalone = accounts.find((item) => item.user_id === shell.userId)?.standalone === true;
  const help = helpContent(screen, { offline: shell.sync.offline, unsent: shell.sync.work?.unsent, standalone });
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [openId, setOpenId] = useState<string>();
  const entries = faqEntries(query, standalone);
  // Leaving the open form from here would skip its save, so the "go" buttons that navigate are not offered on it.
  const leavesForm = screen === "form" || screen === "revision";
  // A "go" button for the screen Help was opened on would only push a duplicate of it.
  // (Worklist filters are left out: the list changes its filter in place, so the address can be stale.)
  const onTargetScreen = (target: FaqTarget) => target === "settings" && screen === "settings";
  /** The two sheets swap in place; the others close Help and open their screen. */
  function goTo(target: FaqTarget) {
    if (target === "account" || target === "sync") return shell.openSheet(target);
    shell.closeSheet();
    const params = { userId: shell.userId };
    if (target === "settings") router.push({ pathname: "/settings", params });
    else router.dismissTo({ pathname: "/worklist", params: { ...params, view: "interviews", filter: target } });
  }
  // Every "go" button opens something of an account (its menu with Sign out, Sync, Settings, its worklist), so none is
  // offered unless that account's store is unlocked: before the PIN, Help is the guide, the FAQ text and Try DORIS only.
  const unlocked = shell.userId !== undefined && isUnlocked(shell.userId);
  // The offline DORIS demo needs no account, so Help offers it before sign-in too (not on the demo itself, nor over an open form).
  const tryDoris = canTryDorisDemo() && !leavesForm && pathname !== "/doris-demo";
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
        <View key={line} style={{ marginTop: spacing.xxs }}><BulletItem textStyle={{ color: ui.popoverForeground }}>{line}</BulletItem></View>
      ))}
      {shell.server ? (
        <View style={{ marginTop: spacing.md }}>
          <Button label={t("helpOpenGuide")} onPress={openGuide} />
        </View>
      ) : null}
      {tryDoris ? (
        <View style={{ marginTop: spacing.md }}>
          <Button kind="secondary" label={t("helpTryDoris")} onPress={() => { shell.closeSheet(); router.push("/doris-demo"); }} />
        </View>
      ) : null}
      <Text accessibilityRole="header" style={{ ...typography.headline, color: ui.popoverForeground, marginTop: spacing.lg }}>{t("faqTitle")}</Text>
      {/* On the white sheet the field takes the neutral fill; no edge until focused. */}
      <TextField
        onCard
        accessibilityLabel={t("faqSearch")}
        placeholder={t("faqSearch")}
        value={query}
        onChangeText={setQuery}
        style={{ marginVertical: spacing.xs }}
      />
      {entries.length === 0 ? <Text style={{ ...typography.body, color: ui.mutedForeground }}>{t("faqNone")}</Text> : null}
      {entries.map((entry) => (
        <View key={entry.id} testID="faq-entry" style={{ borderTopWidth: 1, borderTopColor: ui.border }}>
          <SheetRow label={entry.question} onPress={() => setOpenId(openId === entry.id ? undefined : entry.id)} />
          {openId === entry.id || query.trim() ? (
            <View style={{ paddingBottom: spacing.sm, gap: spacing.xs }}>
              <Text style={{ ...typography.body, color: ui.popoverForeground }}>{entry.answer}</Text>
              {entry.target && unlocked && (entry.target === "account" || entry.target === "sync" || (!leavesForm && !onTargetScreen(entry.target))) ? (
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
  const { ui, typography } = useTheme();
  const { sync } = shell;
  const account = accounts.find((item) => item.user_id === shell.userId);
  const standalone = account?.standalone === true;
  const work = sync.work;
  const attention = work?.items.filter((item) => item.state === "attention") ?? [];
  const queued = work?.items.filter((item) => item.state !== "attention") ?? [];
  // Nothing to send: Send now is hidden and Refresh becomes the sheet's one filled button.
  const nothingToSend = work !== undefined && work.unsent === 0 && !work.unsentFiles;
  const openDrafts = () => {
    shell.closeSheet();
    router.dismissTo({ pathname: standalone ? "/standalone" : "/worklist", params: { userId: shell.userId, view: "interviews", filter: "drafts" } });
  };
  return (
    <BottomSheet visible={shell.sheet === "sync"} title={t("tabSync")} onClose={shell.closeSheet}>
      {standalone ? <Notice tone="warning">{t("standaloneWarning")}</Notice> : null}
      {/* One status line, then the count: what the sheet is for. */}
      <Text style={{ ...typography.subhead, color: ui.mutedForeground }}>{syncedText(sync.lastAt)}</Text>
      <Text style={{ ...typography.body, color: ui.popoverForeground }}>{work ? unsentText(work.unsent) : t("syncUnsentUnknown")}</Text>
      {work?.attention ? <Notice tone="error">{t("syncAttentionCount", { count: work.attention })}</Notice> : null}
      {/* Refused items first, under their own label, only when there are any; then the rest of the unsent work. */}
      {attention.length ? <View style={{ marginTop: spacing.sm, marginLeft: -spacing.md }}><SectionLabel>{t("syncNeedsAttention")}</SectionLabel></View> : null}
      {[...attention, ...queued].map((item) => (
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
      {account && !standalone && isUnlocked(account.user_id) ? (
        <View style={{ marginTop: spacing.md, gap: spacing.sm }}>
          {/* No connection: Send now would only fail, so it waits. */}
          {nothingToSend ? null : <Button label={t("sendNow")} loading={sync.busy} disabled={sync.busy || !shell.userId || sync.offline} onPress={() => void shell.sendNow()} />}
          <Button kind={nothingToSend ? "primary" : "secondary"} label={t("refresh")} disabled={sync.busy || !shell.userId} onPress={() => void shell.refreshNow()} />
        </View>
      ) : null}
    </BottomSheet>
  );
}
