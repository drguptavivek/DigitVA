import { useEffect, useRef, useState, type ReactNode } from "react";
import { Keyboard, KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, View, useWindowDimensions } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import type { DorisCodeInfoReply, DorisTermsReply } from "../../contracts";
import type { DorisOption } from "../guidance";
import type { PickerFrameProps } from "../IcdPickerFrame";
import { AUTO_SEARCH_DELAY_MS, AUTO_SEARCH_MIN_CHARS } from "../compact";
import { Alert, Button, Input, SectionTitle, font, gap, useUi } from "../ui";
import { BuildCard, type BuildPreview } from "./BuildCard";
import { DetailsCard } from "./DetailsCard";
import { HierarchyCard } from "./HierarchyCard";
import { Reveal } from "./Panel";
import { RelatedCard, type RelatedTerm } from "./RelatedCard";
import { ResultRow, type Chapter } from "./ResultRow";
import { isComplete, isMandatory, looksCode, notFinal, splitExpression, type PickerItem } from "./expression";
import { errorMessage, Notice, usePost } from "./transport";

const MAX_QUERY = 80;
// The server refuses a search under 2 characters; the app's own auto-search starts at AUTO_SEARCH_MIN_CHARS.
const MIN_QUERY = 2;
const HEX_COLOUR = /^#[0-9a-fA-F]{6}$/;
// The footer never takes more than this share of the window; its text scrolls inside it.
const FOOTER_SHARE = 0.28;
// Tablets (useUi().phone false) split the picker once a card is open: results take this share of the width, never less than the minimum.
const LIST_SHARE = 0.4;
const LIST_MIN = 320;

interface Message {
  text: string;
  error?: boolean;
}

/** Every card carries a new `n` each time it is opened, so it is laid out afresh and scrolled to once; `scroll` is false for a card the picker opens itself. */
interface Slot {
  n: number;
  scroll: boolean;
}

/** WHO withholds a stem whose postcoordination is mandatory until its required axes are chosen; the stem alone must never be used. */
const needsBuild = (item: PickerItem): boolean => isMandatory(item) && !isComplete(item.code);
const rowKey = (item: PickerItem): string => `${item.code}:${item.uri}`;

/**
 * Fixed under the results: the staged code ("SELECTED") or the expression being built ("BUILDING") with its note, a
 * failure or progress line, and the buttons. The text scrolls inside a footer capped at FOOTER_SHARE of the window;
 * the buttons stay in view. On a tablet the buttons sit beside the text, one row, so landscape keeps its height for the
 * cards. Nothing leaves the picker until OK has the server verify the pair.
 */
