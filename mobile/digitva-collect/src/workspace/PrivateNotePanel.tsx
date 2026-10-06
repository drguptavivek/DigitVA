import { useCallback, useEffect, useRef, useState } from "react";
import { AppState as NativeAppState, Text, TextInput, View } from "react-native";

import { ApiError } from "../api";
import { Button, errorText, styles } from "../ui";
import type { WorkspaceApi } from "./api";
import type { NotePayload } from "./contracts";

/** Loads and saves the caller's allocation-scoped private note in memory only. */
export function PrivateNotePanel({
  identity,
  api,
  onAllocationLost,
}: {
  identity: { vaSid: string; mode: "coding" | "reviewing" };
  api: WorkspaceApi;
  onAllocationLost: () => void;
}) {
  const [noteState, setNoteState] = useState<{ api: WorkspaceApi; vaSid: string; mode: "coding" | "reviewing"; note: NotePayload; content: string } | null>(null);
  const [busy, setBusy] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const context = useRef({ api, vaSid: identity.vaSid, mode: identity.mode });
  context.current = { api, vaSid: identity.vaSid, mode: identity.mode };
  const currentNote = noteState?.api === api && noteState.vaSid === identity.vaSid && noteState.mode === identity.mode ? noteState : null;
  const content = currentNote?.content ?? "";
  const note = currentNote?.note ?? null;

  const load = useCallback(async () => {
    const id = ++generation.current;
    const current = () => generation.current === id
      && context.current.api === api
      && context.current.vaSid === identity.vaSid
      && context.current.mode === identity.mode;
    setBusy(true);
    setError("");
    setNoteState(null);
    try {
      const response = await api.getNote(identity.vaSid, identity.mode);
      if (!current()) return;
      setNoteState({ api, vaSid: identity.vaSid, mode: identity.mode, note: response, content: response.content ?? "" });
    } catch (loadError) {
      if (!current()) return;
      if (loadError instanceof ApiError && loadError.status === 403) {
        setNoteState(null);
        onAllocationLost();
      } else setError(errorText(loadError));
    } finally {
      if (current()) setBusy(false);
    }
  }, [api, identity.mode, identity.vaSid, onAllocationLost]);

  useEffect(() => {
    void load();
    return () => {
      generation.current += 1;
    };
  }, [load]);

  useEffect(() => {
    const clear = () => {
      generation.current += 1;
      setNoteState(null);
      setBusy(true);
    };
    const native = NativeAppState.addEventListener("change", (state) => {
      if (state !== "active") clear();
      else void load();
    });
    const onVisibility = () => {
      if (typeof document === "undefined") return;
      if (document.visibilityState !== "visible") clear();
      else void load();
    };
    if (typeof document !== "undefined") document.addEventListener("visibilitychange", onVisibility);
    return () => {
      native.remove();
      if (typeof document !== "undefined") document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [load]);

  const save = async () => {
    if (!content.trim()) {
      setError("Enter a note before saving.");
      return;
    }
    if (content.length > 20_000) {
      setError("Notes are limited to 20,000 characters.");
      return;
    }
    setSaving(true);
    setError("");
    const id = generation.current;
    const current = () => generation.current === id
      && context.current.api === api
      && context.current.vaSid === identity.vaSid
      && context.current.mode === identity.mode;
    try {
      const response = await api.saveNote(identity.vaSid, identity.mode, content);
      if (!current()) return;
      setNoteState({ api, vaSid: identity.vaSid, mode: identity.mode, note: response, content: response.content ?? "" });
    } catch (saveError) {
      if (!current()) return;
      if (saveError instanceof ApiError && saveError.status === 403) {
        setNoteState(null);
        onAllocationLost();
      } else setError(errorText(saveError));
    } finally {
      if (current()) setSaving(false);
    }
  };

  const updateContent = (value: string) => {
    if (!currentNote) return;
    setNoteState({ ...currentNote, content: value });
  };

  return (
    <View style={styles.card}>
      <Text accessibilityRole="header" style={styles.headline}>Private note</Text>
      {busy || (!currentNote && !error) ? <Text style={styles.muted}>Loading note…</Text> : !currentNote ? (
        <>
          <Text accessibilityRole="alert" style={styles.error}>{error}</Text>
          <Button label="Retry private note" kind="secondary" onPress={() => void load()} />
        </>
      ) : (
        <>
          <TextInput accessibilityLabel="Private note" placeholder="Private note" value={content} onChangeText={updateContent} style={styles.input} multiline maxLength={20_000} />
          {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
          <Button label="Save private note" onPress={() => void save()} loading={saving} disabled={saving} />
          {note?.updated_at ? <Text style={styles.muted}>Saved {note.updated_at}</Text> : null}
        </>
      )}
    </View>
  );
}
