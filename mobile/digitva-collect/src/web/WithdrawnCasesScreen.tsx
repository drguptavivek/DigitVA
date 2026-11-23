/**
 * Withdrawn cases (web, admin only; docs/policy/consent-withdrawal.md): the cases whose respondent withdrew
 * consent, newest first. A row opens the sealed case detail, where the banner and Undo live (SupervisionActions).
 * The list carries no respondent text; the server refuses anyone but an admin.
 */
import { useEffect, useState } from "react";
import { Text, TextInput, View } from "react-native";

import { t, type StringKey } from "../i18n";
import { listConsentWithdrawals, type WithdrawnCaseRow } from "../supervision/api";
import { Button, useUiStyles } from "../ui";
import { browserErrorText, WebShell } from "./common";
import { SupervisionCaseDetail } from "../supervision/SupervisionCase";
import { useWebSupervisionHost } from "./supervisionHost";

const day = (iso: string) => iso.slice(0, 10);

export default function WithdrawnCasesScreen() {
  const styles = useUiStyles();
  const host = useWebSupervisionHost();
  const request = host?.request;
  const [draftProject, setDraftProject] = useState("");
  const [projectId, setProjectId] = useState("");
  const [includeUndone, setIncludeUndone] = useState(false);
  const [rows, setRows] = useState<WithdrawnCaseRow[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selected, setSelected] = useState<string | undefined>();
  const [reloads, setReloads] = useState(0);

  useEffect(() => {
    if (!request) return undefined;
    let active = true;
    setBusy(true);
    setError("");
    listConsentWithdrawals(request, { projectId, includeUndone })
      .then((page) => {
        if (!active) return;
        setRows(page.withdrawals);
        setNextCursor(page.next_cursor);
        setLoaded(true);
      })
      .catch((caught) => {
        if (active) setError(browserErrorText(caught));
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [request, projectId, includeUndone, reloads]);

  async function loadMore() {
    if (!request || !nextCursor) return;
    setBusy(true);
    try {
      const page = await listConsentWithdrawals(request, { projectId, includeUndone, cursor: nextCursor });
      setRows((previous) => [...previous, ...page.withdrawals]);
      setNextCursor(page.next_cursor);
    } catch (caught) {
      setError(browserErrorText(caught));
    } finally {
      setBusy(false);
    }
  }

  // An undo (or any action) in the detail returns to a fresh list.
  function finish(message: string) {
    setSelected(undefined);
    setNotice(message);
    setReloads((count) => count + 1);
  }

  return (
    <WebShell title={t("navWithdrawnCases")}>
      {selected && host ? (
        <SupervisionCaseDetail host={host} deathId={selected} onBack={() => setSelected(undefined)} onDone={finish} />
      ) : (
        <View style={{ gap: 12 }}>
          <Text style={styles.muted}>{t("withdrawnCasesIntro")}</Text>
          {notice ? <Text style={styles.text} role="status">{notice}</Text> : null}
          <Text style={styles.muted}>{t("withdrawnCasesProject")}</Text>
          <TextInput
            accessibilityLabel={t("withdrawnCasesProject")}
            value={draftProject}
            onChangeText={setDraftProject}
            maxLength={6}
            autoCapitalize="characters"
            autoCorrect={false}
            style={styles.input}
          />
          <View style={styles.row}>
            <Button size="sm" kind="secondary" label={t("withdrawnCasesApply")} onPress={() => setProjectId(draftProject.trim())} />
            <Button
              size="sm"
              kind={includeUndone ? "primary" : "secondary"}
              label={t("withdrawnCasesIncludeUndone")}
              onPress={() => setIncludeUndone((current) => !current)}
            />
          </View>
          {error ? <Text style={styles.error} accessibilityRole="alert">{error}</Text> : null}
          {busy && rows.length === 0 ? <Text style={styles.muted}>{t("loading")}</Text> : null}
          {loaded && !busy && rows.length === 0 && !error ? <Text style={styles.muted}>{t("withdrawnCasesEmpty")}</Text> : null}
          {rows.map((row) => (
            <View key={row.withdrawal_id} style={styles.card}>
              <Text style={styles.text}>
                {t("withdrawnCasesRow", {
                  unique_id: row.unique_id,
                  project: row.project_name,
                  requested_on: row.requested_on,
                  recorded_at: day(row.recorded_at),
                  channel: t(`supervisionWithdrawalChannel_${row.channel}` as StringKey),
                  recorded_by: row.recorded_by_name,
                })}
              </Text>
              {row.undone ? <Text style={styles.muted}>{t("withdrawnCasesUndone")}</Text> : null}
              <View style={styles.row}>
                <Button size="sm" kind="secondary" label={t("withdrawnCasesOpen")} onPress={() => setSelected(row.death_id)} />
              </View>
            </View>
          ))}
          {nextCursor ? <Button size="sm" kind="secondary" loading={busy} label={t("loadMore")} onPress={() => void loadMore()} /> : null}
        </View>
      )}
    </WebShell>
  );
}
