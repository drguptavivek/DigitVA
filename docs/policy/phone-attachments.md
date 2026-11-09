---
title: Phone Attachments (audio, photographs, documents)
doc_type: policy
status: active
owner: engineering
last_updated: 2026-11-09
---

# Phone Attachments

Owner, 2026-10-22 and 2026-10-23 field test (`digitva-jkvl`): the phone app
records the narrative audio (`Id10476_audio`), photographs the written
narrative and the other image questions, and attaches a medical-certificate PDF
(`custom_medical_certificate_upload`). Before this, those controls were
disabled on the phone ("capture it in the ODK app"). The web form keeps its own
browser buffer ([Web Intake Policy](web-intake.md), "Attachments"); this page
is the phone's side. Server caps and accepted types are not restated here:
[ODK Attachment Intake Limits](odk-attachment-intake-limits.md) and
`app/services/web_intake_attachment_service.py` own them.

## Decisions

1. **What the phone captures.** Audio for `audio` questions; a camera photo or
   a gallery image for `image` questions; a JPEG, PNG or PDF from the document
   picker for `file` questions (`image-or-pdf`). Nothing else.
2. **Limits (checked on the phone before anything is stored; the server checks
   again and is the boundary).**
   - Audio: 30 minutes and 25 MB at most (the web recorder's limits). The
     recorder stops by itself at 30 minutes and keeps what it has. It records
     mono AAC (`.m4a`) at a voice bitrate, about 0.25 MB a minute, so the
     duration limit is the binding one. The server accepts `m4a` and
     re-encodes audio to its canonical format.
   - The recorder can be paused and resumed; one take is one file. Only
     recorded time counts toward the 30 minutes (a pause never uses it up), the
     control shows the elapsed and the remaining time, and the take stops by
     itself when the recorded time reaches the limit. While a take is open the
     audio mode is "recording, plays in silent mode"; when it is saved or
     cancelled the mode returns to playback (`allowsRecording: false`, still
     plays in silent mode) so a saved take can be heard with the phone on
     silent. **No recording in the background:** when the app leaves the
     foreground (background, a phone call) the take is paused, kept, and stays
     paused until the interviewer resumes, saves or cancels it. The web form
     records as before (no pause).
   - Images: the vendor package's policy (`WHO_VA_ATTACHMENT_POLICY.image`): at
     most 10 MB and 16 megapixels in, re-encoded to a JPEG of at most 2048 px
     and 2 MB out (a camera frame above 16 megapixels is scaled down first, so a 50 MP photograph is not refused). EXIF and every other metadata block are dropped by the
     re-encode (`exif: false` on the picker as well). A file that is not a
     real JPEG or PNG is refused by its leading bytes, never its name.
   - PDF: at most 5 MB, must start `%PDF-`; kept as it is (`serverSideValidationRequired`).
   - At most one file per question, and the server's per-draft cap applies.
3. **Storage: inside the interviewer's encrypted database.** A file is a BLOB
   row in the SQLCipher store (`attachments` table, `src/attachmentStore.ts`),
   keyed with the same data key as the answers. So it is encrypted at rest
   exactly as the answers are, is deleted with its draft,
   and is wiped with the store (revocation with nothing unsent). Per-file encryption on top of that is not available (the
   installed libraries have digests only) and would add nothing: the key is the
   store's key.
   - **Plain-text windows, all in app-private storage and never in a shared,
     gallery or Downloads folder.** The recorder, the camera, the picker and the
     JPEG re-encode each write one temporary file in the app's private cache.
     It is read into the store and deleted at once, whether the capture worked
     or not. Playback and preview write one temporary copy of a stored file to
     a private `va-media` cache folder and delete it when the control is done
     with it. That folder, and the fixed cache folders the picker, image
     manipulator, document picker and recorder libraries write to
     (`ImagePicker`, `ImageManipulator`, `DocumentPicker`, `Audio`; these
     libraries accept no output location), are emptied when the store locks,
     when it is deleted, and at start-up (`wipeMediaCache`). A failed
     pre-scale, recorder stop or cancel deletes its own plain file at once. Only
     paths that resolve (decoded, `.`/`..` collapsed) inside the app cache are
     ever deleted; anything else is left alone. Operating-system backups are off (`allowBackup: false`), so none
     of this leaves the phone. (Clarified 2026-10-27, `digitva-5bzf`: this is
     the OS backup. A Collect Plus standalone user may make a passphrase-encrypted
     backup that includes attachments, see `field-data-collection.md` Path C
     "Export and backup".)
   - The answer holds `{ id, uri: "who-va-attachment:<uuid>", name, mimeType,
     size, ... }` exactly as the web engine writes it. The id is the UUID the
     server uses as `client_attachment_id`. A file path is never in an answer.
4. **Upload: the existing intake path, before the interview is sent.** On
   Send, for a completed interview with files: (a) get the server draft of the
   case (`POST /api/v1/intake/drafts`, which returns the caller's own open
   draft); (b) `PUT /api/v1/intake/drafts/<draft_id>/attachments/<id>` for each
   file the sent answers reference that the server has not confirmed (raw body,
   `Content-Length`, `X-Content-SHA256`; the id makes a retry idempotent);
   (c) only when every file is confirmed, `POST /api/v1/intake/submissions`.
   An interview with a missing file is never submitted (owner decision in
   `digitva-jkvl`); the server also refuses it (`attachments_pending`), and then
   the phone marks the files unconfirmed and sends them again.
   - A timeout, network error, 5xx or 429 keeps the file and retries on the
     next Send. So does a 400 `checksum_mismatch` or `invalid_request` (a
     truncated transfer) and a 413 without the server's `payload_too_large`
     code (a proxy's limit). The server's own 413 `payload_too_large`, a 415, a
     422 and any other 400 can never succeed: the file is held as
     needing attention with its Ref line; the interviewer replaces or deletes
     it by reopening the interview. A 422 `attachment_limit` is not a fault in
     the file: the interview is held and the reason shown on the interview,
     the file carries no refusal, and the next Send tries it again. A 404 or 409 (the draft is gone or closed)
     is held as needing attention and the interview is not sent.
   - Resumable upload is not built: a file is one PUT (audio is a few MB at
     the limits above). Chunked upload waits for the server side
     (`digitva-jkvl`).
   - **Direct-start interviews (no case)** use an attachment draft: (a)
     `POST /api/v1/intake/drafts` with `project_id`, `site_id`, `org_unit_id`
     and the interview's `client_draft_id` (no `death_id`; a repeat returns
     the same draft); (b) PUT the files to that draft; (c) `POST
     /intake/submissions` with the same `client_draft_id`, which completes
     that draft (owner, project, site and unit must match, else 409) rather
     than creating another. A 409 at step (a) (another interviewer's id, an id
     already uploaded, another project, site or unit) holds the interview as
     needing attention with the server's code on its Ref line; nothing is sent. Server: `docs/current-state/device-collection-api.md`,
     "Direct start with attachments". An attachment draft never submitted
     stays an ordinary open draft under the existing rules. The phone offers
     the attachment controls on every interview, direct starts included.
5. **Unsent work.** `src/unsentWork.ts`: each file of a completed interview
   that the server has not confirmed is unsent work listed on its own (kind
   `attachment`, ready to send); one held for needing attention shows in the
   attention list with its Ref line (status, code, route; never a name or
   content). Files of an interview still being filled in are in progress, like
   the interview. The unsent count (Home, the Sync badge) counts interviews and
   other records, not files: an interview with two photos is "1 ready to send"
   with a note that 2 attached files are also waiting (`unsentFiles`;
   digitva-7amd.15, owner acceptance 2026-10-29).
6. **Consent refusal.** A refusal strips the covered answers from the draft
   (`stripDraftCovered`); that now also deletes the files of those questions
   from the store (one helper, `deleteCoveredAttachments`, used by the
   refusal, by the form when it opens a draft holding covered answers, and by
   sync before it sends an interview under a refusal, own or inherited).
   Upload sends only files the sent answers still reference, so a covered file
   is never uploaded even if a copy lingered. Files no answer references
   (replaced or abandoned takes) are deleted when the interview is completed
   and after a send that left the draft in place.
7. **Permissions.** `CAMERA` and `RECORD_AUDIO` are declared; storage
   permissions stay blocked. The microphone is asked for only when the
   interviewer taps Record, and the camera only when they take a photograph,
   each after a plain explanation of why; if it was
   refused for good, the explanation offers a link to the app's settings. The
   gallery uses the system photo picker on Android 13 and later, with no
   permission. Owner decision: Android 12 and older (API 32) may request
   `READ_EXTERNAL_STORAGE` to choose from the gallery; it is declared with
   `maxSdkVersion="32"` (`plugins/with-android-legacy-gallery.js`), images
   only, and asked for at the point of use after a plain explanation, with the
   settings link when refused for good. `WRITE_EXTERNAL_STORAGE` stays
   blocked; the camera remains another way to attach a photograph.
8. **Wipe.** Deleting the draft, sign-out, revocation and the PIN wipe all
   remove the files with the store. The media cache folder is emptied with
   them. Files are never copied to another account's store.

9. **Document photos: scanner, blur check and full-screen view** (owner,
   2026-11-06, `digitva-lq5m`).
   - **Scan document.** On the document questions (`imagenarr`, `md_im1`..,
     `ds_im1`.., and the image-or-PDF `custom_medical_certificate_upload`) the
     first button is "Scan document": the phone's own scanner finds the page's
     edges, crops it and straightens it (perspective correction), one page per
     question. Camera and Gallery / Choose file stay as the other buttons; every
     other image question keeps Camera first. iOS uses VisionKit; Android uses
     the ML Kit document scanner, which needs Google Play services and fetches
     its scanner module on first use. Where there is no scanner (no Play
     services, the module not yet fetched, a build without it, the web form) or
     the scanner fails, the plain camera opens instead; a cancel is a cancel.
   - **Same path as a photo.** The scanned page comes back to the app as
     JPEG bytes, is written to the app's private cache (never the iOS
     Documents folder the plugin's own file mode uses) and then goes through
     the existing pre-scale and `processImage` limits, re-encode and encrypted
     store unchanged (decisions 2 and 3). Its plain file is deleted once it is
     stored, like a camera frame; the `va-media` folder and ML Kit's
     `mlkit_docscan_ui_client` cache folder are in the sweep (`wipeMediaCache`).
   - **Blur check.** After a camera photo, a scan, a gallery image or an image
     file is picked, and before it is processed, the phone scores its sharpness
     (variance of the Laplacian of a grey copy about 512 px wide; the copy is
     deleted at once). Below the threshold the control says "This photo looks
     blurry. Retake?" with Retake and Keep. The photo is already saved: the
     warning never blocks saving, Keep keeps it, Retake opens the same source
     again and replaces it. A failed check counts as sharp. The threshold is a
     first guess to be calibrated on real phones.
   - **On the phone only.** The scanner, the edge correction and the blur
     check run on the phone; no image, score or page leaves it for them.
   - **Full-screen view.** Tapping a stored photo opens it full screen: pinch
     to zoom (1x to 5x), pan, double-tap to zoom or fit, rotate, close. Rotation
     and zoom are view-only; the stored image never changes. The viewer shows
     the control's short-lived preview copy (decision 3). The hide, zoom-in and
     zoom-out buttons beside the preview are gone.
   - **Permissions.** On iOS the scanner asks for the camera after the same
     explanation as the camera button. The Android ML Kit scanner runs in Play
     services' own screen and needs no camera permission from the app.

- Web interview (2026-11-07): "Take photo" is only `<input type="file" accept="image/jpeg,image/png" capture="environment">` (the camera on phones, a file picker on desktop); there is no live `getUserMedia` camera. The photo goes through the usual sharpness and size processing.

- Files the server already holds (`digitva-n3ec`): `GET /api/v1/intake/drafts/<id>` carries `server_attachments`, the ids of the draft's stored files. A draft imported from the server keeps the list; an attachment question whose answer references one of them, with no bytes on the phone, shows "Saved on server" instead of a load failure, counts as answered, and is not sent again (the upload step sends only files the phone holds). Replace makes a new local file. There is no re-download of the bytes to the phone.

## Not decided here

- Re-recording replaces the saved file once the new one is saved; delete
  removes it.
- Chunked, resumable upload and server re-encode of images: `digitva-jkvl`.
