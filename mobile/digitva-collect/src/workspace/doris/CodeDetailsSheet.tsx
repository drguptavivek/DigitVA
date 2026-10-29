import { useEffect, useState } from "react";
import { Modal, Pressable, View, type StyleProp, type ViewStyle } from "react-native";

import { t as tr } from "../../i18n";
import { errorText } from "../../ui";
import type { WorkspaceApi } from "../api";
import type { DorisCodeInfoItem, VaDefinition, WorkspaceIdentity } from "../contracts";
import { Alert, Body, Button, Card, CardTitle, FieldHint, Muted, gap, uiRadius, useUi } from "./ui";

const ENTITIES: Record<string, string> = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": "\"", "&#39;": "'", "&nbsp;": " " };
const vaDefinitionCache = new WeakMap<WorkspaceApi, Map<string, Promise<VaDefinition | null>>>();

function getVaDefinition(api: WorkspaceApi, code: string): Promise<VaDefinition | null> {
  let byCode = vaDefinitionCache.get(api);
  if (!byCode) vaDefinitionCache.set(api, byCode = new Map());
  let request = byCode.get(code);
  if (!request) {
    request = Promise.resolve().then(() => api.getVaDefinitionForIcd(code)).catch(() => {
      if (byCode?.get(code) === request) byCode.delete(code);
      return null;
    });
    byCode.set(code, request);
  }
  return request;
}

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
    getVaDefinition(api, code)
      .then((found) => { if (live) setDefinition(found); });
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
 * The VA cause a chosen ICD-11 code maps to: one banner per cause. The chosen cause also shows its plain-text
 * definition; the Step 1 DORIS card shows the label alone. Nothing renders while loading or when there is no VA cause.
 */
export function AssociatedVaCodes({ api, code, showDefinition = false, attribution = false, style }: { api: WorkspaceApi; code: string; showDefinition?: boolean; attribution?: boolean; style?: StyleProp<ViewStyle> }) {
  const { t } = useUi();
  const [loaded, setLoaded] = useState<{ api: WorkspaceApi; code: string; definition: VaDefinition | null } | null>(null);
  useEffect(() => {
    let live = true;
    getVaDefinition(api, code)
      .then((found) => { if (live) setLoaded({ api, code, definition: found }); });
    return () => { live = false; };
  }, [api, code]);
  const definition = loaded?.api === api && loaded.code === code ? loaded.definition : null;
  if (!definition) return null;
  const text = definitionPlainText(definition.definition_html);
  return (
    <View testID={showDefinition ? "va-definition-note" : "associated-va-codes"} style={[{ gap: gap.xs, backgroundColor: t.warning, borderColor: t.warningBorder, borderWidth: 1, borderLeftWidth: 4, borderRadius: uiRadius.md, paddingHorizontal: gap.md, paddingVertical: gap.sm }, style]}>
      <Body style={{ color: t.warningForeground, fontWeight: "600" }}>{`Associated VA codes: ${definition.va_code} ${definition.title}`}</Body>
      {showDefinition ? <Body style={{ color: t.warningForeground, fontWeight: "600" }}>Case definition</Body> : null}
      {showDefinition ? (text ? <Body style={{ color: t.warningForeground }}>{text}</Body> : <Muted>No definition text for this VA cause.</Muted>) : null}
      {showDefinition && attribution ? <FieldHint testID="digitva-addition">{tr("digitvaAddition")}</FieldHint> : null}
    </View>
  );
}
