/**
 * Mentor view (web): per-coder progress in one district, a read-only drill-down to one coder's coded cases, and
 * feedback notes (docs/policy/mentor-view.md). The server decides every scope; this screen only shows what it gets.
 * Also exports the coder's "Feedback from mentors" panel for Home.
 */
import { useEffect, useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";

import { useAppState } from "../AppState";
import {
  createMentorNote,
  getMentorCoderCases,
  getMentorCoders,
  getMentorDistricts,
  getMyMentorFeedback,
  markMentorFeedbackRead,
  retractMentorNote,
  type ClientCsrf,
  type MentorCase,
  type MentorCoderRow,
  type MentorDistrict,
  type MentorNote,
  type MentorPeriod,
} from "../api";
import { Select } from "../ui/Select";
import { spacing, useTheme } from "../theme";
import { Button, useUiStyles } from "../ui";
import { openServerPage } from "./roleHome";
import { browserErrorText, WebShell } from "./common";

const PERIODS: { key: MentorPeriod; label: string }[] = [
  { key: "30d", label: "Last 30 days" },
  { key: "90d", label: "Last 90 days" },
  { key: "12m", label: "Last 12 months" },
  { key: "all", label: "All time" },
];

const OUTCOME_LABEL: Record<MentorCase["review_outcome"], string> = {
  not_reviewed: "Not reviewed",
  agreed: "Reviewer agreed",
  changed: "Reviewer changed",
};

export const PII_WARNING =
  "Do not enter names, places, phone numbers or anything that identifies the person who died or the family.";

function authorLine(note: MentorNote): string {
  return `${note.author_name}${note.institute_name ? `, ${note.institute_name}` : ""} - ${note.created_at.slice(0, 10)}`;
}

function CaseRow({ item, csrf, userId }: { item: MentorCase; csrf: ClientCsrf; userId: string }) {
  const styles = useUiStyles();
  const theme = useTheme();
  const [notes, setNotes] = useState(item.notes);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const add = async () => {
    setBusy(true);
    setError("");
    try {
      const note = await createMentorNote(item.va_sid, draft.trim(), csrf);
      setNotes((current) => [...current, note]);
      setDraft("");
    } catch (caught) {
      setError(browserErrorText(caught));
    } finally {
      setBusy(false);
    }
  };
  const retract = async (noteId: string) => {
    try {
      await retractMentorNote(noteId, csrf);
      setNotes((current) => current.filter((note) => note.note_id !== noteId));
    } catch (caught) {
      setError(browserErrorText(caught));
    }
  };

  return (
    <View style={styles.card}>
      <Pressable onPress={() => openServerPage(userId, `/coding/area/${encodeURIComponent(item.va_sid)}`)}>
        <Text style={styles.headline}>{item.va_sid}</Text>
      </Pressable>
      <Text style={styles.text}>{`Coded ${item.coded_at.slice(0, 10)} - ${item.final_cod} - ${OUTCOME_LABEL[item.review_outcome]}`}</Text>
      {notes.map((note) => (
        <View key={note.note_id} style={{ gap: spacing.xs }}>
          <Text style={styles.text}>{note.body}</Text>
          <Text style={styles.muted}>{authorLine(note)}</Text>
          {note.can_retract ? <Button kind="secondary" size="sm" label="Retract" onPress={() => retract(note.note_id)} /> : null}
        </View>
      ))}
      <Text style={styles.muted}>{PII_WARNING}</Text>
      <TextInput
        style={styles.input}
        value={draft}
        onChangeText={setDraft}
        multiline
        maxLength={2000}
        placeholder="Feedback for the coder on this case"
        placeholderTextColor={theme.colors.textMuted}
        accessibilityLabel={`Note on ${item.va_sid}`}
      />
      {error ? <Text role="alert" style={styles.error}>{error}</Text> : null}
      <Button size="sm" label="Add note" disabled={busy || !draft.trim()} onPress={add} />
    </View>
  );
}

function CoderCases({ district, coder, period, csrf, userId, onBack }: {
  district: string; coder: MentorCoderRow; period: MentorPeriod; csrf: ClientCsrf; userId: string; onBack: () => void;
}) {
  const styles = useUiStyles();
  const [cases, setCases] = useState<MentorCase[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async (after: string | null) => {
    setLoading(true);
    try {
      const page = await getMentorCoderCases(district, coder.coder_id as string, period, after, csrf);
      setCases((current) => (after ? [...current, ...page.cases] : page.cases));
      setNext(page.next);
    } catch (caught) {
      setError(browserErrorText(caught));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { void load(null); }, [district, coder.coder_id, period]);

  return (
    <View style={{ gap: spacing.sm }}>
      <Button kind="secondary" size="sm" label="Back to coders" onPress={onBack} />
      <Text style={styles.headline}>{`${coder.label}: coded cases`}</Text>
      {error ? <Text role="alert" style={styles.error}>{error}</Text> : null}
      {!loading && cases.length === 0 && !error ? <Text style={styles.muted}>No coded cases in this period.</Text> : null}
      {cases.map((item) => <CaseRow key={item.va_sid} item={item} csrf={csrf} userId={userId} />)}
      {next ? <Button kind="secondary" size="sm" label="Load more" disabled={loading} onPress={() => load(next)} /> : null}
    </View>
  );
}

function CoderTable({ rows, namesVisible, onOpen }: {
  rows: MentorCoderRow[]; namesVisible: boolean; onOpen: (row: MentorCoderRow) => void;
}) {
  const styles = useUiStyles();
  if (rows.length === 0) return <Text style={styles.muted}>No coders hold a coding grant in this district.</Text>;
  return (
    <View style={{ gap: spacing.sm }}>
      {!namesVisible ? <Text style={styles.muted}>Your grant in this project does not show coder names, so case lists and notes are not available.</Text> : null}
      {rows.map((row, index) => (
        <View key={row.coder_id ?? `${index}`} style={styles.card}>
          <Text style={styles.headline}>{row.label}</Text>
          <Text style={styles.text}>
            {`Ready for them ${row.ready} - Coded ${row.coded} - Reviewed, agreed ${row.reviewed_agreed} - Reviewed, changed ${row.reviewed_changed} - Not codeable ${row.not_codeable} - Recodes ${row.recodes}`}
          </Text>
          {row.last_active ? <Text style={styles.muted}>{`Last signed in ${row.last_active}`}</Text> : null}
          {row.coder_id ? <Button size="sm" label="View coded cases" onPress={() => onOpen(row)} /> : null}
        </View>
      ))}
    </View>
  );
}

export default function MentorViewScreen() {
  const styles = useUiStyles();
  const { bootstrap } = useAppState();
  const csrf = bootstrap?.csrf as ClientCsrf;
  const [districts, setDistricts] = useState<MentorDistrict[] | null>(null);
  const [district, setDistrict] = useState("");
  const [period, setPeriod] = useState<MentorPeriod>("all");
  const [table, setTable] = useState<{ names_visible: boolean; coders: MentorCoderRow[]; truncated: boolean } | null>(null);
  const [coder, setCoder] = useState<MentorCoderRow | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getMentorDistricts(csrf)
      .then((data) => {
        setDistricts(data.districts);
        if (data.districts.length > 0) setDistrict(data.districts[0].district_id);
      })
      .catch((caught) => setError(browserErrorText(caught)));
  }, [csrf]);

  useEffect(() => {
    if (!district) return;
    setTable(null);
    setCoder(null);
    getMentorCoders(district, period, csrf)
      .then(setTable)
      .catch((caught) => setError(browserErrorText(caught)));
  }, [district, period, csrf]);

  return (
    <WebShell title="Mentor view">
      {error ? <Text role="alert" style={styles.error}>{error}</Text> : null}
      {districts === null && !error ? <Text style={styles.muted}>Loading...</Text> : null}
      {districts && districts.length > 0 ? (
        <View style={{ gap: spacing.sm }}>
          <Select
            label="Project – District Office"
            placeholder="Project – District Office"
            options={districts.map((d) => ({ value: d.district_id, label: `${d.project_name} – ${d.name}` }))}
            value={district}
            onChange={setDistrict}
          />
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.xs }}>
            {PERIODS.map((p) => (
              <Button key={p.key} size="sm" kind={p.key === period ? undefined : "secondary"}
                selected={p.key === period} label={p.label} onPress={() => setPeriod(p.key)} />
            ))}
          </View>
          {coder ? (
            <CoderCases district={district} coder={coder} period={period} csrf={csrf}
              userId={bootstrap?.user.user_id ?? ""} onBack={() => setCoder(null)} />
          ) : table ? (
            <>
              <CoderTable rows={table.coders} namesVisible={table.names_visible} onOpen={setCoder} />
              {table.truncated ? <Text style={styles.muted}>Showing the first 500 coders.</Text> : null}
            </>
          ) : null}
        </View>
      ) : null}
    </WebShell>
  );
}

