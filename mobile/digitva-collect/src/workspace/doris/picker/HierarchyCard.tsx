import { Pressable, Text, View } from "react-native";

import { Button, Label, Muted, Body, font, gap, useUi } from "../ui";
import { parseDorisHierarchy, type DorisHierarchy, type DorisOption } from "../guidance";
import { LoadView, Panel } from "./Panel";
import { isExtension } from "./expression";
import { useLoad, type Post } from "./transport";

function Nodes({ title, nodes, onNode }: { title: string; nodes: DorisOption[]; onNode: (node: DorisOption) => void }) {
  const { t } = useUi();
  return (
    <View style={{ gap: gap.xs }}>
      <Label>{title}</Label>
      {nodes.map((node) => node.code ? (
        <Pressable key={`${node.code}:${node.uri}`} accessibilityRole="button" accessibilityLabel={`${node.code} ${node.title}`} onPress={() => onNode(node)} hitSlop={4} style={{ minHeight: 44, justifyContent: "center" }}>
          <Text style={{ fontSize: font.title, color: t.primary }}>{node.code} — {node.title}</Text>
        </Pressable>
      ) : <Muted key={`${node.uri}:${node.title}`}>▷ {node.title}</Muted>)}
    </View>
  );
}

function HierarchyBody({ tree, onNode, onUse, onBuild }: { tree: DorisHierarchy; onNode: (node: DorisOption) => void; onUse: (selected: DorisOption) => void; onBuild: (selected: DorisOption) => void }) {
  const { selected } = tree;
  // Only a final code is offered: a node with children is drilled into (tap a child), an extension code is added through + Build.
  const usable = Boolean(selected.code && selected.uri) && !tree.children.length && !isExtension(selected.code);
  const context = [["Maternal context", tree.related_maternal], ["Perinatal context", tree.related_perinatal]] as const;
  return (
    <View style={{ gap: gap.sm }}>
      <Body>Selected: {selected.code}{selected.title ? ` — ${selected.title}` : ""}</Body>
      {tree.ancestors.length ? <Nodes title="Ancestor path" nodes={tree.ancestors} onNode={onNode} /> : null}
      {tree.siblings.length ? <Nodes title="Siblings" nodes={tree.siblings} onNode={onNode} /> : null}
      {tree.children.length ? <Nodes title="Children" nodes={tree.children} onNode={onNode} /> : null}
      {context.map(([title, nodes]) => nodes.length ? <Muted key={title}>{title}: {nodes.map((node) => node.title).join("; ")}</Muted> : null)}
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: gap.sm }}>
        <Button label="Use this code" size="sm" disabled={!usable} onPress={() => onUse(selected)} />
        {usable ? <Button label="Build expression for this stem" variant="outline" size="sm" onPress={() => onBuild(selected)} /> : null}
      </View>
      {tree.truncated ? <Muted>Some hierarchy choices were omitted; refine the code if needed.</Muted> : null}
    </View>
  );
}

/** Ancestors, siblings and children of a code (the `hierarchy` route); a node opens its own hierarchy, so a category is drilled into, never used. */
export function HierarchyCard({ code, post, onNode, onUse, onBuild, onClose }: { code: string; post: Post; onNode: (node: DorisOption) => void; onUse: (selected: DorisOption) => void; onBuild: (selected: DorisOption) => void; onClose: () => void }) {
  const state = useLoad(async () => parseDorisHierarchy(await post("hierarchy", { code })), [code]);
  return (
    <Panel testID="picker-hierarchy" title="See in hierarchy" onClose={onClose}>
      <LoadView state={state} loading="Loading the WHO hierarchy…">{(tree) => <HierarchyBody tree={tree} onNode={onNode} onUse={onUse} onBuild={onBuild} />}</LoadView>
    </Panel>
  );
}
