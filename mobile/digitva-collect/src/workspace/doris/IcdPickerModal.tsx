import { useEffect, useMemo, useRef } from "react";
import { Modal, View } from "react-native";

import type { JsonRequester, WorkspaceApi } from "../api";
import { isPlusVariant } from "../../appVariant";
import type { WorkspaceIdentity } from "../contracts";
import { IcdPickerFrame, type PickerFrameProps } from "./IcdPickerFrame";
import { IcdPicker } from "./picker/IcdPicker";
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

/**
 * Full-screen host for the ICD-11 picker. The Collect Plus build shows the React picker (same bridge, same messages,
 * so online and offline coding use one path); plain Collect and the browser build keep the shared web page.
 */
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
  const onMessage: PickerFrameProps["onMessage"] = (message, reply) => void bridge.handle(message, reply);

  return (
    <Modal visible transparent animationType="slide" supportedOrientations={["portrait", "landscape"]} onRequestClose={close}>
      <View style={{ flex: 1, backgroundColor: "rgba(17,24,39,0.62)" }}>
        {isPlusVariant()
          // A rebuilt bridge never answers what the old one owed, so the React picker is told to start over.
          ? <IcdPicker init={props.init} revision={props.revision} generation={props.requestGeneration ?? 0} onClose={close} onMessage={onMessage} />
          : <IcdPickerFrame init={props.init} revision={props.revision} onClose={close} onMessage={onMessage} />}
      </View>
    </Modal>
  );
}