/** The coder's "Feedback from mentors" on Home: own notes only (the server filters), newest first, mark as read. */
export function MentorFeedbackPanel({ csrf }: { csrf: ClientCsrf }) {
  const styles = useUiStyles();
  const [notes, setNotes] = useState<MentorNote[]>([]);

  useEffect(() => {
    getMyMentorFeedback(csrf).then((data) => setNotes(data.notes)).catch(() => setNotes([]));
  }, [csrf]);

  if (notes.length === 0) return null;
  const unread = notes.filter((note) => !note.read).length;
  const markRead = async (noteId: string) => {
    try {
      await markMentorFeedbackRead(noteId, csrf);
    } catch {
      return; // the note stays unread and the button stays; nothing else to undo
    }
    setNotes((current) => current.map((note) => (note.note_id === noteId ? { ...note, read: true } : note)));
  };
  return (
    <View style={styles.card}>
      <Text style={styles.headline}>{unread ? `Feedback from mentors (${unread} unread)` : "Feedback from mentors"}</Text>
      {notes.map((note) => (
        <View key={note.note_id} style={{ gap: spacing.xs }}>
          <Text style={styles.muted}>{`${note.va_sid} - ${authorLine(note)}`}</Text>
          <Text style={styles.text}>{note.body}</Text>
          {!note.read ? <Button kind="secondary" size="sm" label="Mark as read" onPress={() => markRead(note.note_id)} /> : null}
        </View>
      ))}
    </View>
  );
}
