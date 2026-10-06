import { useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";

import { ApiError } from "../../api";
import { Button, errorText, styles } from "../../ui";
import type { JsonRequester, WorkspaceApi } from "../api";
import type { DorisTerm, WorkspaceIdentity } from "../contracts";
import {
  dorisGuidance,
  parseDorisHierarchy,
  parseDorisOptions,
  parseDorisPostcoordination,
  parseDorisRelated,
  type DorisAxis,
  type DorisHierarchy,
  type DorisOption,
  type DorisPostcoordination,
  type DorisRelated,
} from "./guidance";

interface SelectedCode {
  code: string;
  title: string;
  uri: string;
}

/** Selects only server-resolved ICD-11 values, including WHO-guided expressions. */
export function IcdSelector({
  label,
  api,
  request,
  identity,
  onSelect,
  onEdit,
  value,
  initialQuery = "",
  subtreeUris,
  onForbidden,
}: {
  label: string;
  api: WorkspaceApi;
  request: JsonRequester;
  identity: WorkspaceIdentity;
  onSelect: (choice: SelectedCode | null) => void;
  onEdit: () => void;
  value?: SelectedCode | null;
  initialQuery?: string;
  subtreeUris?: string[];
  onForbidden?: () => void;
}) {
  const [query, setQuery] = useState(initialQuery);
  const [items, setItems] = useState<DorisTerm[]>([]);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [postcoordination, setPostcoordination] = useState<DorisPostcoordination | null>(null);
  const [axisValues, setAxisValues] = useState<Record<string, DorisOption[]>>({});
  const [expanded, setExpanded] = useState<Record<string, DorisOption[]>>({});
  const [truncatedOptions, setTruncatedOptions] = useState(false);
  const [axisQueries, setAxisQueries] = useState<Record<string, string>>({});
  const [axisMatches, setAxisMatches] = useState<Record<string, DorisTerm[]>>({});
  const [extension, setExtension] = useState<DorisTerm | null>(null);
  const [hierarchy, setHierarchy] = useState<DorisHierarchy | null>(null);
  const [related, setRelated] = useState<{ chapter: string; items: DorisRelated["terms"]; composite: DorisOption | null } | null>(null);
  const [error, setError] = useState("");

  const showError = (caught: unknown) => {
    if (caught instanceof ApiError && caught.status === 403) onForbidden?.();
    else setError(errorText(caught));
  };

  const choose = async (choice: SelectedCode) => {
    setBusy(true);
    setError("");
    try {
      const checked = await api.checkDorisSelection(identity.vaSid, choice.code, choice.uri);
      setItems([]);
      setPostcoordination(null);
      setHierarchy(null);
      setRelated(null);
      onSelect({ code: checked.item.code, title: checked.item.title, uri: checked.item.uri });
      setNotice(`${checked.item.code} — ${checked.item.title}`);
    } catch (selectionError) {
      if (selectionError instanceof ApiError && selectionError.status === 403) {
        onForbidden?.();
        return;
      }
      if (selectionError instanceof ApiError && selectionError.code === "INVALID_SELECTION") {
        setError("WHO could not verify that code and URI together. Search again.");
      } else setError(errorText(selectionError));
    } finally {
      setBusy(false);
    }
  };

  const resolveAndChoose = async (choice: DorisOption) => {
    setBusy(true);
    setError("");
    try {
      const info = await api.getDorisCodeInfo(identity.vaSid, choice.code);
      if (info.item.postcoordination) {
        const term: DorisTerm = { ...info.item, matching_text: info.item.title, postcoordination_availability: 2, related_maternal: false, related_perinatal: false, has_coding_note: false };
        await openTerm(term);
      } else await choose({ ...choice, uri: info.item.uri });
    } catch (lookupError) {
      showError(lookupError);
      setBusy(false);
    }
  };

  const search = async () => {
    const valueToSearch = query.trim();
    if (valueToSearch.length < 2) {
      setNotice("Enter at least two characters.");
      return;
    }
    setBusy(true);
    setError("");
    setItems([]);
    setPostcoordination(null);
    setHierarchy(null);
    setRelated(null);
    try {
      if (/^[A-Za-z0-9.&/]+$/.test(valueToSearch) && /\d/.test(valueToSearch)) {
        try {
          const info = await api.getDorisCodeInfo(identity.vaSid, valueToSearch);
          setItems([{ ...info.item, matching_text: info.item.title, postcoordination_availability: info.item.postcoordination ? 2 : 0, related_maternal: false, related_perinatal: false, has_coding_note: false }]);
          setNotice("Choose the WHO-resolved code or expression.");
          return;
        } catch (codeError) {
          if (codeError instanceof ApiError && codeError.status === 403) throw codeError;
        }
      }
      const reply = await api.searchDorisTerms(identity.vaSid, valueToSearch, { limit: 20, ...(subtreeUris ? { subtreeUris } : {}) });
      setItems(reply.items);
      setNotice(reply.truncated ? "Refine the search to see more matches." : reply.items.length ? "Choose a WHO result." : "No matching conditions.");
    } catch (searchError) {
      showError(searchError);
    } finally {
      setBusy(false);
    }
  };

  const openTerm = async (term: DorisTerm) => {
    setBusy(true);
    setError("");
    setPostcoordination(null);
    setAxisValues({});
    setExpanded({});
    setTruncatedOptions(false);
    setAxisMatches({});
    setExtension(null);
    try {
      const [guideResult, treeResult] = await Promise.allSettled([
        term.postcoordination || term.postcoordination_availability === 2
          ? dorisGuidance(request, identity, "postcoordination", { code: term.code }, parseDorisPostcoordination)
          : Promise.resolve(null),
        dorisGuidance(request, identity, "hierarchy", { code: term.code }, parseDorisHierarchy),
      ]);
      if (guideResult.status === "rejected") {
        showError(guideResult.reason);
        return;
      }
      const guide = guideResult.value;
      if (treeResult.status === "fulfilled") setHierarchy(treeResult.value);
      else showError(treeResult.reason);
      setPostcoordination(guide);
      if (guide?.axes.some((axis) => axis.required)) setNotice("Complete the required WHO axes before selecting this condition.");
      else if (guide?.axes.length) setNotice("Review the optional WHO axes and select any that apply, or use the stem alone.");
      if (!guide?.axes.length && (!guide || !guide.truncated)) await choose(term);
    } catch (openError) {
      showError(openError);
    } finally {
      setBusy(false);
    }
  };

  const selectAxisOption = (axis: DorisAxis, option: DorisOption) => {
    setAxisValues((current) => {
      const prior = current[axis.id] ?? [];
      if (prior.some((item) => item.uri === option.uri)) return { ...current, [axis.id]: prior.filter((item) => item.uri !== option.uri) };
      if (axis.allow_multiple_values === "NotAllowed") return { ...current, [axis.id]: [option] };
      if (axis.allow_multiple_values === "AllowedExceptFromSameBlock" && option.block_uri) {
        return { ...current, [axis.id]: [...prior.filter((item) => item.block_uri !== option.block_uri), option] };
      }
      return { ...current, [axis.id]: [...prior, option] };
    });
  };

  const completeExpression = async (term: DorisTerm) => {
    setBusy(true);
    setError("");
    try {
    if (!postcoordination) {
      await choose(term);
      return;
    }
    if (postcoordination.truncated || truncatedOptions || postcoordination.axes.some((axis) => axis.truncated)) {
      setError("WHO returned an incomplete choice set. Refine the stem before selecting it.");
      return;
    }
    const missing = postcoordination.axes.find((axis) => axis.required && !(axisValues[axis.id]?.length));
    if (missing) {
      setNotice(`Choose a value for ${missing.label}.`);
      return;
    }
    const axisCodes = postcoordination.axes.flatMap((axis) => (axisValues[axis.id] ?? []).map((item) => item.code));
    const extensionCode = postcoordination.other_postcoordination ? extension?.code ?? "" : "";
    const code = `${postcoordination.stem.code}${extensionCode ? `&${extensionCode}` : ""}${axisCodes.length ? `/${axisCodes.join("/")}` : ""}`;
    const info = await api.getDorisCodeInfo(identity.vaSid, code);
    await choose({ code, title: info.item.title, uri: info.item.uri });
    } catch (expressionError) {
      showError(expressionError);
    } finally {
      setBusy(false);
    }
  };

  const expand = async (axis: DorisAxis, parent: DorisOption) => {
    const key = `${axis.id}:${parent.uri}`;
    if (expanded[key]) {
      setExpanded((current) => ({ ...current, [key]: [] }));
      return;
    }
    setBusy(true);
    setError("");
    try {
      const reply = await dorisGuidance(request, identity, "postcoordination-options", {
        stem_code: postcoordination?.stem.code ?? "",
        axis_id: axis.id,
        parent_uri: parent.uri,
      }, parseDorisOptions);
      setExpanded((current) => ({ ...current, [key]: reply.items }));
      setTruncatedOptions((current) => current || reply.truncated);
      if (reply.truncated) setNotice("This WHO option list is incomplete; choose from the returned items or refine the stem.");
    } catch (expandError) {
      showError(expandError);
    } finally {
      setBusy(false);
    }
  };

  const loadRelated = async (term: DorisTerm, chapter: "maternal" | "perinatal") => {
    setBusy(true);
    setError("");
    try {
      const reply = await dorisGuidance(request, identity, "related", { code: term.code, chapter }, parseDorisRelated);
      setRelated({ chapter, items: reply.terms, composite: reply.composite });
      if (reply.truncated) setNotice("WHO returned a bounded related list; refine the search if needed.");
    } catch (relatedError) {
      showError(relatedError);
    } finally {
      setBusy(false);
    }
  };

  const showHierarchyOption = (option: DorisOption) => (
    <Button key={`${option.code}:${option.uri}`} label={`${option.code} — ${option.title}`} kind="secondary" disabled={busy} onPress={() => void resolveAndChoose(option)} />
  );

  return (
    <View style={styles.card}>
      <Text style={styles.headline}>{label}</Text>
      {value ? (
        <View>
          <Text style={styles.text}>{value.code} — {value.title}</Text>
          <Button label="Change selection" kind="secondary" onPress={() => { onEdit(); onSelect(null); setNotice(""); }} />
        </View>
      ) : (
        <>
          <TextInput accessibilityLabel={`${label} search`} placeholder="Search WHO ICD-11 or enter a code" value={query} onChangeText={(next) => { setQuery(next); setNotice(""); setItems([]); setError(""); }} onSubmitEditing={() => void search()} style={styles.input} returnKeyType="search" />
          <Button label="Search WHO ICD-11" kind="secondary" disabled={busy} loading={busy} onPress={() => void search()} />
          {items.map((term) => (
            <View key={`${term.code}:${term.uri}`} style={styles.card}>
              <Text style={styles.text}>{term.code} — {term.title}</Text>
              {term.matching_text && term.matching_text !== term.title ? <Text style={styles.muted}>Matched: {term.matching_text}</Text> : null}
              <Button label="Inspect WHO code" kind="secondary" disabled={busy} onPress={() => void openTerm(term)} />
              {!term.postcoordination && term.postcoordination_availability !== 2 ? <Button label={`Use ${term.code}`} kind="secondary" disabled={busy} onPress={() => void choose(term)} /> : null}
              {term.related_maternal ? <Button label="Maternal related codes" kind="secondary" disabled={busy} onPress={() => void loadRelated(term, "maternal")} /> : null}
              {term.related_perinatal ? <Button label="Perinatal related codes" kind="secondary" disabled={busy} onPress={() => void loadRelated(term, "perinatal")} /> : null}
            </View>
          ))}
          {postcoordination ? (
            <View>
              <Text style={styles.headline}>WHO postcoordination for {postcoordination.stem.code}</Text>
              {postcoordination.axes.map((axis) => (
                <View key={axis.id}>
                  <Text style={styles.text}>{axis.label}{axis.required ? " (required)" : " (optional)"}</Text>
                  {axis.truncated ? <Text style={styles.error}>WHO option list is incomplete. Search a narrower stem.</Text> : null}
                  {(axisValues[axis.id] ?? []).map((item) => (
                    <Pressable key={item.uri} accessibilityRole="button" accessibilityLabel={`Remove ${axis.label} ${item.code}`} onPress={() => selectAxisOption(axis, item)}>
                      <Text style={styles.text}>Selected: {item.code} — {item.title} ×</Text>
                    </Pressable>
                  ))}
                  {axis.options.map((option) => (
                    <View key={option.uri}>
                      <Pressable accessibilityRole="button" accessibilityLabel={`Select ${axis.label} ${option.code}`} onPress={() => selectAxisOption(axis, option)}>
                        <Text style={styles.text}>{(axisValues[axis.id] ?? []).some((item) => item.uri === option.uri) ? "☑" : "☐"} {option.code} — {option.title}</Text>
                      </Pressable>
                      {option.has_children ? <Button label={`More ${axis.label}: ${option.title}`} kind="secondary" disabled={busy} onPress={() => void expand(axis, option)} /> : null}
                      {(expanded[`${axis.id}:${option.uri}`] ?? []).map((child) => (
                        <Pressable key={child.uri} accessibilityRole="button" accessibilityLabel={`Select ${axis.label} ${child.code}`} onPress={() => selectAxisOption(axis, child)}>
                          <Text style={styles.text}>　{(axisValues[axis.id] ?? []).some((item) => item.uri === child.uri) ? "☑" : "☐"} {child.code} — {child.title}</Text>
                        </Pressable>
                      ))}
                    </View>
                  ))}
                  <TextInput accessibilityLabel={`Search ${axis.label}`} placeholder={`Search within ${axis.label}`} value={axisQueries[axis.id] ?? ""} onChangeText={(value) => setAxisQueries((current) => ({ ...current, [axis.id]: value }))} style={styles.input} />
                  <Button label={`Search ${axis.label} options`} kind="secondary" disabled={busy || axis.truncated} onPress={async () => {
                    const searchValue = (axisQueries[axis.id] ?? "").trim();
                    if (searchValue.length < 2) { setNotice("Enter at least two characters for the scoped search."); return; }
                    setBusy(true);
                    try {
                      const reply = await api.searchDorisTerms(identity.vaSid, searchValue, { limit: 20, subtreeUris: axis.subtree_uris });
                      setAxisMatches((current) => ({ ...current, [axis.id]: reply.items }));
                      if (reply.truncated) setTruncatedOptions(true);
                    } catch (searchError) { showError(searchError); }
                    finally { setBusy(false); }
                  }} />
                  {(axisMatches[axis.id] ?? []).map((match) => (
                    <Pressable key={`axis:${axis.id}:${match.code}`} accessibilityRole="button" accessibilityLabel={`Select ${axis.label} ${match.code}`} onPress={() => selectAxisOption(axis, { code: match.code, title: match.title, uri: match.uri, has_children: false })}>
                      <Text style={styles.text}>{match.code} — {match.title}</Text>
                    </Pressable>
                  ))}
                </View>
              ))}
              {postcoordination.other_postcoordination ? (
                <View>
                  <Text style={styles.text}>Other postcoordination</Text>
                  <TextInput accessibilityLabel="Other postcoordination search" placeholder="Search WHO extension codes" value={extension?.matching_text ?? ""} onChangeText={(next) => {
                    setExtension(null);
                    setQuery(next);
                  }} style={styles.input} />
                  <Button label="Search extension codes" kind="secondary" disabled={busy} onPress={async () => {
                    const searchValue = query.trim();
                    if (searchValue.length < 2) { setNotice("Enter at least two characters for the extension search."); return; }
                    setBusy(true);
                    try {
                      const reply = await api.searchDorisTerms(identity.vaSid, searchValue, { limit: 20, subtreeUris: postcoordination.other_postcoordination?.subtree_uris });
                      setItems(reply.items);
                      setTruncatedOptions((current) => current || reply.truncated);
                      setNotice(reply.truncated ? "Refine the search to see more extension codes." : "Choose an extension code.");
                    } catch (searchError) { showError(searchError); }
                    finally { setBusy(false); }
                  }} />
                  {items.filter((item) => item.uri).map((item) => (
                    <Pressable key={`extension:${item.code}`} accessibilityRole="button" accessibilityLabel={`Select extension ${item.code}`} onPress={() => setExtension(item)}>
                      <Text style={styles.text}>{extension?.code === item.code ? "☑" : "☐"} {item.code} — {item.title}</Text>
                    </Pressable>
                  ))}
                </View>
              ) : null}
              <Button label="Use complete WHO expression" disabled={busy || postcoordination.truncated || truncatedOptions} loading={busy} onPress={() => void completeExpression({ code: postcoordination.stem.code, title: postcoordination.stem.title, uri: postcoordination.stem.uri, release: "", matching_text: postcoordination.stem.title, postcoordination: true, postcoordination_availability: 2, related_maternal: false, related_perinatal: false, has_coding_note: false })} />
            </View>
          ) : null}
          {hierarchy ? (
            <View>
              <Text style={styles.text}>WHO hierarchy: {hierarchy.ancestors.map((item) => item.title).join(" › ")} › {hierarchy.selected.title}</Text>
              {hierarchy.truncated ? <Text style={styles.muted}>WHO hierarchy is bounded.</Text> : null}
              {hierarchy.ancestors.map(showHierarchyOption)}
              {hierarchy.siblings.map(showHierarchyOption)}
              {hierarchy.children.map(showHierarchyOption)}
              {hierarchy.related_maternal.length ? <Text style={styles.text}>Related maternal terms</Text> : null}
              {hierarchy.related_maternal.map(showHierarchyOption)}
              {hierarchy.related_perinatal.length ? <Text style={styles.text}>Related perinatal terms</Text> : null}
              {hierarchy.related_perinatal.map(showHierarchyOption)}
            </View>
          ) : null}
          {related ? (
            <View>
              <Text style={styles.headline}>{related.chapter === "maternal" ? "Maternal" : "Perinatal"} related terms</Text>
              {related.composite ? <Button label={`Use composite ${related.composite.code}`} kind="secondary" disabled={busy} onPress={() => void resolveAndChoose(related.composite!)} /> : null}
                {related.items.map((item) => item.requires_postcoordination
                  ? <Button key={item.uri} label={`Inspect related code ${item.code}`} kind="secondary" disabled={busy} onPress={() => {
                    const term: DorisTerm = { ...item, release: "", matching_text: item.title, postcoordination: true, postcoordination_availability: 2, related_maternal: false, related_perinatal: false, has_coding_note: false };
                    void openTerm(term);
                  }} />
                  : showHierarchyOption(item))}
            </View>
          ) : null}
          {notice ? <Text style={styles.muted}>{notice}</Text> : null}
        </>
      )}
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
    </View>
  );
}
