/**
 * The adoption offer and push on the standalone home (src/standalone/adopt.ts). The home sits behind the
 * standalone PIN, so confirming here is the PIN-confirmed adoption Path C requires: it names the server, the
 * counts, the account and the site, and nothing is sent until the user confirms. Afterwards "Send now" pushes;
 * refusals stay listed until dismissed.
 */
import { useCallback, useEffect, useState } from "react";
import { Text, View } from "react-native";

import { useAppState } from "../AppState";
import { refreshAccessSummaryForAction, type Account } from "../auth";
import type { Db } from "../drafts";
import { t } from "../i18n";
import { getOrCreatePlusDeviceIdentity } from "../offlineIdentity";
import { Button, errorText, useUiStyles } from "../ui";
import {
  adoptionOffer,
  adoptionSites,
  adoptionTargets,
  codingNoticeText,
  codingNotices,
  dismissCodingNotices,
  getAdoption,
  pushStandaloneRecords,
  saveAdoption,
  standaloneCounts,
  type AdoptionSite,
  type CodingNotice,
  type StandaloneAdoption,
  type StandaloneCounts,
} from "./adopt";

/** `refresh` changes when the home's records change, so the counts follow without remounting (and losing the result). */
export function AdoptionCard({ db, refresh, onChanged }: { db: Db; refresh: number; onChanged: () => void }) {
  const styles = useUiStyles();
  const { device, accounts } = useAppState();
  const [adoption, setAdoption] = useState<StandaloneAdoption | null>();
  const [counts, setCounts] = useState<StandaloneCounts>();
  const [notices, setNotices] = useState<CodingNotice[]>([]);
  const [target, setTarget] = useState<Account>();
  const [sites, setSites] = useState<AdoptionSite[]>();
  const [site, setSite] = useState<AdoptionSite>();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    const identity = await getOrCreatePlusDeviceIdentity();
    setAdoption(await getAdoption(db));
    setCounts(await standaloneCounts(db, identity?.uuid ?? ""));
    setNotices(await codingNotices(db));
  }, [db]);
  useEffect(() => {
    load().catch((caught) => setMessage(errorText(caught)));
  }, [load, refresh]);

  async function run(work: () => Promise<void>) {
    setBusy(true);
    setMessage("");
    try {
      await work();
    } catch (caught) {
      setMessage(errorText(caught));
    } finally {
      setBusy(false);
    }
  }

  const chooseTarget = (account: Account) => run(async () => {
    setTarget(account);
    setSite(undefined);
    setSites(adoptionSites(await refreshAccessSummaryForAction(account.user_id)));
  });

  async function push() {
    try {
      const result = await pushStandaloneRecords(db);
      setMessage(t("standaloneSendResult", { sent: result.sent, failed: result.failed }));
    } finally {
      await load();
      onChanged();
    }
  }
  const send = () => run(push);

  const confirm = () => run(async () => {
    if (!device || !target || !site) return;
    await saveAdoption(db, {
      userId: target.user_id, userName: target.name, server: device.server,
      projectId: site.projectId, siteId: site.siteId, siteName: site.siteName, adoptedAt: new Date().toISOString(),
    });
    await push();
  });

  if (!device || !counts || adoption === undefined) return null;
  const host = new URL(device.server).host;
  const countLines = (
    <>
      <Text style={styles.text}>{t("standaloneAdoptCounts", { interviews: counts.interviews, codings: counts.codings })}</Text>
      {counts.staleDraftIds.length ? <Text style={styles.error}>{t("standaloneAdoptStale", { count: counts.staleDraftIds.length, ids: counts.staleDraftIds.map((id) => id.slice(0, 8)).join(", ") })}</Text> : null}
      <Text style={styles.muted}>{t("standaloneAdoptKept")}</Text>
    </>
  );
  const footer = (
    <>
      {notices.length ? (
        <View style={{ gap: 4 }}>
          <Text style={styles.text}>{t("standaloneCodingRefusedTitle")}</Text>
          {notices.map((notice) => (
            <Text key={`${notice.draftId}:${notice.at}`} style={styles.muted} selectable>{notice.draftId.slice(0, 8)} · {codingNoticeText(notice.code)}</Text>
          ))}
          <Button kind="secondary" label={t("standaloneDismiss")} disabled={busy} onPress={() => void dismissCodingNotices(db).then(load)} />
        </View>
      ) : null}
      {message ? <Text style={styles.muted}>{message}</Text> : null}
    </>
  );

  if (adoption) {
    if (adoption.server !== device.server) return <View style={styles.card}><Text style={styles.error}>{t("standaloneAdoptServerChanged")}</Text></View>;
    return (
      <View style={[styles.card, { gap: 8 }]}>
        <Text style={styles.text}>{t("standaloneAdoptedTo", { host, name: adoption.userName, site: adoption.siteName })}</Text>
        {countLines}
        <Button label={t("standaloneSendNow")} loading={busy} disabled={busy || counts.interviews === 0} onPress={() => void send()} />
        {footer}
      </View>
    );
  }

  const offer = adoptionOffer({ device, accounts, counts, adoption });
  if (!offer) {
    // Enrolled with records to send, but no account to send them as yet.
    return counts.interviews > 0 && adoptionTargets(accounts).length === 0
      ? <View style={styles.card}><Text style={styles.muted}>{t("standaloneAdoptSignIn", { host })}</Text></View>
      : null;
  }
  return (
    <View style={[styles.card, { gap: 8 }]}>
      <Text style={[styles.text, { fontWeight: "700" }]}>{t("standaloneAdoptOffer", { host: offer.host })}</Text>
      {countLines}
      {offer.targets.map((account) => (
        <Button key={account.user_id} kind={target?.user_id === account.user_id ? "primary" : "secondary"}
          label={t("standaloneAdoptAs", { name: account.name })} disabled={busy} onPress={() => void chooseTarget(account)} />
      ))}
      {target && sites?.length === 0 ? <Text style={styles.error}>{t("standaloneAdoptNoSite")}</Text> : null}
      {target && sites?.length ? <Text style={styles.muted}>{t("standaloneAdoptSite")}</Text> : null}
      {target && sites?.map((choice) => (
        <Button key={`${choice.projectId}:${choice.siteId}`} kind={site === choice ? "primary" : "secondary"}
          label={choice.siteName} disabled={busy} onPress={() => setSite(choice)} />
      ))}
      {site ? <Button label={t("standaloneAdoptConfirm")} loading={busy} disabled={busy} onPress={() => void confirm()} /> : null}
      {footer}
    </View>
  );
}
