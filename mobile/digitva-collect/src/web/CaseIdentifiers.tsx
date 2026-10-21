import { useEffect, useRef, useState } from "react";
import { Text, View } from "react-native";

import { useAppState } from "../AppState";
import { ApiError } from "../api";
import { IdentifierFields, identifierIssueText, MONOSPACE } from "../IdentifierFields";
import { t } from "../i18n";
import {
  identifierChanges, identifierFieldErrors, identifierIssues, identifierValues, identifierWarnings,
  isBadgeOnly, loadIdentifierTypes, putCaseIdentifiers,
  type CaseIdentifier, type IdentifierType,
} from "../identifiers";
import { Button, useUiStyles } from "../ui";

/**
 * A case's registration numbers on a card or the detail. Value viewers see label first and the
 * number in monospace; a missing number shows nothing on a card and "Not yet issued" on the detail.
 * Badge-only viewers (no `value` key) see "<label>: recorded" or "<label>: missing".
 */
export function IdentifierFacts({ identifiers, variant }: { identifiers: CaseIdentifier[] | undefined; variant: "card" | "detail" }) {
  const styles = useUiStyles();
  if (!identifiers?.length) return null;
  // Per entry: no `value` key is a badge ("recorded"/"missing"); a null value is a type with no number yet.
  const rows = identifiers.flatMap((entry) => {
    if (!("value" in entry)) {
      return [<Text key={entry.code} style={styles.muted} testID={`identifier-badge-${entry.code}`}>
        {t(entry.present ? "idBadgeRecorded" : "idBadgeMissing", { label: entry.label })}
      </Text>];
    }
    if (!entry.value) {
      return variant === "detail"
        ? [<Text key={entry.code} style={styles.muted} testID={`identifier-value-${entry.code}`}>{entry.label}: {t("idNotYetIssued")}</Text>]
        : [];
    }
    return [<Text key={entry.code} style={variant === "detail" ? styles.text : styles.muted} testID={`identifier-value-${entry.code}`}>
      {entry.label}: <Text style={{ fontFamily: MONOSPACE }}>{entry.value}</Text>
    </Text>];
  });
  return rows.length ? <View style={{ gap: 2 }} testID="identifier-facts">{rows}</View> : null;
}

type Editable = { death_id: string; project_id?: string; updated_at?: string | null; identifiers?: CaseIdentifier[]; can_edit_identifiers?: boolean };

/**
 * "Add registration number" on a card or the detail, only when the server's flag says this caller
 * may write this case (absent means no; the flag already folds in the closed-case rule). It opens
 * the same fields in a small panel and saves through PUT /intake/cases/<id>/identifiers.
 */
export function AddIdentifierAction({ row, onChanged }: { row: Editable; onChanged: () => void }) {
  if (row.can_edit_identifiers !== true) return null;
  return <AddIdentifierPanel row={row} onChanged={onChanged} />;
}

