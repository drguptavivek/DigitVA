# Examples and Host App Integration

This repository includes small examples for the three supported UI surfaces:

- `examples/react-web` renders `WhoVaForm` inside a React web app.
- `examples/plain-web` registers the framework-independent web component.
- `examples/expo` shows the minimal Expo/React Native form embedding.
- `examples/expo-demo` is a complete local Expo demo used for APK, iOS simulator, and web builds.

The examples are intentionally host-app shaped. The WHO VA runtime owns form rendering, validation, relevance, calculations, preview, and draft envelopes; the host application owns persistence, authentication, upload, encryption, routing, device services, and final submission.

## Install The Package

```bash
npm install @drguptavivek/who-2022-va
```

Install the UI peers for the surface you use:

```bash
# React web or the web component
npm install react react-dom react-native-web

# Expo / React Native
npm install react react-native react-native-svg
```

For Expo SDK 57, Expo recommends `react-native-svg` `15.15.4`:

```bash
npx expo install react-native-svg
```

## React Web

```tsx
import { WhoVaForm } from "@drguptavivek/who-2022-va/web";

export function VerbalAutopsyPage() {
  return (
    <WhoVaForm
      draftStore={secureDraftStore}
      platform={secureAttachmentAndRecordingServices}
      onDraftSaved={(draft) => console.log("saved", draft.id)}
      onComplete={(result) => {
        if (result.valid) submitVa(result.data);
      }}
    />
  );
}
```

The web form is in-memory by default: Save draft and binary capture remain disabled until the host supplies a `draftStore` and `platform` services. The checked-in web examples explicitly call `createInsecureWhoVaBrowserDefaults()` because they are prototypes; do not copy that opt-in into production VA deployments.

## Plain Web Component

```ts
import { defineWhoVaElement } from "@drguptavivek/who-2022-va/web-component";

defineWhoVaElement();

const form = document.createElement("who-va-2022-form");
form.draftStore = secureDraftStore;
form.platform = secureAttachmentAndRecordingServices;
form.addEventListener("who-va-draft-saved", (event) => console.log(event.detail.id));
form.addEventListener("who-va-complete", (event) => submitVa(event.detail.data));
document.querySelector("#form-root")?.append(form);
```

Configure `draftStore`, attachment services, and any existing `draft-id` before appending the element. Otherwise the component creates a new draft ID but keeps answers in memory and leaves Save draft and binary controls disabled.

## Expo / React Native

```tsx
import { useMemo } from "react";
import { SafeAreaView } from "react-native";
import type { WhoVaDraft, WhoVaDraftStore } from "@drguptavivek/who-2022-va";
import { WhoVaForm } from "@drguptavivek/who-2022-va/native";

export default function App() {
  const draftStore = useMemo<WhoVaDraftStore>(() => {
    const drafts = new Map<string, WhoVaDraft>();
    return {
      save(draft) {
        drafts.set(draft.id, draft);
      },
      load(id) {
        return drafts.get(id);
      }
    };
  }, []);

  return (
    <SafeAreaView style={{ flex: 1 }}>
      <WhoVaForm
        draftStore={draftStore}
        platform={{
          pickDate: async (_question, _data, currentValue) => openDatePicker(currentValue),
          captureAudio: async () => recordAudio(),
          captureImage: async () => openCamera(),
          selectImage: async () => openImageLibrary(),
          selectFile: async (_question, _data, acceptedMimeTypes) => openDocumentPicker(acceptedMimeTypes)
        }}
        onDraftSaved={(draft) => console.log("saved", draft.id)}
        onComplete={(result) => {
          if (result.valid) queueForSubmission(result.data);
        }}
      />
    </SafeAreaView>
  );
}
```

The in-memory store above is only suitable for demos. Production apps should save the full `WhoVaDraft` envelope in SQLite, AsyncStorage, MMKV, the app database, or another offline-first encrypted store. If `draftStore` is omitted, the native Save draft button is disabled because the package cannot choose a safe persistence layer for the host app.

## Demo App Builds

The full demo app lives in `examples/expo-demo`. It uses Expo Router and opens on a Home route with Start New, Continue Last, Drafts, and Completed paths so host applications can copy the basic interview lifecycle shape.

Routes:

- `/` shows the Home screen.
- `/start` starts a new interview.
- `/continue` resumes the most recent saved draft, and `/continue?draftId=...` resumes a selected draft.
- `/drafts` lists saved local drafts.
- `/completed` lists validated submissions completed during the demo session.

```bash
pnpm --dir examples/expo-demo build:web
cd examples/expo-demo/android && ./gradlew assembleRelease
cd ../ios && pod install
xcodebuild -workspace WHOVA2022Demo.xcworkspace \
  -scheme WHOVA2022Demo \
  -configuration Release \
  -sdk iphonesimulator \
  -destination 'generic/platform=iOS Simulator' \
  CODE_SIGNING_ALLOWED=NO \
  build
```

The current local build artifacts are written under `examples/expo-demo/artifacts/`:

- `who-va-2022-demo-android-release.apk`
- `who-va-2022-demo-ios-simulator.app.zip`
- `who-va-2022-demo-expo-web.zip`

## Production Checklist

- Provide a secure `draftStore`; do not rely on demo memory storage.
- Implement native date, audio, image, and file services through `platform`.
- Upload attachment references by streaming the stored file/blob; do not convert large files to base64.
- Submit only after `onComplete` returns a valid result, or call `validate()` from the headless API before upload.
- Treat `draftId` as an opaque identifier that can be resumed by the host application.
