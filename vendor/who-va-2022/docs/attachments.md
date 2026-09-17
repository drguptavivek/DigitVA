# Attachment processing

Attachment selection is fail-closed. A file chooser's extension and reported MIME type are only hints; neither enters a draft as evidence that the file is safe.

## Shared policy

`WHO_VA_ATTACHMENT_POLICY` is the single runtime policy used by web and native adapters.

| Attachment | Input                                                                         | Processing                                                                                                                                                                     | Stored output                         |
| ---------- | ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------- |
| Image      | JPEG or PNG, at most 10 MB, at most 16 megapixels and 8,192 px on either edge | Verify signature and dimensions, decode, correct browser orientation, resize to a 2,048 px longest edge, add a white background, and retry JPEG encoding at decreasing quality | One UUID-named JPEG of at most 2 MB   |
| PDF        | PDF file, at most 5 MB                                                        | No page parsing or rasterisation is performed in the app. The original file is retained for upload and marked for server-side validation.                                      | One UUID-named retained PDF reference |

SVG, GIF, HEIC, WebP, renamed executables, renamed PDFs, malformed images, zero-sized images, and files outside the policy are rejected. They can be added later only with an explicit decoder, canonical output format, and tests.

## Web lifecycle

`@drguptavivek/who-2022-va/web` provides the complete browser implementation:

1. The picker accepts only JPEG/PNG for images and PDF for documents.
2. `processWebImageAttachment()` reads a bounded header, verifies the real signature and dimensions, and enforces dimension limits before browser decoding.
3. Canvas creates a new JPEG rather than preserving the selected file structure, metadata, or filename.
4. `storeWebPdfAttachment()` checks the selected PDF size and signature, stores the original PDF, and marks the answer as `serverSideValidationRequired`.
5. Generated image binaries and retained PDFs are stored in IndexedDB by `createIndexedDbWebAttachmentStore()`.
6. The answer and local-storage draft contain only `who-va-attachment:` UUID references and metadata.
7. Preview URLs are temporary `blob:` URLs and are revoked when no longer used.

Browser audio recording uses an injected binary store. `WHO_VA_WEB_AUDIO_POLICY` limits a recording to 30 minutes and 25 MB of encoded chunks; the recorder requests one-second chunks so it can stop and discard the recording as soon as the byte ceiling is exceeded.

If IndexedDB, decoding, or storage fails, the control shows a realtime error and does not set an answer.

## Expo and React Native lifecycle

The native entry point exports `processNativeImageAttachment()`. It applies the shared byte, signature, dimension, resizing, output-size, UUID, and processed-marker contract while the host supplies device operations:

```ts
import { processNativeImageAttachment } from "@drguptavivek/who-2022-va/native";

const platform = {
  selectImage: async () => {
    const asset = await pickFromImageLibrary();
    return { uri: asset.uri, name: asset.fileName ?? "selected-image" };
  },
  processImage: async (selection) =>
    processNativeImageAttachment(selection, {
      getSize: appFiles.getSize,
      read: appFiles.readBytes,
      encodeJpeg: async (uri, options) => {
        // Use expo-image-manipulator here. Return its temporary JPEG URI.
        return manipulateToJpeg(uri, options);
      },
      persist: appFiles.copyIntoEncryptedAttachmentStore,
      remove: appFiles.removeTemporaryFile
    })
};
```

`encodeJpeg` is the Expo seam for `expo-image-manipulator`; `persist` must move or copy the verified result from cache into application-controlled durable storage. The reusable image control rejects an unprocessed picker URI if `processImage` is absent.

There is no in-app PDF processing path. Expo and React Native hosts should copy an accepted PDF into application-controlled durable storage, return a retained PDF reference, and leave PDF content validation, page counting, conversion, and malware scanning to the receiving service.

## Server boundary

Frontend canonicalisation protects image drafts and gives immediate feedback, but is not a server security boundary. On synchronization, the receiving service must repeat size and content validation, validate retained PDFs, count pages if needed, scan uploads, generate its own storage keys, store files outside an executable webroot, and serve them with authoritative MIME types and `X-Content-Type-Options: nosniff`.
