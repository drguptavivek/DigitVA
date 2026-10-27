import { useEffect, useMemo, useRef } from "react";
import { Modal, View } from "react-native";

import type { JsonRequester, WorkspaceApi } from "../api";
import type { WorkspaceIdentity } from "../contracts";
import { IcdPickerFrame } from "./IcdPickerFrame";
import { createPickerBridge, type PickerChoice, type PickerInit } from "./pickerBridge";

export interface IcdPickerModalProps {
  init: PickerInit;
  api: WorkspaceApi;
  request: JsonRequester;
  identity: WorkspaceIdentity;
  /** Certificate revision; verified codes and in-flight page replies expire when it moves. */
  revision: number;
  /** Parent request generation also expires replies after selection or remark changes. */
  requestGeneration?: number;
  onSelect: (choice: PickerChoice) => void;
  onUncoded: (text: string) => void;
  onClose: () => void;
  onForbidden: () => void;
}

/** Full-screen host for the shared ICD-11 picker used by the web editor. */
export function IcdPickerModal(props: IcdPickerModalProps) {
  const latest = useRef(props);
  latest.current = props;
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const currentBridge = useRef<ReturnType<typeof createPickerBridge> | null>(null);
  const bridge = useMemo(() => {
    const created = createPickerBridge({
      api: props.api,
      request: props.request,
      identity: props.identity,
      revision: () => latest.current.revision,
      isActive: () => mounted.current && currentBridge.current === created,
      onForbidden: () => latest.current.onForbidden(),
      allowUncoded: () => latest.current.init.allowUncoded,
      onSelect: (choice) => latest.current.onSelect(choice),
      onUncoded: (text) => latest.current.onUncoded(text),
      onClose: () => latest.current.onClose(),
    });
    return created;
  }, [props.api, props.request, props.identity.vaSid, props.identity.mode, props.revision, props.requestGeneration]);
  currentBridge.current = bridge;
  const close = () => { bridge.dispose(); props.onClose(); };

  return (
    <Modal visible transparent animationType="slide" onRequestClose={close}>
      <View style={{ flex: 1, backgroundColor: "rgba(17,24,39,0.62)" }}>
        <IcdPickerFrame init={props.init} revision={props.revision} onClose={close} onMessage={(message, reply) => void bridge.handle(message, reply)} />
      </View>
    </Modal>
  );
}
