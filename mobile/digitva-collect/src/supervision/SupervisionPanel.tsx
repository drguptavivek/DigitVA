import { useEffect, useRef, useState } from "react";
import { Text, View } from "react-native";

import { listCases, SUPERVISION_STATES, type SupervisedCase, type SupervisionTiles } from "./api";
import { t } from "../i18n";
import { Button, stateLabel, useUiStyles } from "../ui";
import type { SupervisionHost } from "./host";
import { CaseSummary, SupervisionCaseDetail } from "./SupervisionCase";
import { SupervisionActions } from "./SupervisionActions";

const ANY_STATE = "any";
const TILES = [
  { key: "needs_decision", label: "supervisionTileDecision" },
  { key: "overdue", label: "supervisionTileOverdue" },
  { key: "stuck", label: "supervisionTileStuck" },
  { key: "total", label: "supervisionTileTotal" },
] as const;
type TileKey = (typeof TILES)[number]["key"];
const NO_TILES: SupervisionTiles = { needs_decision: 0, overdue: 0, stuck: 0, total: 0 };

/** A tile's list filter. Attention tiles page oldest first (the longest-waiting case on top); Total in scope is newest first. */
function tileQuery(tile: TileKey) {
  return {
    needsDecision: tile === "needs_decision",
    overdue: tile === "overdue",
    stuck: tile === "stuck",
    sort: tile === "total" ? ("newest" as const) : ("oldest" as const),
  };
}

/**
 * The supervisor's part of the Deaths tab (docs/policy/case-list-views.md,
 * "Supervision preset"): four tiles that filter the supervised cases (Needs my
 * decision by default), the state and visit-note filters, and each case's
 * actions and detail. The host says what the platform offers (browser Deaths
 * screen, or the phone's Supervision screen); it owns the shell and the access check.
 */
export function SupervisionList({ host }: { host: SupervisionHost }) {
  const { request } = host;
  const styles = useUiStyles();
  const [tile, setTile] = useState<TileKey>("needs_decision");
  const [tiles, setTiles] = useState<SupervisionTiles>(NO_TILES);
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
  const listKey = `${tile}|${state}|${visitNotesOnly}|${reloads}`;
  const listKeyRef = useRef(listKey);
  listKeyRef.current = listKey;

  useEffect(() => {
    let active = true;
    setBusy(true);
    setError("");
    listCases(request, { ...tileQuery(tile), state: state === ANY_STATE ? "" : state, visitNotesOnly })
      .then((page) => {
        if (!active) return;
        setRows(page.cases);
        setCounts(page.counts);
        setTiles(page.tiles ?? NO_TILES);
        setNextCursor(page.next_cursor);
      })
      .catch((caught) => {
        if (active) setError(host.errorText(caught));
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [request, tile, state, visitNotesOnly, reloads]);

  function finish(message: string) {
    setSelected(undefined);
    setNotice(message);
    setReloads((count) => count + 1);
  }

  async function loadMore() {
    if (!nextCursor) return;
    const key = listKey;
    setBusy(true);
    try {
      const page = await listCases(request, { ...tileQuery(tile), state: state === ANY_STATE ? "" : state, visitNotesOnly, cursor: nextCursor });
      if (listKeyRef.current !== key) return;
      setRows((previous) => [...previous, ...page.cases]);
      setNextCursor(page.next_cursor);
    } catch (caught) {
      if (listKeyRef.current === key) setError(host.errorText(caught));
    } finally {
      if (listKeyRef.current === key) setBusy(false);
    }
  }

  function showTile(next: TileKey) {
    setNotice("");
    setSelected(undefined);
    setTile(next);
  }

  const inScope = Object.values(counts).reduce((sum, count) => sum + count, 0);
  const emptyText = !inScope ? t("supervisionNoScope") : tile === "needs_decision" ? t("supervisionNoDecision") : t("supervisionNoCasesHere");
  // Counts ignore every filter, so the buttons stay put; states with no case are left out.
  const stateButtons = [
    { code: ANY_STATE, label: `${t("supervisionAnyState")} (${inScope})` },
    ...SUPERVISION_STATES.filter((code) => counts[code]).map((code) => ({ code, label: `${stateLabel(code)} (${counts[code]})` })),
  ];

  return selected ? (
    <SupervisionCaseDetail host={host} deathId={selected} onBack={() => setSelected(undefined)} onDone={finish} />
  ) : (
    <>
      <View style={styles.row}>
        {TILES.map(({ key, label }) => (
          <Button
            key={key}
            size="sm"
            kind={tile === key ? "primary" : "secondary"}
            label={`${t(label)} (${tiles[key]})`}
            onPress={() => showTile(key)}
          />
        ))}
      </View>
      <View style={styles.row} accessibilityLabel={t("supervisionStateFilter")}>
        {stateButtons.map((button) => (
          <Button
            key={button.code}
            size="sm"
            kind={state === button.code ? "primary" : "secondary"}
            label={button.label}
            onPress={() => setState(button.code)}
          />
        ))}
        <Button
          size="sm"
          kind={visitNotesOnly ? "primary" : "secondary"}
          label={t("supervisionVisitNotes")}
          onPress={() => setVisitNotesOnly((on) => !on)}
        />
      </View>
      {notice ? <Text style={styles.muted} accessibilityRole="alert">{notice}</Text> : null}
      {error ? <Text style={styles.error} accessibilityRole="alert">{error}</Text> : null}
      {rows.length === 0 && !busy ? <Text style={styles.muted}>{emptyText}</Text> : null}
      {rows.map((row) => (
        <View key={row.death_id} style={styles.card} testID="supervision-card">
          <CaseSummary row={row} />
          <SupervisionActions host={host} row={row} onDone={finish} />
          <Button size="sm" kind="secondary" label={t("viewDetails")} onPress={() => setSelected(row.death_id)} testID="supervision-view-details" />
          {host.identifierAction?.(row, () => setReloads((count) => count + 1))}
        </View>
      ))}
      {nextCursor ? <Button size="sm" kind="secondary" loading={busy} label={t("loadMore")} onPress={() => void loadMore()} /> : null}
    </>
  );
}
