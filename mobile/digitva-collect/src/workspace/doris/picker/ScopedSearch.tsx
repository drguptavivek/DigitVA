import { useEffect, useRef, useState } from "react";
import { View } from "react-native";

import type { DorisTermsReply } from "../../contracts";
import { Alert, Input, Muted, gap } from "../ui";
import { OptionRow } from "./OptionRow";
import type { PickerItem } from "./expression";
import { errorMessage, type Post } from "./transport";

/**
 * "Search in axis" box: a debounced WHO search limited to the axis's subtrees (or to the extension chapter for
 * "Other postcoordination?"). A pick goes to `onChoose`, which may refuse it by throwing; the message shows under
 * the box. After a successful pick the box clears, as the web builder re-renders.
 */
export function ScopedSearch({ label, subtreeUris, post, isActive, onChoose, onActive }: {
  label: string;
  subtreeUris: string[];
  post: Post;
  isActive: (code: string) => boolean;
  onChoose: (item: PickerItem) => Promise<void> | void;
  /** True while matches are shown, so the axis can hide its own option list. */
  onActive?: (active: boolean) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<{ items: PickerItem[]; truncated: boolean } | null>(null);
  const [problem, setProblem] = useState("");
  const [checking, setChecking] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const token = useRef(0);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  const type = (next: string) => {
    setQuery(next);
    setProblem("");
    if (timer.current) clearTimeout(timer.current);
    const mine = ++token.current;
    const value = next.trim();
    if (value.length < 2) {
      setResults(null);
      onActive?.(false);
      return;
    }
    timer.current = setTimeout(async () => {
      try {
        const reply = await post("terms", { query: value, limit: 20, subtree_uris: subtreeUris }) as DorisTermsReply;
        if (mine !== token.current) return;
        setResults({ items: reply.items.filter((item) => item.code && item.uri), truncated: reply.truncated });
        onActive?.(true);
      } catch (error) {
        if (mine === token.current) setProblem(errorMessage(error));
      }
    }, 250);
  };

  const choose = async (item: PickerItem) => {
    setChecking(true);
    setProblem("");
    try {
      await onChoose(item);
      token.current += 1;
      setQuery("");
      setResults(null);
      onActive?.(false);
    } catch (error) {
      setProblem(errorMessage(error));
    } finally {
      setChecking(false);
    }
  };

  return (
    <View style={{ gap: gap.xs }}>
      <Input value={query} onChangeText={type} placeholder={`search in axis: ${label}`} accessibilityLabel={`search in axis: ${label}`} maxLength={80} autoCorrect={false} autoCapitalize="none" />
      {/* Above the matches: below 20 of them a refused pick looked like a tap that did nothing. */}
      {problem ? <Alert variant="destructive">{problem}</Alert> : null}
      {results ? (
        <View style={{ gap: gap.xs }}>
          {results.items.length ? results.items.map((item) => (
            <OptionRow key={`${item.code}:${item.uri}`} selected={isActive(item.code)} disabled={checking} accessibilityLabel={`${item.code} ${item.title}`} onPress={() => void choose(item)}>
              {`${item.code} — ${item.title}`}
            </OptionRow>
          )) : <Muted>No matches in this axis.</Muted>}
          {results.truncated ? <Muted>Showing the first 20 matches. Refine the search to narrow them.</Muted> : null}
        </View>
      ) : null}
    </View>
  );
}
