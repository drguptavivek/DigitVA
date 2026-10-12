import { useEffect, useMemo, useRef, useState } from "react";
import { Text, View } from "react-native";
import { WhoVaQuestionControls } from "@drguptavivek/who-2022-va/native";

import { useAppState } from "../AppState";
import { listCases, SUPERVISION_STATES, type SupervisedCase } from "../supervision/api";
import { SUPERVISION_ROLES } from "../api";
import { t } from "../i18n";
import type { JsonRequester } from "../workspace/api";
import { createWebWorkspaceTransport } from "../workspace/transport.web";
import { choiceQuestion } from "../workspace/QualityPanels";
import { Button, stateLabel, useUiStyles } from "../ui";
import { browserErrorText, WebShell } from "./common";
import { CaseSummary, SupervisionCaseDetail } from "./SupervisionCase";
import { SupervisionActions } from "./SupervisionActions";

const ANY_STATE = "any";

/** Interview supervisors' cases: flags to resolve, all cases, and each case's detail. */
export default function SupervisionScreen() {
  const { bootstrap } = useAppState();
  const styles = useUiStyles();
  const request: JsonRequester | undefined = useMemo(
    () => (bootstrap ? createWebWorkspaceTransport(bootstrap.csrf) : undefined),
    [bootstrap],
  );
  const [flagsOnly, setFlagsOnly] = useState(true);
  const [state, setState] = useState(ANY_STATE);
  const [visitNotesOnly, setVisitNotesOnly] = useState(false);
  const [rows, setRows] = useState<SupervisedCase[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [reloads, setReloads] = useState(0);
  const [selected, setSelected] = useState<string | undefined>();
  // A load-more reply from a previous filter, or from before an action reloaded the list, must not land in the current list.
  const listKey = `${flagsOnly}|${state}|${visitNotesOnly}|${reloads}`;
  const listKeyRef = useRef(listKey);
  listKeyRef.current = listKey;

  const canSupervise = bootstrap?.access.roles.some((role) => SUPERVISION_ROLES.includes(role)) === true;

  useEffect(() => {
    if (!request || !canSupervise) return undefined;
    let active = true;
    setBusy(true);
    setError("");
    listCases(request, { flagsOnly, state: state === ANY_STATE ? "" : state, visitNotesOnly })
      .then((page) => {
        if (!active) return;
        setRows(page.cases);
        setCounts(page.counts);
        setNextCursor(page.next_cursor);
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
  }, [request, canSupervise, flagsOnly, state, visitNotesOnly, reloads]);

  if (!bootstrap) return <WebShell title={t("supervisionTitle")}>{null}</WebShell>;
  if (!canSupervise) {
    return (
      <WebShell title={t("supervisionTitle")}>
        <Text role="alert" style={styles.error}>{t("serverForbidden")}</Text>
      </WebShell>
    );
  }

  function finish(message: string) {
    setSelected(undefined);
    setNotice(message);
    setReloads((count) => count + 1);
  }

  async function loadMore() {
    if (!request || !nextCursor) return;
    const key = listKey;
    setBusy(true);
    try {
      const page = await listCases(request, { flagsOnly, state: state === ANY_STATE ? "" : state, visitNotesOnly, cursor: nextCursor });
      if (listKeyRef.current !== key) return;
      setRows((previous) => [...previous, ...page.cases]);
      setNextCursor(page.next_cursor);
    } catch (caught) {
      if (listKeyRef.current === key) setError(browserErrorText(caught));
    } finally {
      if (listKeyRef.current === key) setBusy(false);
    }
  }

  function showTab(flags: boolean) {
    setNotice("");
    setSelected(undefined);
    setFlagsOnly(flags);
  }

  const inScope = Object.values(counts).reduce((sum, count) => sum + count, 0);
  const emptyText = !inScope ? t("supervisionNoScope") : flagsOnly ? t("supervisionNoFlags") : t("supervisionNoCasesHere");
  const stateOptions = [
    { value: ANY_STATE, label: t("supervisionAnyState") },
    ...SUPERVISION_STATES.map((code) => ({ value: code, label: stateLabel(code) })),
  ];

  return (
    <WebShell title={t("supervisionTitle")}>
      {selected && request ? (
        <SupervisionCaseDetail request={request} deathId={selected} onBack={() => setSelected(undefined)} onDone={finish} />
      ) : (
        <>
          <View style={styles.row}>
            <Button kind={flagsOnly ? "primary" : "secondary"} label={t("supervisionTabFlags")} onPress={() => showTab(true)} />
            <Button kind={flagsOnly ? "secondary" : "primary"} label={t("supervisionTabAll")} onPress={() => showTab(false)} />
            <Button
              kind={visitNotesOnly ? "primary" : "secondary"}
              label={t("supervisionVisitNotes")}
              onPress={() => setVisitNotesOnly((on) => !on)}
            />
          </View>
          {!flagsOnly ? (
            <WhoVaQuestionControls.SingleChoice
              question={choiceQuestion("supervision-state", t("supervisionStateFilter"), "singleChoice", stateOptions)}
              value={state}
              data={{}}
              locale="en"
              issues={[]}
              choiceColumns={2}
              onAnswer={(value) => {
                if (typeof value === "string") setState(value);
              }}
            />
          ) : null}
          {notice ? <Text style={styles.muted} accessibilityRole="alert">{notice}</Text> : null}
          {error ? <Text style={styles.error} accessibilityRole="alert">{error}</Text> : null}
          {rows.length === 0 && !busy ? <Text style={styles.muted}>{emptyText}</Text> : null}
          {rows.map((row) => (
            <View key={row.death_id} style={styles.card}>
              <CaseSummary row={row} />
              {request ? <SupervisionActions request={request} row={row} onDone={finish} /> : null}
              <Button kind="secondary" label={t("viewDetails")} onPress={() => setSelected(row.death_id)} />
            </View>
          ))}
          {nextCursor ? <Button kind="secondary" loading={busy} label={t("loadMore")} onPress={() => void loadMore()} /> : null}
        </>
      )}
    </WebShell>
  );
}
