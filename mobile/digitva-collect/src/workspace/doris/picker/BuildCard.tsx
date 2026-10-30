import { useEffect, useState } from "react";
import { Pressable, Text, View } from "react-native";

import { Alert, Body, Button, Muted, Separator, font, gap, useUi } from "../ui";
import { parseDorisOptions, parseDorisPostcoordination, type DorisAxis, type DorisOption, type DorisPostcoordination } from "../guidance";
import { CAUSING_AXIS, buildExpression, isExtension, requiredSatisfied, toggleOption, type PickerItem, type Selection } from "./expression";
import { OptionRow } from "./OptionRow";
import { LoadView, Panel } from "./Panel";
import { ScopedSearch } from "./ScopedSearch";
import { errorMessage, Notice, PickerError, useLoad, type Post } from "./transport";

interface BuildData {
  data: DorisPostcoordination;
  selected: Selection;
  other: DorisOption | null;
}

/**
 * Loads the stem and its axes, then resolves the parts of a composite opened with `preselect`: a part that is a
 * root option is chosen directly, an X code becomes the "Other postcoordination" pick, and any other code goes on
 * the first axis that takes stem codes. A part WHO cannot resolve is left for the coder to pick by hand.
 */
async function loadBuild(post: Post, stemCode: string, preselect: string[]): Promise<BuildData> {
  const data = parseDorisPostcoordination(await post("postcoordination", { code: stemCode }));
  const selected: Selection = {};
  let other: DorisOption | null = null;
  const unresolved: string[] = [];
  for (const code of preselect) {
    const placed = data.axes.flatMap((axis) => axis.options.filter((option) => option.code === code).map((option) => ({ axis, option })));
    for (const { axis, option } of placed) selected[axis.id] = [...(selected[axis.id] ?? []), option];
    if (!placed.length) unresolved.push(code);
  }
  await Promise.all(unresolved.map(async (code) => {
    try {
      const part = ((await post("codeinfo", { code })) as { item?: PickerItem }).item;
      if (!part?.code || !part.uri) return;
      const chosen: DorisOption = { code: part.code, title: part.title, uri: part.uri, has_children: false };
      const axis = data.axes.find((candidate) => candidate.options.some((option) => option.code && !isExtension(option.code)));
      if (isExtension(chosen.code)) other = chosen;
      else if (axis && !(selected[axis.id] ?? []).some((item) => item.code === chosen.code)) selected[axis.id] = [...(selected[axis.id] ?? []), chosen];
    } catch {
      // the coder can still pick the part by hand
    }
  }));
  return { data, selected, other };
}

