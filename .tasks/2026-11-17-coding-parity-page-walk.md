# Coding parity: page-by-page walk, web vs phone (2026-11-17)

- Status: open
- Priority: P1
- Created: 2026-11-17
- Bead: digitva-9cll.22 (children filed 2026-11-17, see below)

## Goal

Make the phone coding workspace (Collect / Collect Plus, native) show and
behave like the web coding workspace, and apply the owner's ordering and
theme decisions to both. Owner rule: `coding-parity-all-surfaces`.

## How it was found

Owner and session walked the same staging test case (NA_102308287, project
SA-NQA/DEMO) on the in-app browser (Expo web, `/app/workspace`) and on an
emulator running the release APK 0.3.23 (CI build, release cert). Every
answer matched on every page; differences are layout, missing sections and
colour.

Web and phone share `src/workspace/CaseWorkspaceScreen.tsx`; they differ in
platform files: `CategoryPanel.web.tsx` vs `CategoryPanel.tsx`,
`WorkspaceLayout.web.tsx` vs `WorkspaceLayout.tsx`, and
`media/AttachmentGallery.web.tsx` (web only). Server payload is the same
(`app/routes/api/va_case.py` ~778-889). Nothing below was fixed after the
`android-v0.3.23` tag.

## Owner decisions (2026-11-17)

- Petrol theme on both: the web coding pages move off the legacy blue.
- Question/answer grid on the phone, as the web table.
- Step 2 card order: Your Step 1 certificate -> DORIS result from Step 1 ->
  Your Step 1 assigned causes -> SmartVA Analysis.
- Final-cause card: "Use SmartVA result", then "Or search ICD-11 for your
  own code", then "Your choice: ..." (with info and remove buttons).

## Fix list

| # | Fix | Where | Evidence |
|---|---|---|---|
| 1 | Darker question text | Phone | grey label too light |
| 2 | Yes/no colours from field config (flip/info), red Yes / green No in Petrol tones | Phone | `CategoryPanel.tsx` plain text; web `ResponseValue` `CategoryPanel.web.tsx:39` |
| 3 | Previous / Next at the bottom of each category | Phone | `WorkspaceLayout.tsx:22` ignores `nextBlockedReason` |
| 4 | Symptoms on VA Interview only where the web shows it (render_mode gate) | Phone | `CategoryPanel.tsx:52`; web `:214`, `:254`; offline `localCategories.ts:430` |
| 5 | Notes button on every page | Phone | notes only after COD editor, `CaseWorkspaceScreen.tsx:551` |
| 6 | Hide "default" headings; tidy raw keys (`risk_factors`, `duration_of_illness`) | Both | web shows raw keys |
| 7 | Disease / Co-morbidity as Diagnosed / Absent / other | Phone | web `DiseaseHistory` `CategoryPanel.web.tsx:68-98` |
| 8 | Question/answer grid | Phone | web table `CategoryPanel.web.tsx:51-66` |
| 9 | Petrol theme on the coding pages | Web | `*.web.tsx` use legacy blue |
| 10 | Narration image and documents gallery with rotate | Phone | `imagenarr` not shown at all; no native gallery |
| 11 | Narrative quality score status disagrees ("0/10 Cannot Grade" web vs "-/10 Not Assessed" phone) for the same case | Both | check which is right |
| 12 | Next-blocked message ("Complete the Narrative Quality Assessment before proceeding.") | Phone | see 3 |
| 13 | On Narration, symptoms card after the narrative | Phone | web order |
| 14 | Narration audio playback via the gallery | Phone | `AttachmentMedia.native.tsx` plays only bare path values |
| 15 | AMR audio plays (today a download link) | Web | `media/path.ts:48` `browserAudioSupported` excludes amr |
| 16 | Remove literal "More information" / "Flipped" lines | Phone | `CategoryPanel.tsx:60-61` |
| 17 | DORIS Administrative Data prefilled from the interview (sex Id10019, DOB Id10021, DOD Id10023, age) | Phone | phone: "Administrative data was not supplied for this certificate." |
| 18 | Manner of death prefilled from the interview (Id10077) | Phone | web prefills |
| 19 | Step 2 card order (decision above) | Both | shared |
| 20 | Final-cause card order (decision above) | Both | shared |

Not yet compared: bottom of the phone Step 1 form (fetal/infant, pregnancy,
surgery, autopsy, Reset DORIS from interview, Process, Save Step 1, Report
not codeable), and audio with a real recording.

## Constraints

- Collect screens are frozen (`docs/design/collect-petrol-theme/README.md`);
  the coding workspace is not on the frozen list, the queue and header are.
- Offline coding (9cll.22.8) renders through the same native panel: fixes
  must work for the local category payload too.
- Policy/design baseline before implementation (CLAUDE.md); old APKs are
  unaffected by web changes; phone fixes ship in the next Collect release.
