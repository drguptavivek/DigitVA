import { useMemo, useRef } from "react";
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
  onSelect: (choice: PickerChoice) => void;
  onUncoded: (text: string) => void;
  onClose: () => void;
  onForbidden: () => void;
}

/** Full-screen host for the shared ICD-11 picker used by the web editor. */
export function IcdPickerModal(props: IcdPickerModalProps) {
  const latest = useRef(props);
  latest.current = props;
  const bridge = useMemo(() => createPickerBridge({
    api: props.api,
    request: props.request,
    identity: props.identity,
    revision: () => latest.current.revision,
    onForbidden: () => latest.current.onForbidden(),
    allowUncoded: () => latest.current.init.allowUncoded,
    onSelect: (choice) => latest.current.onSelect(choice),
    onUncoded: (text) => latest.current.onUncoded(text),
    onClose: () => latest.current.onClose(),
  }), [props.api, props.request, props.identity.vaSid, props.identity.mode]);

  return (
    <Modal visible transparent animationType="slide" onRequestClose={props.onClose}>
      <View style={{ flex: 1, backgroundColor: "rgba(17,24,39,0.62)" }}>
        <IcdPickerFrame init={props.init} revision={props.revision} onMessage={(message, reply) => void bridge.handle(message, reply)} />
      </View>
    </Modal>
  );
}