/** "More choices": loads the direct children of an option, and says why when it cannot. */
function MoreChoices({ onLoad }: { onLoad: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const press = async () => {
    setBusy(true);
    setProblem("");
    try {
      await onLoad();
    } catch (error) {
      setBusy(false);
      setProblem(errorMessage(error));
    }
  };
  return (
    <View style={{ gap: gap.xs }}>
      <Button label={busy ? "Loading…" : "More choices"} variant="ghost" size="sm" disabled={busy} accessibilityLabel="More choices" onPress={() => void press()} style={{ alignSelf: "flex-start" }} />
      {problem ? <Alert variant="destructive">{problem}</Alert> : null}
    </View>
  );
}

interface ListProps {
  axis: DorisAxis;
  options: DorisOption[];
  chosen: DorisOption[];
  expanded: Record<string, DorisOption[]>;
  onPick: (option: DorisOption) => void;
  onExpand: (option: DorisOption) => Promise<void>;
}

/** A long list shows this many options, then "Show all N"; options already chosen stay visible. */
const OPTION_CAP = 8;

/** The options of an axis, with loaded children indented under their parent. Uncoded folders expand but never select. */
function OptionList({ axis, options, chosen, expanded, onPick, onExpand }: ListProps) {
  const { t } = useUi();
  const [all, setAll] = useState(false);
  const usable = options.filter((option) => option.code || option.title);
  const shown = all ? usable : usable.filter((option, index) => index < OPTION_CAP || chosen.some((item) => item.code === option.code));
  return (
    <View style={{ gap: gap.xs }}>
      {shown.map((option) => {
        const children = expanded[`${axis.id}|${option.uri}`];
        const on = chosen.some((item) => item.code === option.code);
        return (
          <View key={`${option.code}:${option.uri}`} style={{ gap: gap.xs }}>
            {option.code && option.uri
              ? <OptionRow selected={on} accessibilityLabel={`${axis.label} ${option.code} ${option.title}`} onPress={() => onPick(option)}>{`${option.code} — ${option.title}`}</OptionRow>
              : <Text style={{ fontSize: font.body, lineHeight: 20, color: t.mutedForeground }}>▷ {option.title}</Text>}
            {children ? (
              <View style={{ marginLeft: gap.xl }}>
                <OptionList axis={axis} options={children} chosen={chosen} expanded={expanded} onPick={onPick} onExpand={onExpand} />
              </View>
            ) : option.has_children && option.uri ? <MoreChoices onLoad={() => onExpand(option)} /> : null}
          </View>
        );
      })}
      {shown.length < usable.length ? <Button label={`Show all ${usable.length}`} variant="ghost" size="sm" accessibilityLabel={`Show all ${usable.length} options`} onPress={() => setAll(true)} style={{ alignSelf: "flex-start" }} /> : null}
    </View>
  );
}

const multipleHint = (axis: DorisAxis): string => axis.allow_multiple_values === "AllowedExceptFromSameBlock" ? "(choose across different blocks)" : axis.allow_multiple_values === "AllowAlways" ? "(choose one or more)" : "(choose one)";

interface AxisProps {
  axis: DorisAxis;
  chosen: DorisOption[];
  expanded: Record<string, DorisOption[]>;
  unknown: boolean;
  post: Post;
  onPick: (option: DorisOption) => void;
  onExpand: (option: DorisOption) => Promise<void>;
  onUnknown: () => void;
}

function AxisSection({ axis, chosen, expanded, unknown, post, onPick, onExpand, onUnknown }: AxisProps) {
  const { t, phone } = useUi();
  const [searching, setSearching] = useState(false);
  // Optional axes fold on phones to keep the required ones in view; an axis that already holds a choice (a composite's
  // parts) starts open, and tablets always show every axis.
  const [open, setOpen] = useState(chosen.length > 0);
  // Chosen values that are not root options (preselected composite parts, deeper children) stay visible and pressable.
  const extras = chosen.filter((item) => !axis.options.some((option) => option.code === item.code) && !Object.values(expanded).some((list) => list.some((option) => option.code === item.code)));
  const foldable = phone && !axis.required;
  const showBody = !foldable || open;
  const title = (
    <>
      {axis.label} ({axis.instruction || (axis.required ? "required" : "optional")}.) <Text style={{ fontWeight: "400", color: t.mutedForeground }}>{multipleHint(axis)}</Text>
    </>
  );
  return (
    <View style={{ gap: gap.xs }} testID={`axis-${axis.id}`}>
      <Separator />
      {foldable ? (
        <Pressable accessibilityRole="button" accessibilityLabel={`${axis.label}, optional${chosen.length ? `, ${chosen.length} chosen` : ""}`} accessibilityState={{ expanded: open }} onPress={() => setOpen(!open)} style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: gap.sm, minHeight: 44 }}>
          <Text style={{ flexShrink: 1, fontSize: font.body, lineHeight: 20, fontWeight: "600", color: t.foreground }}>
            {open ? title : `${axis.label} (optional)${chosen.length ? ` · ${chosen.length} chosen` : ""}`}
          </Text>
          <Text style={{ fontSize: font.title, color: t.mutedForeground }}>{open ? "▾" : "▸"}</Text>
        </Pressable>
      ) : (
        <Text accessibilityRole="header" style={{ fontSize: font.body, lineHeight: 20, fontWeight: "600", color: t.foreground }}>{title}</Text>
      )}
      {showBody ? (
        <>
          {axis.id === CAUSING_AXIS && axis.required
            ? <OptionRow selected={unknown} accessibilityLabel="Causing condition not known" onPress={onUnknown}>Causing condition not known</OptionRow>
            : null}
          {axis.subtree_uris.length ? (
            <ScopedSearch label={axis.label} subtreeUris={axis.subtree_uris} post={post} isActive={(code) => chosen.some((item) => item.code === code)} onActive={setSearching}
              onChoose={(item) => onPick({ code: item.code, title: item.title, uri: item.uri, has_children: false, block_uri: item.uri })} />
          ) : null}
          {searching ? null : <OptionList axis={axis} options={[...axis.options, ...extras]} chosen={chosen} expanded={expanded} onPick={onPick} onExpand={onExpand} />}
        </>
      ) : null}
    </View>
  );
}

const TRUNCATED = "More WHO options exist. Refine the search if the needed choice is not shown.";

/** What the picker's footer shows while a build is open and nothing is staged (the web's "BUILDING" footer). */
export interface BuildPreview {
  stem: PickerItem;
  built: PickerItem;
  complete: boolean;
  /** WHO allows the stem alone only when no axis is required. */
  stemAlone: boolean;
}