function AddIdentifierPanel({ row, onChanged }: { row: Editable; onChanged: () => void }) {
  const { bootstrap } = useAppState();
  const styles = useUiStyles();
  const [open, setOpen] = useState(false);
  const [types, setTypes] = useState<IdentifierType[]>([]);
  // The types load up front: without them there is nothing to add, and a failed load must say so.
  const [typesState, setTypesState] = useState<"loading" | "ready" | "error">("loading");
  const [values, setValues] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [warnings, setWarnings] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const base = useRef<Record<string, string>>({});
  const updatedAt = useRef<string | undefined>(row.updated_at ?? undefined);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  const badge = isBadgeOnly(row.identifiers);

  useEffect(() => {
    if (!bootstrap) return;
    setTypesState("loading");
    loadIdentifierTypes(row.project_id ?? "", bootstrap.csrf).then(
      (loaded) => { if (alive.current) { setTypes(loaded); setTypesState("ready"); } },
      () => { if (alive.current) setTypesState("error"); },
    );
  }, [bootstrap, row.project_id]);

  function show() {
    if (!bootstrap) return;
    const initial = badge ? {} : identifierValues(row.identifiers);
    base.current = initial;
    updatedAt.current = row.updated_at ?? undefined;
    setValues(initial);
    setErrors({});
    setWarnings({});
    setMessage("");
    setOpen(true);
  }

  function close() {
    setOpen(false);
    setWarnings({});
  }

  async function save() {
    if (!bootstrap || busy) return;
    const issues = identifierIssues(types, values);
    if (Object.keys(issues).length) {
      setErrors(Object.fromEntries(types.filter((type) => issues[type.code]).map((type) => [type.code, identifierIssueText(type, issues[type.code])])));
      return;
    }
    const changes = identifierChanges(base.current, values);
    // A badge-only viewer cannot see stored values, so never send a clear for a field they left empty.
    if (badge) for (const code of Object.keys(changes)) if (changes[code] === null) delete changes[code];
    if (!Object.keys(changes).length) {
      close();
      return;
    }
    setBusy(true);
    setErrors({});
    setMessage("");
    try {
      const reply = await putCaseIdentifiers(bootstrap.links.intakeCases, row.death_id, changes, updatedAt.current, bootstrap.csrf);
      if (!alive.current) return;
      const stamp = (reply.case as { updated_at?: unknown } | undefined)?.updated_at;
      if (typeof stamp === "string") updatedAt.current = stamp;
      base.current = { ...base.current, ...Object.fromEntries(Object.entries(changes).filter(([, v]) => v !== null)) as Record<string, string> };
      for (const [code, v] of Object.entries(changes)) if (v === null) delete base.current[code];
      onChanged();
      const found = identifierWarnings(reply);
      if (Object.keys(found).length) {
        setWarnings(found);
        setMessage(t("idSaved"));
      } else {
        close();
      }
    } catch (error) {
      if (!alive.current) return;
      if (error instanceof ApiError && error.status === 409 && error.code === "case_closed") {
        setMessage(t("idCaseClosed"));
      } else if (error instanceof ApiError && error.status === 409 && error.code === "death_stale") {
        setMessage(t("idStaleReloaded"));
        onChanged();
        close();
      } else {
        const fieldErrors = identifierFieldErrors(error);
        setErrors(fieldErrors);
        setMessage(Object.keys(fieldErrors).length ? t("serverValidation") : t("serverError"));
      }
    } finally {
      if (alive.current) setBusy(false);
    }
  }

  const warned = Object.keys(warnings).length > 0;
  if (typesState === "error") return <Text style={styles.error} accessibilityRole="alert" testID="identifier-types-error">{t("idTypesLoadFailed")}</Text>;
  if (typesState !== "ready" || types.length === 0) return null;
  return (
    <>
      {!open ? <Button size="sm" kind="secondary" label={t("idAddAction")} onPress={show} /> : null}
      {open ? (
        <View style={[styles.card, { flexBasis: "100%", minWidth: 0 }]} testID="identifier-panel">
          <IdentifierFields
            types={types}
            values={values}
            errors={errors}
            warnings={warnings}
            disabled={busy}
            onChange={(code, value) => {
              setValues((current) => ({ ...current, [code]: value }));
              setErrors((current) => ({ ...current, [code]: "" }));
            }}
            onContinue={(code) => {
              const rest = { ...warnings };
              delete rest[code];
              setWarnings(rest);
              if (!Object.keys(rest).length) close();
            }}
            onEdit={() => { setWarnings({}); setMessage(""); }}
          />
          {message ? <Text style={warned ? styles.muted : styles.error} accessibilityRole="alert">{message}</Text> : null}
          <View style={styles.row}>
            <Button size="sm" label={t("save")} loading={busy} disabled={busy || warned} onPress={() => void save()} />
            <Button size="sm" kind="secondary" label={t("cancel")} disabled={busy} onPress={close} />
          </View>
        </View>
      ) : null}
    </>
  );
}