function Footer({ selection, building, message, verifying, onConfirm, onClear, onUseBuilt }: { selection: PickerItem | null; building: BuildPreview | null; message: Message; verifying: boolean; onConfirm: () => void; onClear: () => void; onUseBuilt: (item: PickerItem) => void }) {
  const { t, phone } = useUi();
  const bottom = useSafeAreaInsets().bottom;
  const { height } = useWindowDimensions();
  const shown = selection ?? (building ? building.built : null);
  const caption = selection ? "SELECTED" : "BUILDING";
  const note = !selection && building && !building.complete ? "Required axis missing" : "";
  return (
    <View testID="picker-footer" style={{ maxHeight: height * FOOTER_SHARE, flexDirection: phone ? "column" : "row", alignItems: phone ? "stretch" : "center", borderTopWidth: 2, borderTopColor: t.primary, backgroundColor: t.accent, paddingBottom: bottom }}>
      <ScrollView keyboardDismissMode="on-drag" testID="picker-footer-text" style={phone ? { flexShrink: 1 } : { flex: 1 }} contentContainerStyle={{ gap: gap.xs, paddingHorizontal: gap.md, paddingVertical: gap.sm }}>
        {shown ? (
          <View testID={selection ? "picker-selection" : "picker-building"}>
            <Text style={{ fontSize: font.caption, fontWeight: "600", letterSpacing: 1, color: t.mutedForeground }}>{caption}</Text>
            <Text style={{ fontSize: font.title, lineHeight: 22, color: t.accentForeground }}>
              <Text testID={selection ? undefined : "build-preview"} style={{ fontWeight: "700", fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace", color: t.primary }}>{shown.code}</Text> — <Text style={{ fontWeight: "700" }}>{shown.title}</Text>
            </Text>
          </View>
        ) : <Text style={{ fontSize: font.body, color: t.mutedForeground }}>No code selected</Text>}
        {note ? <Text style={{ fontSize: font.caption, fontWeight: "600", color: t.warningForeground }}>{note}</Text> : null}
        {message.text ? (message.error ? <Alert variant="destructive">{message.text}</Alert> : <Text style={{ fontSize: font.body, color: t.mutedForeground }}>{message.text}</Text>) : null}
      </ScrollView>
      <View testID="picker-footer-buttons" style={{ flexDirection: "row", flexWrap: "wrap", gap: gap.sm, paddingHorizontal: gap.md, paddingBottom: gap.sm, paddingTop: phone ? 0 : gap.sm }}>
        {!selection && building ? (
          <>
            <Button label="Use complete expression" size="sm" disabled={!building.complete} onPress={() => onUseBuilt(building.built)} />
            {building.stemAlone ? <Button label="Use stem without extensions" variant="outline" size="sm" onPress={() => onUseBuilt(building.stem)} /> : null}
          </>
        ) : (
          <>
            <Button label="OK" accessibilityLabel="Use the selected code" disabled={!selection || verifying} onPress={onConfirm} style={phone ? { flexGrow: 1 } : { minWidth: 160 }} />
            {/* Apart from OK, so a thumb aimed at OK does not land on it. Clears only the staged code; the results stay. */}
            <Button label="Clear" variant="outline" accessibilityLabel="Clear the selected code" disabled={!selection || verifying} onPress={onClear} style={{ marginLeft: gap.md, minWidth: 96 }} />
          </>
        )}
      </View>
    </View>
  );
}

/**
 * The ICD-11 condition picker of the Collect Plus build, written in React Native instead of the shared web page
 * (app/static/js/digitva_icd11_picker.js). It speaks the page's message protocol to the picker bridge, so the
 * bridge still does what it does for the page: only a (code, uri) pair that `checkDorisSelection` confirmed at the
 * current certificate revision is handed on, stale replies are dropped, and a 403 ends the edit.
 * Every reply is bounded: at most 20 terms per search, with a "refine the search" hint when WHO cut the list.
 *
 * Layout follows the web. Phone: title, search box and status stay fixed on top, results and the cards a coder opens
 * scroll under them, and the footer stays below. Tablet (width of 768 or more) with a card open: results on the left
 * (about 40 %, at least 320) and the card on the right, each scrolling by itself, the footer across the full width. `generation` changes when the host replaced the bridge: the
 * old bridge never answers what was in flight, so the picker starts over exactly as it does when `revision` moves.
 */
export function IcdPicker({ init, revision, generation, onMessage, onClose }: PickerFrameProps & { onClose: () => void; generation?: number }) {
  const { t, phone } = useUi();
  const { width } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const post = usePost(onMessage);
  const finalMode = Boolean(init.finalMode);
  const [query, setQuery] = useState((init.query ?? "").slice(0, MAX_QUERY));
  const [items, setItems] = useState<PickerItem[]>([]);
  const [status, setStatus] = useState<Message>({ text: "" });
  const [selection, setSelection] = useState<PickerItem | null>(null);
  const [footer, setFooter] = useState<Message>({ text: "" });
  const [verifying, setVerifying] = useState(false);
  const [details, setDetails] = useState<(Slot & { item: PickerItem }) | null>(null);
  const [build, setBuild] = useState<(Slot & { stem: string; preselect: string[] }) | null>(null);
  const [hierarchy, setHierarchy] = useState<(Slot & { code: string }) | null>(null);
  const [related, setRelated] = useState<(Slot & { item: PickerItem; chapter: Chapter }) | null>(null);
  const [building, setBuilding] = useState<BuildPreview | null>(null);
  // The row whose control opened the cards now shown ("Back to results" returns there); null for cards opened by a search.
  const [from, setFrom] = useState<string | null>(null);
  const queryNow = useRef(query);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const token = useRef(0);
  const opens = useRef(0);
  // The term last searched: auto-search skips it until the box drops under AUTO_SEARCH_MIN_CHARS (the app's SearchBox rule).
  const last = useRef("");
  const alive = useRef(true);
  const scroller = useRef<ScrollView>(null);
  const rowY = useRef<Record<string, number>>({});
  const accent = HEX_COLOUR.test(init.accent) ? init.accent : t.primary;

  const cancelTimer = () => { if (timer.current) clearTimeout(timer.current); };
  const slot = (scroll: boolean): Slot => ({ n: ++opens.current, scroll });
  const scrollTo = (y: number) => scroller.current?.scrollTo({ y, animated: true });
  const closePanels = () => {
    setSelection(null);
    setFooter({ text: "" });
    setDetails(null);
    setBuild(null);
    setHierarchy(null);
    setRelated(null);
    setFrom(null);
  };
  const showDetails = (item: PickerItem, scroll: boolean) => setDetails({ item, ...slot(scroll) });
  const openBuild = (stem: string, preselect: string[] = [], scroll = true) => {
    setHierarchy(null);
    setBuild({ stem, preselect, ...slot(scroll) });
  };
  // A stem that needs postcoordination opens its builder, with its details unless this is the final cause.
  const routeToBuild = (item: PickerItem, scroll = true) => {
    if (!finalMode) showDetails(item, false);
    openBuild(item.code, [], scroll);
  };
  const openHierarchy = (code: string) => {
    setBuild(null);
    setHierarchy({ code, ...slot(true) });
  };
  // A staged choice waits in the footer until OK, so the coder can read Details first. Every way to stage a code
  // ends here, so a mandatory stem never reaches OK without its builder, and an extension code alone or a category
  // with children never reaches it at all (WHO's CoDEdit and DORIS would object after processing): a category opens
  // its hierarchy to choose under it.
  const stage = (item: PickerItem) => {
    // Whatever stages a code (a row, Build, the hierarchy) hides the keyboard, so the footer shows the pick.
    Keyboard.dismiss();
    const refused = notFinal(item);
    if (refused) {
      setSelection(null);
      setFooter({ text: refused.message });
      if (refused.kind === "category") openHierarchy(refused.stem);
      return;
    }
    if (needsBuild(item)) {
      routeToBuild(item);
      return;
    }
    setSelection(item);
    setFooter({ text: "" });
    showDetails(item, false);
  };

  const search = async (raw: string) => {
    cancelTimer();
    const mine = ++token.current;
    const value = raw.trim();
    last.current = value;
    closePanels();
    setItems([]);
    if (value.length < MIN_QUERY) {
      setStatus({ text: "Type at least 2 characters." });
      return;
    }
    setStatus({ text: "Searching…" });
    try {
      let found: PickerItem[];
      let cut = false;
      if (looksCode(value)) {
        found = [((await post("codeinfo", { code: value })) as DorisCodeInfoReply).item];
      } else {
        const reply = (await post("terms", { query: value, limit: 20 })) as DorisTermsReply;
        found = reply.items;
        cut = reply.truncated;
      }
      if (mine !== token.current) return;
      setItems(found);
      setStatus({ text: cut ? "Showing the first 20 matches. Refine the search to see others." : found.length ? "Choose a result." : "No matching conditions." });
      // A first result that needs postcoordination opens its builder without a tap, and without moving the list.
      const first = found[0];
      if (first && needsBuild(first) && !notFinal(first)) routeToBuild(first, false);
    } catch (error) {
      if (mine === token.current) setStatus({ text: errorMessage(error), error: true });
    }
  };

  // Opens with the suggested text, and starts over when the certificate moved or the host replaced the bridge:
  // nothing built before is still valid, and a reply the old bridge owed will never come.
  useEffect(() => {
    if (queryNow.current.trim().length >= MIN_QUERY) void search(queryNow.current);
    else { token.current += 1; closePanels(); }
    setVerifying(false);
  }, [revision, generation]);
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; cancelTimer(); };
  }, []);

  const type = (next: string) => {
    setQuery(next);
    queryNow.current = next;
    cancelTimer();
    setSelection(null);
    setFooter({ text: "" });
    setDetails(null);
    const term = next.trim();
    if (term.length < AUTO_SEARCH_MIN_CHARS) last.current = "";
    if (term.length < MIN_QUERY) {
      token.current += 1;
      setItems([]);
      setBuild(null);
      setHierarchy(null);
      setStatus({ text: "" });
    } else if (term.length >= AUTO_SEARCH_MIN_CHARS && term !== last.current) timer.current = setTimeout(() => void search(next), AUTO_SEARCH_DELAY_MS);
  };
  const reset = () => {
    cancelTimer();
    token.current += 1;
    last.current = "";
    setQuery("");
    queryNow.current = "";
    closePanels();
    setItems([]);
    setStatus({ text: "" });
  };
  const addUncoded = () => {
    const text = query.trim();
    if (!text) setStatus({ text: "Enter the condition text first." });
    else onMessage({ t: "uncoded", text }, () => undefined);
  };

  const confirm = async () => {
    if (!selection) return;
    Keyboard.dismiss();
    setVerifying(true);
    setFooter({ text: `Verifying ${selection.code}…` });
    try {
      const verified = ((await post("selection-check", { code: selection.code, uri: selection.uri })) as DorisCodeInfoReply).item;
      if (!alive.current) return;
      if (!verified.code || !verified.uri) throw new Notice("The server did not return a verified code and URI.");
      // Last line of defence: whatever staged it, WHO's own flag for the verified code decides. The builder's own
      // output is exempt: the server flags the bare stem of "Causing condition not known" as mandatory too.
      if (needsBuild(verified) && !selection.built) {
        setSelection(null);
        setFooter({ text: `${verified.code} needs postcoordination. Complete it in the builder.` });
        routeToBuild(verified);
        return;
      }
      onMessage({ t: "select", choice: { code: verified.code, uri: verified.uri, ...(selection.causingUnknown ? { causing_condition_unknown: true } : {}) } }, () => undefined);
    } catch (error) {
      setFooter({ text: errorMessage(error), error: true });
    } finally {
      setVerifying(false);
    }
  };

  // A code WHO has no uri for (a composite, a bare code, a hierarchy node) is resolved through codeinfo before it is
  // staged, which also tells whether it is a stem that needs its builder.
  const resolveAndStage = async (code: string) => {
    setBuild(null);
    setFooter({ text: `Checking ${code} with WHO…` });
    try {
      const item = ((await post("codeinfo", { code })) as DorisCodeInfoReply).item;
      if (!item.code || !item.uri) throw new Notice(`WHO did not return ${code}.`);
      stage(item);
    } catch (error) {
      setFooter({ text: errorMessage(error), error: true });
    }
  };
  const pickRelated = (term: RelatedTerm) => {
    setRelated(null);
    if (term.requires_postcoordination || finalMode) {
      setQuery(term.code);
      queryNow.current = term.code;
      void search(term.code);
    } else if (!term.uri && isComplete(term.code)) {
      const { stem, parts } = splitExpression(term.code);
      openBuild(stem, parts);
    } else if (!term.uri) void resolveAndStage(term.code);
    else stage(term);
  };
  const openStem = (item: PickerItem) => {
    const { stem, parts } = splitExpression(item.code);
    if (!finalMode) showDetails(item, false);
    openBuild(stem, parts);
  };
  const useBuilt = (item: PickerItem) => {
    stage({ ...item, built: true });
    setBuild(null);
  };
  const useHierarchyNode = (node: DorisOption) => {
    setHierarchy(null);
    void resolveAndStage(node.code);
  };
  // Each row control remembers its row for "Back to results" before it acts.
  // A row action hides the keyboard so its result (the staged code, Build, Details) is not left under it; tapping
  // the search box brings the keyboard back.
  const fromRow = (item: PickerItem, act: () => void) => () => { Keyboard.dismiss(); setFrom(rowKey(item)); act(); };
  const back = from === null ? null : () => scrollTo(rowY.current[from] ?? 0);
  const reveal = (card: Slot) => (card.scroll ? scrollTo : null);
  // An error is an alert of its own; the plain status shares a line with "Add uncoded text".
  const statusLine = status.error ? "" : status.text;
  const twoPane = !phone && Boolean(details || build || hierarchy || related);
  // On a phone a card sits in the results scroller and scrolls into view; on a tablet it has a pane of its own.
  const place = (key: string, card: Slot, content: ReactNode) => twoPane
    ? <View key={key} style={{ gap: gap.xs }}>{content}</View>
    : <Reveal key={key} scrollTo={reveal(card)} onBack={back}>{content}</Reveal>;

  const cards = [
    details ? place(`details-${details.n}`, details, <DetailsCard item={details.item} post={post} onHierarchy={() => openHierarchy(details.item.code)} onClose={() => setDetails(null)} />) : null,
    build ? place(`build-${build.n}`, build, <BuildCard stemCode={build.stem} preselect={build.preselect} post={post} inFooter={!selection} onPreview={setBuilding} onUse={useBuilt} onCancel={() => setBuild(null)} />) : null,
    hierarchy ? place(`hierarchy-${hierarchy.n}`, hierarchy, <HierarchyCard code={hierarchy.code} post={post} onNode={(node) => setHierarchy({ ...hierarchy, code: node.code })} onUse={useHierarchyNode} onBuild={(node) => openBuild(node.code)} onClose={() => setHierarchy(null)} />) : null,
    related ? place(`related-${related.n}`, related, <RelatedCard item={related.item} chapter={related.chapter} post={post} onCode={pickRelated} onChapter={(chapter) => setRelated({ ...related, chapter, ...slot(true) })} onClose={() => setRelated(null)} />) : null,
  ];

  return (
    <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1, backgroundColor: t.background, paddingTop: insets.top, paddingLeft: insets.left, paddingRight: insets.right }} accessibilityViewIsModal>
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: gap.sm, paddingHorizontal: gap.md, paddingVertical: gap.xs, borderTopWidth: 4, borderTopColor: accent, borderBottomWidth: 1, borderBottomColor: t.border }}>
        <SectionTitle>{init.title}</SectionTitle>
        <View style={{ flexDirection: "row", gap: gap.sm }}>
          <Button label="Reset" variant="outline" size="sm" accessibilityLabel="Reset search and current selection" onPress={reset} />
          <Button label="Close" variant="outline" size="sm" accessibilityLabel="Close search" onPress={onClose} />
        </View>
      </View>
      <View testID="picker-search" style={{ gap: gap.xs, paddingHorizontal: gap.md, paddingVertical: gap.sm, borderBottomWidth: 1, borderBottomColor: t.border }}>
        <Input value={query} onChangeText={type} onSubmitEditing={() => void search(query)} returnKeyType="search" maxLength={MAX_QUERY} autoFocus autoCorrect={false} autoCapitalize="none" accessibilityLabel="Search a condition or ICD-11 code" placeholder="Search a condition or ICD-11 code" />
        {status.error ? <Alert variant="destructive">{status.text}</Alert> : null}
        {statusLine || init.allowUncoded ? (
          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: gap.sm }}>
            <Text accessibilityRole="text" accessibilityLiveRegion="polite" style={{ flex: 1, fontSize: font.body, lineHeight: 20, color: t.mutedForeground }}>{statusLine}</Text>
            {init.allowUncoded ? (
              <Pressable accessibilityRole="button" accessibilityLabel="Add uncoded text" hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }} onPress={addUncoded} style={{ minHeight: 28, justifyContent: "center" }}>
                <Text maxFontSizeMultiplier={1.3} style={{ fontSize: font.body, lineHeight: 20, color: t.primary, textDecorationLine: "underline" }}>Add uncoded text</Text>
              </Pressable>
            ) : null}
          </View>
        ) : null}
      </View>
      <View testID="picker-body" style={{ flex: 1, flexDirection: twoPane ? "row" : "column" }}>
        <ScrollView ref={scroller} testID="picker-results" style={twoPane ? { flexGrow: 0, flexShrink: 0, width: Math.max(LIST_MIN, Math.round(width * LIST_SHARE)), borderRightWidth: 1, borderRightColor: t.border } : { flex: 1 }} keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag" contentContainerStyle={{ paddingHorizontal: gap.sm, paddingVertical: gap.xs }}>
          {items.map((item) => (
            <ResultRow key={rowKey(item)} item={item} inline={!phone && !twoPane} onLayout={(event) => { rowY.current[rowKey(item)] = event.nativeEvent.layout.y; }}
              onTitle={fromRow(item, () => stage(item))} onUse={fromRow(item, () => stage(item))} onDetails={fromRow(item, () => showDetails(item, true))}
              onRelated={(chapter) => { Keyboard.dismiss(); setFrom(rowKey(item)); setRelated({ item, chapter, ...slot(true) }); }} onBuild={fromRow(item, () => openStem(item))} />
          ))}
          {twoPane ? null : cards}
        </ScrollView>
        {twoPane ? <ScrollView testID="picker-detail" style={{ flex: 1 }} keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag" contentContainerStyle={{ padding: gap.md, gap: gap.sm }}>{cards}</ScrollView> : null}
      </View>
      <Footer selection={selection} building={building} message={footer} verifying={verifying} onConfirm={() => void confirm()} onClear={() => { setSelection(null); setFooter({ text: "" }); }} onUseBuilt={useBuilt} />
    </KeyboardAvoidingView>
  );
}