function BuildForm({ loaded, post, inFooter, onPreview, onUse }: { loaded: BuildData; post: Post; inFooter: boolean; onPreview: (preview: BuildPreview | null) => void; onUse: (item: PickerItem) => void }) {
  const { data } = loaded;
  const stem: PickerItem = { code: data.stem.code, title: data.stem.title, uri: data.stem.uri };
  const [selected, setSelected] = useState<Selection>(loaded.selected);
  const [other, setOther] = useState<DorisOption | null>(loaded.other);
  const [expanded, setExpanded] = useState<Record<string, DorisOption[]>>({});
  const [unknown, setUnknown] = useState(false);
  const [cut, setCut] = useState(false);
  const complete = requiredSatisfied(data.axes, selected, unknown);
  const built = buildExpression(stem, data.axes, selected, other, unknown);
  const stemAlone = !data.axes.some((axis) => axis.required);

  // The live expression and its Use buttons belong to the footer, which stays on screen while the axes scroll.
  useEffect(() => {
    if (!inFooter) return undefined;
    onPreview({ stem, built, complete, stemAlone });
    return () => onPreview(null);
  }, [inFooter, built.code, built.causingUnknown, complete]);

  const pick = (axis: DorisAxis, option: DorisOption) => {
    setSelected((current) => ({ ...current, [axis.id]: toggleOption(axis, current[axis.id] ?? [], option) }));
    if (axis.id === CAUSING_AXIS) setUnknown(false);
  };
  const toggleUnknown = (axis: DorisAxis) => {
    setUnknown(!unknown);
    if (!unknown) setSelected((current) => ({ ...current, [axis.id]: [] }));
  };
  const expand = async (axis: DorisAxis, parent: DorisOption) => {
    const reply = parseDorisOptions(await post("postcoordination-options", { stem_code: stem.code, axis_id: axis.id, parent_uri: parent.uri }));
    setExpanded((current) => ({ ...current, [`${axis.id}|${parent.uri}`]: reply.items }));
    if (reply.truncated) setCut(true);
  };
  // WHO accepts an open-ended extension only when codeinfo resolves "stem&code"; not every X code fits every stem.
  const chooseExtension = async (item: PickerItem) => {
    try {
      await post("codeinfo", { code: `${stem.code}&${item.code}` });
    } catch (error) {
      throw new Notice(error instanceof PickerError && error.code === "CODE_NOT_FOUND" ? `WHO does not accept ${item.code} as an extension of ${stem.code}.` : errorMessage(error));
    }
    setOther({ code: item.code, title: item.title, uri: item.uri, has_children: false });
  };

  return (
    <View style={{ gap: gap.sm }}>
      <Body>Stem: {stem.code} — {stem.title}</Body>
      {complete ? null : <Alert variant="warning" role="none">A required axis is missing. Choose one option to complete the expression.</Alert>}
      {[...data.axes].sort((a, b) => Number(b.required) - Number(a.required)).map((axis) => (
        <AxisSection key={axis.id} axis={axis} chosen={selected[axis.id] ?? []} expanded={expanded} unknown={unknown} post={post}
          onPick={(option) => pick(axis, option)} onExpand={(parent) => expand(axis, parent)} onUnknown={() => toggleUnknown(axis)} />
      ))}
      {data.other_postcoordination ? (
        <View style={{ gap: gap.xs }} testID="axis-other">
          <Separator />
          <Text accessibilityRole="header" style={{ fontSize: font.body, fontWeight: "600" }}>Other postcoordination? (use additional code, if desired.)</Text>
          {other ? <OptionRow selected accessibilityLabel={`Remove ${other.code}`} onPress={() => setOther(null)}>{`${other.code} — ${other.title}`}</OptionRow> : null}
          <ScopedSearch label="Other postcoordination" subtreeUris={data.other_postcoordination.subtree_uris} post={post} isActive={(code) => other?.code === code} onChoose={chooseExtension} />
        </View>
      ) : null}
      {data.truncated || cut || data.axes.some((axis) => axis.truncated) ? <Alert variant="warning">{TRUNCATED}</Alert> : null}
      {inFooter ? null : (
        <>
          <Separator />
          <Muted>Complete code preview</Muted>
          <Text selectable style={{ fontSize: font.body, fontFamily: "monospace" }} testID="build-preview">{built.code}</Text>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: gap.sm }}>
            <Button label="Use complete expression" size="sm" disabled={!complete} onPress={() => onUse(built)} />
            {stemAlone ? <Button label="Use stem without extensions" variant="outline" size="sm" onPress={() => onUse(stem)} /> : null}
          </View>
        </>
      )}
    </View>
  );
}

/**
 * WHO postcoordination builder (the `postcoordination` route): required axes first, then the rest, then "Other
 * postcoordination?". With `inFooter` the expression preview and its Use buttons go to the picker's footer through
 * `onPreview` instead of the end of the card.
 */
export function BuildCard({ stemCode, preselect, post, inFooter, onPreview, onUse, onCancel }: { stemCode: string; preselect: string[]; post: Post; inFooter: boolean; onPreview: (preview: BuildPreview | null) => void; onUse: (item: PickerItem) => void; onCancel: () => void }) {
  const state = useLoad(() => loadBuild(post, stemCode, preselect), []);
  return (
    <Panel testID="picker-build" title="Build expression" closeLabel="Cancel" onClose={onCancel}>
      <LoadView state={state} loading="Loading WHO postcoordination choices…">{(loaded) => <BuildForm loaded={loaded} post={post} inFooter={inFooter} onPreview={onPreview} onUse={onUse} />}</LoadView>
    </Panel>
  );
}
