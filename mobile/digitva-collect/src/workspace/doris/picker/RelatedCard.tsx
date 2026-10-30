import { Pressable, Text, View } from "react-native";

import { Alert, Muted, SectionTitle, font, gap, useUi } from "../ui";
import { parseDorisRelated, type DorisOption, type DorisRelated } from "../guidance";
import type { PickerItem } from "./expression";
import { LoadView, Panel } from "./Panel";
import { ContextBadges, type Chapter } from "./ResultRow";
import { useLoad, type Post } from "./transport";

function TermButton({ term, onPress }: { term: DorisOption; onPress: () => void }) {
  const { t } = useUi();
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={`${term.code} ${term.title}`} onPress={onPress} hitSlop={4} style={{ minHeight: 44, justifyContent: "center" }}>
      <Text style={{ fontSize: font.title, color: t.primary }}>{term.code} — {term.title}</Text>
    </Pressable>
  );
}

export type RelatedTerm = DorisOption & { requires_postcoordination?: boolean };

interface RelatedProps {
  item: PickerItem;
  onCode: (term: RelatedTerm) => void;
  onChapter: (chapter: Chapter) => void;
}

function RelatedBody({ related, item, onCode, onChapter }: RelatedProps & { related: DorisRelated }) {
  const { composite, terms } = related;
  return (
    <View style={{ gap: gap.sm }}>
      {!terms.length && !composite ? <Muted>No related terms were returned for this code.</Muted> : (
        <>
          <SectionTitle>{item.code} — {item.title}</SectionTitle>
          <ContextBadges item={item} onRelated={onChapter} />
          {composite ? <Alert variant="warning"><TermButton term={composite} onPress={() => onCode(composite)} /></Alert> : null}
          {terms.map((term) => <TermButton key={`${term.code}:${term.uri}`} term={term} onPress={() => onCode(term)} />)}
        </>
      )}
      {related.truncated ? <Muted>WHO returned a shortened list.</Muted> : null}
    </View>
  );
}

/**
 * Maternal or perinatal terms related to a result (the `related` route): the composite WHO shows first, then the
 * chapter category and its children. A composite or term goes back to the picker through `onCode`.
 */
export function RelatedCard({ chapter, post, onClose, ...rest }: RelatedProps & { chapter: Chapter; post: Post; onClose: () => void }) {
  const state = useLoad(async () => parseDorisRelated(await post("related", { code: rest.item.code, chapter })), [rest.item.code, chapter]);
  return (
    <Panel testID="picker-related" title={chapter === "maternal" ? "Pregnancy related terms" : "Perinatal related terms"} onClose={onClose}>
      <LoadView state={state} loading="Loading WHO related terms…">{(related) => <RelatedBody related={related} {...rest} />}</LoadView>
    </Panel>
  );
}
