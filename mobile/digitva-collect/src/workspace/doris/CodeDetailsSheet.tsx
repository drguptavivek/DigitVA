import { useEffect, useState } from "react";
import { Modal, Pressable, View } from "react-native";

import { t as tr } from "../../i18n";
import { errorText } from "../../ui";
import type { WorkspaceApi } from "../api";
import type { DorisCodeInfoItem, VaDefinition, WorkspaceIdentity } from "../contracts";
import { Alert, Body, Button, Card, CardTitle, FieldHint, Muted, gap, useUi } from "./ui";

const ENTITIES: Record<string, string> = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": "\"", "&#39;": "'", "&nbsp;": " " };

/** Plain text of a stored definition: tags dropped, the common entities decoded, whitespace collapsed. Never HTML. */
export function definitionPlainText(html: string): string {
  return html.replace(/<[^>]*>/g, " ").replace(/&(amp|lt|gt|quot|#39|nbsp);/g, (entity) => ENTITIES[entity] ?? entity).replace(/\s+/g, " ").trim();
}

/**
 * ICD-11 details of one code (title, code, WHO URI, release, postcoordination) from the codeinfo endpoint, and the
 * VA cause it maps to with its definition, in a sheet over the editor. Closes on the button, an outside press or back.
 */
export function CodeDetailsSheet({ api, identity, code, onClose }: { api: WorkspaceApi; identity: WorkspaceIdentity; code: string; onClose: () => void }) {
  const { t } = useUi();
  const [item, setItem] = useState<DorisCodeInfoItem | null>(null);
  const [definition, setDefinition] = useState<VaDefinition | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    setItem(null);
    setDefinition(null);
    setError("");
    api.getDorisCodeInfo(identity.vaSid, code)
      .then((reply) => { if (live) setItem(reply.item); })
      .catch((failure) => { if (live) setError(errorText(failure)); });
    // The VA cause is extra information: a failed lookup leaves the sheet without it rather than showing an error.
    api.getVaDefinitionForIcd(code)
      .then((found) => { if (live) setDefinition(found); })
      .catch(() => { if (live) setDefinition(null); });
    return () => { live = false; };
  }, [api, code, identity.vaSid]);
  return (
    <Modal visible transparent animationType="fade" statusBarTranslucent onRequestClose={onClose}>
      <View style={{ flex: 1, justifyContent: "center", padding: gap.md }}>
        <Pressable accessibilityLabel="Close details" onPress={onClose} style={{ position: "absolute", top: 0, bottom: 0, left: 0, right: 0, backgroundColor: "rgba(17,24,39,0.62)" }} />
        <Card testID="icd-details-sheet" style={{ backgroundColor: t.popover }}>
          <CardTitle>{item?.title || "ICD-11 details"}</CardTitle>
          {item ? (
            <>
              <Body>Code: {item.code}</Body>
              <Muted>WHO URI: {item.uri}</Muted>
              {item.release ? <Muted>Release: {item.release}</Muted> : null}
              <Muted>{item.postcoordination ? "Postcoordination is available for this code." : "No postcoordination for this code."}</Muted>
            </>
          ) : null}
          {definition ? (
            <View style={{ gap: gap.xs }}>
              <Body style={{ fontWeight: "600" }}>VA cause: {definition.va_code} — {definition.title}</Body>
              {definitionPlainText(definition.definition_html) ? <Body>{definitionPlainText(definition.definition_html)}</Body> : <Muted>No definition text for this VA cause.</Muted>}
              <FieldHint testID="digitva-addition">{tr("digitvaAddition")}</FieldHint>
            </View>
          ) : null}
          {error ? <Alert variant="destructive">{error}</Alert> : null}
          {!item && !error ? <Muted>Loading…</Muted> : null}
          <Button label="Close details" variant="outline" onPress={onClose} accessibilityLabel="Close ICD-11 details" />
        </Card>
      </View>
    </Modal>
  );
}

/**
 * The VA cause a chosen ICD-11 code maps to, under the selection: "Associated VA codes: VAs-xx.xx title" and its case
 * definition behind a toggle. Nothing renders while loading or when the code has no VA cause.
 */
export function AssociatedVaCodes({ api, code }: { api: WorkspaceApi; code: string }) {
  const [definition, setDefinition] = useState<VaDefinition | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    let live = true;
    setDefinition(null);
    setOpen(false);
    api.getVaDefinitionForIcd(code)
      .then((found) => { if (live) setDefinition(found); })
      .catch(() => { if (live) setDefinition(null); });
    return () => { live = false; };
  }, [api, code]);
  if (!definition) return null;
  const text = definitionPlainText(definition.definition_html);
  return (
    <View testID="associated-va-codes" style={{ gap: gap.xs }}>
      <Body>{`Associated VA codes: ${definition.va_code} ${definition.title}`}</Body>
      {text ? <Button label={open ? "Hide case definition" : "Case definition"} variant="outline" size="sm" onPress={() => setOpen(!open)} /> : null}
      {open ? <Muted>{text}</Muted> : null}
    </View>
  );
}
