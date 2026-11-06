---
title: How-Do-I Corpus - Mobile App (DigitVA Collect and Collect Plus)
doc_type: help-corpus
status: draft
owner: engineering
last_updated: 2026-11-06
---

# How-Do-I Corpus - Mobile App

The DigitVA Collect and Collect Plus Android apps: install, enrolment and
sign-in, PIN and locking, offline use, sending work, the phone clock,
languages, settings and recovery from common errors. Format and truth rules:
`docs/policy/help-chatbot.md` ("How-Do-I corpus"). Labels are copied from
`mobile/digitva-collect/src/strings/en.json` and `theme-en.json`.

Phone bottom bar: **Home**, **Interviews**, **Register** (only for accounts
that may register deaths) and **Sync**. The account menu (your picture or
initials, top right) holds **Settings**, **Help**, **Language**, **Lock now**,
**Switch profile**, **Sign out** and the app version. The phone app is for
collection only; coding and review are done in the web app.

## Install and enrol

### How do I install the DigitVA app on my phone?

- id: hdi-mobile-001
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. Open the Help guide "Get the Mobile App" in the web app, or ask your supervisor for the approved download link.
  2. Download the DigitVA Collect APK (the page shows its version and size).
  3. Open the downloaded file and allow your phone to install it if it asks.
  4. Open DigitVA and enrol the phone (see the enrolment entry).
- notes: Install only from the link your organisation gave you. If the page says "The Android APK has not been published for this environment yet", ask your administrator for the approved release link and use the browser application meanwhile. If the phone says the app "isn't compatible", it runs 32-bit Android: use the "32-bit DigitVA Collect" download shown on the same page. Collect Plus needs a 64-bit phone.
- sources: mobile-app; app/templates/help/pages/mobile-app.html; docs/policy/mobile-sign-in.md; docs/current-state/android-release-builds.md
- checked: 2026-11-06

### What is the difference between DigitVA Collect and DigitVA Collect Plus?

- id: hdi-mobile-002
- roles: interviewer
- surfaces: android
- steps:
  1. Use **Collect** for interviews with the server.
  2. Use **Collect Plus** if you also need ICD-11, DORIS and SmartVA on the phone without internet, or the standalone mode.
- notes: The Help page says: Collect supports interviews and coding with the server; Collect Plus also includes ICD-11, DORIS and SmartVA for coding on the phone without internet. Both are installed as separate apps. Collect Plus needs a 64-bit phone.
- sources: mobile-app; app/templates/help/pages/mobile-app.html; docs/current-state/expo-client.md ("Collect Plus")
- checked: 2026-11-06

### How do I enrol the app with my QR code for the first time?

- id: hdi-mobile-003
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. Open the app and choose **Scan your enrolment QR** ("From your supervisor or the welcome email").
  2. Show the QR on another screen (a computer or a second phone); the phone being enrolled cannot scan its own screen. Allow the camera when asked (**Allow camera to scan the QR code**).
  3. Check the server and project shown under "Code accepted" ("Check the server before you enrol."), then tap **Enrol on this server**.
  4. Sign in with your own email or mobile number and password, then set a PIN.
- notes: Enrol only if the server shown is your organisation's DigitVA server. The enrolment QR sets up the phone only; you still need your own password. Errors: "This is not a DigitVA enrolment code.", "The enrolment code is invalid, used or expired. Ask for a new one." and "This app is not allowed to use that server."
- sources: mobile/digitva-collect/src/nativeRoutes/enrol.tsx; mobile/digitva-collect/src/strings/theme-en.json; docs/policy/mobile-sign-in.md ("Enrolment server")
- checked: 2026-11-06

### How do I sign in with a sign-in QR (new data collector)?

- id: hdi-mobile-004
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. Ask your supervisor or data manager for a sign-in QR; they show it on screen or email it to you.
  2. In the app choose **Scan your enrolment QR** and scan it from another screen.
  3. Read "This QR will set up this phone and sign you in. Continue only if your supervisor gave it to you." and tap **Enrol on this server**.
  4. Set your PIN. You do not type a password.
- notes: A sign-in QR is valid for 6 hours and works once, on one phone. If it fails, the message reads "This sign-in QR cannot be used. It may have expired (they last 6 hours), already been scanned, been replaced by a newer one, or been made for a different DigitVA server. Ask your supervisor for a new one." After "Too many attempts. Wait a minute, then scan again." wait a minute. Do not photograph or share the QR; whoever scans it signs in as you. A sign-in QR is offered only to accounts whose grants are interviewer or death reporter (a coder grant beside them is tolerated). An account that also holds admin, project PI, data manager, reviewer or another privileged role gets the enrolment QR and password sign-in only.
- sources: mobile/digitva-collect/src/nativeRoutes/enrol.tsx; mobile/digitva-collect/src/strings/en.json; app/services/sign_in_qr_service.py; docs/policy/mobile-sign-in.md ("Sign-in QR")
- checked: 2026-11-06

### How do I get an enrolment code or a sign-in QR for a new collector?

- id: hdi-mobile-005
- roles: data_manager, project_pi, admin
- surfaces: web
- steps:
  1. Open **Users** (under More) in the web app and find the person.
  2. For an enrolment code choose **Enrolment code**, pick the project, then **Show code** or **Email code**.
  3. For a sign-in QR choose **Sign-in QR**, then **Email it** or **Show on screen**. Hand an on-screen QR to the person in person.
  4. Tell them to scan it from the app's first screen.
- notes: A shown enrolment code appears once (code and QR) and is valid for one device. A sign-in QR is valid for 6 hours and a new one cancels the pending one; use **Revoke pending QR** to cancel it. Emailing needs a verified email address; otherwise "Their email is not verified, so the QR cannot be emailed. Show it on screen instead." The warning says: do not photograph or share the screen.
- sources: mobile/digitva-collect/src/web/UsersScreen.tsx; mobile/digitva-collect/src/web/UsersDialogs.tsx; mobile/digitva-collect/src/strings/en.json; docs/policy/mobile-sign-in.md
- checked: 2026-11-06

### How do I sign in without a QR code?

- id: hdi-mobile-006
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. On the first screen choose **Sign in with email or mobile** ("If your organisation gave you a password").
  2. Enter the **Server address** your organisation gave you.
  3. Choose **Email** or **Mobile**; for mobile enter the 10-digit number (the +91 is fixed).
  4. Enter your **Password** and tap **Log in and enroll this device**.
  5. Set your PIN.
- notes: If you get "This server does not support password enrollment. Use a server QR code or contact your administrator.", use a QR. "The email or password is incorrect." means a wrong credential; "Too many attempts. Wait a few minutes and try again." means wait. Use **Forgot password?** on the sign-in screen for a password reset, or **I have a sign-in code** if you were given a one-time code.
- sources: mobile/digitva-collect/src/nativeRoutes/enrol.tsx; mobile/digitva-collect/src/nativeRoutes/sign-in.tsx; mobile/digitva-collect/src/strings/theme-en.json; docs/policy/mobile-sign-in.md
- checked: 2026-11-06

### What do I do when the app says "This account has no access to any project"?

- id: hdi-mobile-007
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. Ask your supervisor or data manager to give your account the interviewer (or death reporter) role in your project and unit.
  2. After they confirm, sign in again, or open Settings and use **Refresh access** in the Permissions section.
- notes: Other access messages: "Your account has no collection access." and, for a coder-only account, "Coding and review are done in the DigitVA web app, not on this phone. Open the web app in a browser and sign in there." A home screen reading "Your account is active, but no project roles have been assigned yet" means the same.
- sources: mobile/digitva-collect/src/strings/en.json; mobile/digitva-collect/src/nativeRoutes/settings.tsx
- checked: 2026-11-06

### What do I do when the app says "This phone is already enrolled there" or "This device has been revoked"?

- id: hdi-mobile-008
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. "This phone is already enrolled there. To change it, use Settings, 'Change server / re-enrol'." means you are trying to enrol again on the same server: just sign in, or use that Settings option to move to another server.
  2. "This device has been revoked. Enrol it again." means an administrator removed the phone: ask for a new enrolment QR and scan it.
- notes: Revoking a device never deletes unsent interviews; they stay encrypted on the phone and are sent after you enrol and sign in again with the same account.
- sources: mobile/digitva-collect/src/strings/en.json; docs/policy/mobile-sign-in.md; docs/policy/field-data-collection.md
- checked: 2026-11-06

### How many phones can I use with one account?

- id: hdi-mobile-009
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. Open **Settings** and look at **Your devices** ("N of 3 device slots in use").
  2. To free a slot, choose **Remove** beside a phone you no longer use (confirm "Remove this phone from your account?"), or sign in on the web and remove it from your profile.
  3. Then sign in on the new phone.
- notes: Up to 3 phones can be signed in at once; a fourth sign-in is refused. Removing a phone ends its sessions but leaves its encrypted data and unsent work on it.
- sources: mobile/digitva-collect/src/nativeRoutes/settings.tsx; mobile/digitva-collect/src/strings/en.json; docs/policy/mobile-sign-in.md ("Account device limit")
- checked: 2026-11-06

### How do I move the app to a different server?

- id: hdi-mobile-010
- roles: interviewer
- surfaces: android
- steps:
  1. Send all unsent work first: unlock each interviewer profile on the phone and tap **Send now**.
  2. Open **Settings** and choose **Change server / re-enrol**.
  3. Confirm: every interviewer is signed out; then scan the new server's enrolment QR.
- notes: If the phone has unsent work or a locked profile, you see "This phone cannot change server yet. Re-enrolling signs every interviewer out, and work kept on the phone can be sent only from this server. Send all work first: unlock each interviewer and sync." with each name and count. Kept data stays encrypted on the phone.
- sources: mobile/digitva-collect/src/nativeRoutes/settings.tsx; mobile/digitva-collect/src/strings/en.json; docs/policy/mobile-sign-in.md
- checked: 2026-11-06

## PIN, locking and profiles

### How do I set up or change my PIN, fingerprint or phone screen lock?

- id: hdi-mobile-011
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. After first sign-in you see "Set a PIN": enter at least 6 digits (one digit per box) and confirm.
  2. When offered "Unlock faster next time?", choose **Use fingerprint** or **Use phone screen lock**, or **Not now**.
  3. To change these later, open **Settings**, Security.
- notes: The PIN always works as well. A PIN longer than 6 digits is typed through "My PIN is longer than 6 digits" (6 to 16 digits). The screen-lock option is available only if the phone has a screen lock set.
- sources: mobile/digitva-collect/src/nativeRoutes/pin-setup.tsx; mobile/digitva-collect/src/strings/en.json; docs/policy/mobile-sign-in.md ("Phone unlock")
- checked: 2026-11-06

### What do I do if I forgot my PIN?

- id: hdi-mobile-012
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. A forgotten PIN cannot be recovered or reset. After too many wrong tries the app erases that profile's interviews from the phone.
  2. Sign in again with your account and set a new PIN.
  3. Tell your supervisor which interviews were unsent so they can be redone.
- notes: "Wrong PIN. N more wrong attempts erase this interviewer's interviews from this phone." appears after 3 wrong tries; the 5th wrong PIN in a row erases the profile: "Too many wrong PINs. This interviewer's interviews were erased from this phone. Sign in again." Only that profile is erased, not other people's profiles on the same phone. Sent interviews are safe on the server.
- sources: mobile/digitva-collect/src/vault.ts; mobile/digitva-collect/src/strings/en.json; docs/policy/field-data-collection.md
- checked: 2026-11-06

### Why does the app lock itself, and how do I stay unlocked?

- id: hdi-mobile-013
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. The app locks after 5 minutes without use, and about a minute after you leave it.
  2. A warning "This phone locks in N seconds." appears first: tap **Stay unlocked**.
  3. To lock on purpose, open the account menu and choose **Lock now**.
- notes: Locking never loses work; typed answers are saved first. Unlock with your PIN, fingerprint or phone screen lock.
- sources: mobile/digitva-collect/src/autoLock.ts; mobile/digitva-collect/src/strings/theme-en.json; mobile/digitva-collect/src/strings/en.json
- checked: 2026-11-06

### How do I sign out, and do I lose my data?

- id: hdi-mobile-014
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. Open the account menu and choose **Sign out**.
  2. Read the confirmation: "Sign out of this phone? Your data stays here, encrypted. Sign in again with this account, then your PIN, to see it."
  3. Confirm. The profile shows "Signed out. Data kept on this phone: sign in, then use your PIN."
- notes: The confirmation lists anything "Not sent yet (it is sent after you sign in again)". To resume, choose **Sign in again**, enter your password, then your PIN.
- sources: mobile/digitva-collect/src/strings/en.json; docs/policy/field-data-collection.md ("Sign-out keeps the data")
- checked: 2026-11-06

### How do I add a second person to the same phone or switch between people?

- id: hdi-mobile-015
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. To switch, open the account menu and choose **Switch profile** (the app locks first), then tap the other person's name and enter their PIN.
  2. To add someone new, on the list choose **Add profile** and sign in as them.
- notes: Each person has their own encrypted store and PIN; one cannot see the other's interviews.
- sources: mobile/digitva-collect/src/nativeRoutes/index.tsx; mobile/digitva-collect/src/nativeShell/sheets.tsx; docs/policy/field-data-collection.md
- checked: 2026-11-06

### What do I do when the app says "this phone's saved interviews were removed"?

- id: hdi-mobile-016
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. Read the message: "This phone's saved interviews were removed (the database file is missing), so there is nothing to unlock."
  2. Choose **Reset and set a new PIN**.
  3. Choose a new PIN; the app downloads your cases again.
- notes: Interviews that were not sent before this cannot be recovered. Sent interviews are safe on the server. Report it to your supervisor.
- sources: mobile/digitva-collect/src/nativeRoutes/unlock.tsx; mobile/digitva-collect/src/strings/en.json
- checked: 2026-11-06

## Sending, syncing and offline use

### Does the app work without internet?

- id: hdi-mobile-017
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. Do your first sign-in and let the first download finish ("Downloading questionnaires and data ... keep mobile data or Wi-Fi on until this closes").
  2. After that you can register deaths (interviewers), fill and finish interviews and log visits offline.
  3. When you are online again, open **Sync** and tap **Send now**.
- notes: The header shows "Offline" and a notice says "You are offline. Work is saved on this phone and sent later." Refresh and revising a submitted interview need a connection. The app makes no server calls while offline, so it does not fill the error log.
- sources: docs/policy/expo-client.md ("Offline gate"); mobile/digitva-collect/src/strings/en.json
- checked: 2026-11-06

### How do I send my work to the server?

- id: hdi-mobile-018
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. Connect to Wi-Fi or mobile data.
  2. Tap **Sync** in the bottom bar, then **Send now**. (Home also has **Send now**.)
  3. Read "Sent N. Not accepted N. Still on this phone N."
- notes: **Send now** sends finished interviews, pending registrations, queued contact attempts and visits, and ready revisions; interviews still in progress are not sent. On reconnecting, the app also makes one send pass by itself. The Sync badge shows the unsent count.
- sources: mobile/digitva-collect/src/nativeShell/sheets.tsx; mobile/digitva-collect/src/unsentWork.ts; docs/policy/expo-client.md
- checked: 2026-11-06

### How do I download new cases and the latest questionnaire?

- id: hdi-mobile-019
- roles: interviewer
- surfaces: android
- steps:
  1. Connect to the internet.
  2. On **Interviews** pull the list down, or tap **Refresh** in the Sync sheet.
  3. Wait for "Refreshed."
- notes: "Refresh needs a connection." means you are offline. "Could not refresh. Your work is safe." means the attempt failed; try again. "No cases downloaded. Connect to the internet and tap Refresh." appears when nothing is on the phone yet.
- sources: mobile/digitva-collect/src/nativeRoutes/worklistParts.tsx; mobile/digitva-collect/src/strings/en.json
- checked: 2026-11-06

### Why is my interview still not sent?

- id: hdi-mobile-020
- roles: interviewer
- surfaces: android
- steps:
  1. Check it is finished: a draft shows **Draft** / "In progress" and is not sent until you finish it; a finished one shows **Ready to send**.
  2. Check you are online, then tap **Send now** on the Sync tab.
  3. Check the Sync tab for items under "Needs attention": each shows the reason and a Ref code.
- notes: Tell your supervisor the Ref code if you need help. "Waits for its registration" means the interview waits until its death registration is accepted by the server.
- sources: mobile/digitva-collect/src/nativeShell/faq.ts; mobile/digitva-collect/src/nativeShell/sheets.tsx; mobile/digitva-collect/src/strings/en.json
- checked: 2026-11-06

### What does "Needs attention" on the Sync tab mean, and what do I do?

- id: hdi-mobile-021
- roles: interviewer
- surfaces: android
- steps:
  1. Open **Sync** and read each item's reason and Ref code.
  2. For a registration "Not accepted: edit or discard", open it and choose **Edit** (fix and save) or **Discard**.
  3. For an interview, open it, correct the flagged answers (**Go to the question**) and use **Send again**.
  4. Tell your supervisor the Ref code if it stays stuck.
- notes: **Send now** cannot send items that need attention until they are fixed; they are not in the unsent count. Messages include "This interview was not accepted" and the reason line.
- sources: mobile/digitva-collect/src/nativeShell/sheets.tsx; mobile/digitva-collect/src/strings/en.json; docs/policy/expo-client.md
- checked: 2026-11-06

### What do I do when the app says my project is paused or my access was removed?

- id: hdi-mobile-022
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. "<project name>: project paused — N items waiting to send" means your access to that project was paused or removed. The items stay on the phone and are sent when access returns.
  2. "Your access was removed. Work not yet sent stays on this phone, encrypted. Contact your supervisor." means the account lost its grant. Contact your supervisor.
  3. If asked, unlock the profile to see what has not been sent ("Access removed — N items not sent. Contact your supervisor.").
- notes: Nothing is deleted automatically. You cannot start new work in that project meanwhile. Once access is restored, sign in again if prompted ("Sign in again to send interviews.") and tap **Send now**.
- sources: mobile/digitva-collect/src/strings/en.json; docs/policy/field-data-collection.md ("Unsent work is never purged automatically")
- checked: 2026-11-06

### What do I do when the app says "Your session was revoked"?

- id: hdi-mobile-023
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. If the message is "Your session was revoked. This interviewer's data has been removed from the phone.", nothing unsent was on the phone. Sign in again.
  2. If instead you see "Access removed" with a count, unsent work was kept: see the project-paused entry.
  3. If the phone was removed from your account, enrol it again.
- notes: The app never wipes a profile that still holds unsent work after a revoke. Contact your supervisor.
- sources: mobile/digitva-collect/src/strings/en.json; docs/policy/field-data-collection.md
- checked: 2026-11-06

### What do I do when the app says storage is full?

- id: hdi-mobile-024
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. Free space on the phone (delete photos, videos or apps).
  2. Try again. The message says "Your saved answers are not lost."
  3. Send finished interviews so their local copies are cleared.
- notes: "This phone's storage is full, so nothing more can be saved."
- sources: mobile/digitva-collect/src/strings/en.json; mobile/digitva-collect/src/storageErrors.ts
- checked: 2026-11-06

### What do I do when the app says the form needs an update or cannot be loaded?

- id: hdi-mobile-025
- roles: interviewer
- surfaces: android
- steps:
  1. "Update the app to open this form. Your saved answers are kept.": install the newest app (Settings, About, **Check for updates**).
  2. "The current form is unavailable. Reconnect and try again.": connect and tap **Refresh**.
  3. "The questionnaire form could not be verified. Your saved answers are kept. Try again later.": retry after a refresh; if it persists, report the Ref code.
- notes: "This interview was started with an older form version; it now uses the current form. Your answers are kept." is information only.
- sources: mobile/digitva-collect/src/strings/en.json; docs/policy/field-data-collection.md ("Form version")
- checked: 2026-11-06

### What do I do when the phone says "Sync project settings before starting a new death registration or interview"?

- id: hdi-mobile-026
- roles: interviewer
- surfaces: android
- steps:
  1. Connect to the internet.
  2. Tap **Refresh** on Interviews (or **Send now** on Sync).
  3. Try again.
- notes: The phone needs the project's settings, sites and questionnaire once before it can start new work offline. If the first download did not finish after sign-in, repeat the refresh with a good connection.
- sources: mobile/digitva-collect/src/strings/en.json; mobile/digitva-collect/src/nativeRoutes/worklist.tsx
- checked: 2026-11-06

### What do I do when the phone says the date and time are wrong?

- id: hdi-mobile-027
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. A yellow strip says "Your phone's date/time is wrong (it is N ahead / behind). Set Date & time to automatic."
  2. Tap **Open Date & time settings**, turn on automatic date and time, return to the app.
  3. Tap **Re-check**.
- notes: A difference of 5 minutes to 4 hours is a warning only. Over 4 hours, new registrations, interviews and edits are blocked ("Fix the phone's date and time ... Nothing you typed is lost"); you can still view cases and send work. "Could not reach the server to check the time. Connect to the internet and try again." means Re-check needs a connection. A wrong clock also breaks date checks and interview times.
- sources: mobile/digitva-collect/src/nativeShell/ClockNotice.native.tsx; mobile/digitva-collect/src/phoneClock.ts; docs/policy/field-data-collection.md ("Phone clock")
- checked: 2026-11-06

## Language, display and settings

### How do I change the app language to Hindi?

- id: hdi-mobile-028
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. Open the account menu (your picture or initials at the top right).
  2. Choose **Language** and pick English or Hindi, or open **Settings**, then **App language**.
  3. Before you sign in, the language button (a "translate" icon) at the top right of the first screens does the same.
- notes: This changes the app screens only. The questionnaire language is chosen inside each interview (three-dot menu, **Questionnaire language**).
- sources: mobile/digitva-collect/src/nativeShell/sheets.tsx; mobile/digitva-collect/src/nativeShell/NativeChrome.tsx; mobile/digitva-collect/src/nativeRoutes/settings.tsx
- checked: 2026-11-06

### How do I make the text bigger or increase contrast?

- id: hdi-mobile-029
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. Open **Settings**, section **Display**.
  2. Choose **Text size**: **Small**, **Medium** or **Large**.
  3. Turn on **High contrast** for darker text and stronger edges.
- notes: "Text size also follows the phone's font size setting." Light and dark appearance follows the device setting by default.
- sources: mobile/digitva-collect/src/nativeRoutes/settings.tsx; mobile/digitva-collect/src/strings/theme-en.json
- checked: 2026-11-06

### How do I check that the camera, microphone and my access are set up?

- id: hdi-mobile-030
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. Open **Settings**, section **Permissions**.
  2. Tap **Refresh access** to re-check your project access.
  3. If Camera or Microphone is not allowed, tap its row (it offers "Enable camera" / "Enable microphone", or **Open phone settings** if it shows "Blocked; enable in phone settings").
- notes: Collection access and the current project are listed too. Offline it shows the saved access ("Offline. Showing saved access details.").
- sources: mobile/digitva-collect/src/nativeRoutes/settings.tsx; mobile/digitva-collect/src/strings/en.json; mobile/digitva-collect/src/strings/theme-en.json
- checked: 2026-11-06

### How do I get help inside the app?

- id: hdi-mobile-031
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. Open the account menu and choose **Help**, or open **Settings** and **Help & support**.
  2. Read "What this screen is for" and "What to do now". Search **Common questions** for a topic.
  3. For the full guide choose **Open the full guide** (needs internet).
- notes: The short help and common questions are built into the app and work offline. "The guide could not be opened. Check your connection and sign-in." means the full guide needs a connection.
- sources: mobile/digitva-collect/src/nativeShell/sheets.tsx; mobile/digitva-collect/src/nativeShell/faq.ts; docs/policy/expo-client.md ("Common questions")
- checked: 2026-11-06

### How do I send the error log to support?

- id: hdi-mobile-032
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. Open **Settings**, section **Diagnostics**.
  2. Tap **Export errors** and share the file with your supervisor.
- notes: The file lists error codes and screens; it holds no interview answers or names. "No errors recorded." means nothing to export.
- sources: mobile/digitva-collect/src/nativeRoutes/settings.tsx; mobile/digitva-collect/src/nativeShell/faq.ts; docs/policy/expo-client.md ("Local error log")
- checked: 2026-11-06

### How do I check for an app update?

- id: hdi-mobile-033
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. Open **Settings**, About, and tap **Check for updates**.
  2. If "Update available: <version>" shows, tap **Download** and install it from your browser's download.
  3. "The app is up to date." means you have the newest version.
- notes: The app also checks once a day at start. It never installs by itself. If the check says "Couldn't check", you are offline. Builds from Google Play update through Google Play ("App updates come from Google Play."). Settings also shows **Server compatibility**: "This server may not support this app version" means update or ask your administrator.
- sources: mobile/digitva-collect/src/nativeRoutes/settings.tsx; mobile/digitva-collect/src/updateCheck.ts; docs/policy/expo-client.md ("Update check")
- checked: 2026-11-06

### How do I stop usage diagnostics or delete my account?

- id: hdi-mobile-034
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. Usage diagnostics: **Settings**, Diagnostics, **Usage diagnostics**; turn it **Off**. It shares daily totals only, never interview data.
  2. Account deletion: **Settings**, **Delete my account**, then **Send request**.
- notes: For staff accounts, deleting sends a request to the programme team, who confirm with you before acting; audit history is kept. In the public demo it deletes the demo account immediately after your password.
- sources: mobile/digitva-collect/src/nativeRoutes/settings.tsx; mobile/digitva-collect/src/TelemetrySettings.tsx; mobile/digitva-collect/src/strings/en.json
- checked: 2026-11-06

### Why can't I take a screenshot in the app?

- id: hdi-mobile-035
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. Screenshots and screen recording are blocked to protect personal data.
  2. Use a second device only for non-confidential steps, or write the Ref code down.
- notes: The block is temporarily relaxed in some builds for a few weeks; do not depend on it. Never photograph a QR or an interview screen to share.
- sources: docs/policy/expo-client.md ("Screen capture"); mobile/digitva-collect/src/screenCapture.ts
- checked: 2026-11-06

## Home, lists and daily use

### What do I see on the Home screen?

- id: hdi-mobile-036
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. Read the counts card (unsent items, cases needing a visit, drafts in progress).
  2. Tap **Send now** to send unsent work.
  3. Under "Next step" tap **Resume draft** or **Start an interview**; use **Register a death** if your account may register.
- notes: Home is built from data on the phone, so it works offline. "Nothing in progress. Start the next interview." appears when you have no drafts.
- sources: mobile/digitva-collect/src/nativeRoutes/worklistParts.tsx; docs/policy/expo-client.md ("Phone shell")
- checked: 2026-11-06

### How do I find a case on the Interviews tab?

- id: hdi-mobile-037
- roles: interviewer
- surfaces: android
- steps:
  1. Open **Interviews**.
  2. Type in **Search name or ID** (works in Hindi too).
  3. Use the chips **All**, **Drafts**, **To do**, **Sent** and **Revisions**; each shows a count.
- notes: Each card shows the name, the ID, a badge (Draft, To do, Sent, Revision) and one action (**Resume** or **Start**). If you work in several projects use **Change project**. Use the site/unit picker to switch unit.
- sources: mobile/digitva-collect/src/nativeRoutes/worklistParts.tsx; docs/policy/expo-client.md ("Phone shell")
- checked: 2026-11-06

### Why can't I register or interview in a unit, or why is a unit missing from the list?

- id: hdi-mobile-038
- roles: interviewer, death_reporter
- surfaces: android
- steps:
  1. Open the site or unit picker ("Choose the unit") and search for the unit.
  2. If it is not there, refresh while online ("No sites yet. Connect to the internet and tap Refresh.").
  3. If it is still missing, ask your data manager to check your grant: units are listed from your granted units and everything below them.
- notes: "No unit matches your search." means the text did not match; "You cannot open this unit." appears on the organization screen for units outside your reach.
- sources: mobile/digitva-collect/src/strings/en.json; docs/policy/web-intake.md ("Ownership and visibility")
- checked: 2026-11-06

### How do I try the app with practice data?

- id: hdi-mobile-039
- roles: interviewer
- surfaces: android
- steps:
  1. On the first screen choose **Try the demo** ("Practice with test data").
  2. Create a demo account or sign in to your demo account.
  3. Collect practice interviews.
- notes: The demo is public. Do not enter real personal or health data. Your demo account and its data are deleted 30 days after your last sign-in; there is no password reset, so create a new account if you forget the password.
- sources: mobile/digitva-collect/src/nativeRoutes/demo.tsx; mobile/digitva-collect/src/strings/en.json; docs/policy/public-demo.md
- checked: 2026-11-06

### What is the Training menu?

- id: hdi-mobile-040
- roles: interviewer, death_reporter, interview_supervisor
- surfaces: web
- steps:
  1. If your trainer added you to a training session, open **Training** in the web app's left menu.
  2. Choose your area (Interview, Coding or Review) and **Start**.
  3. In the interview area you can register a death ("Report a death") and interview as a field worker would.
- notes: Training uses its own project and never mixes with real work. If you see "You have not been added to an active training session. Ask your trainer to add you with your account's email address.", ask your trainer.
- sources: mobile/digitva-collect/src/training.ts; mobile/digitva-collect/src/strings/en.json; docs/policy/training-demo-project.md
- checked: 2026-11-06

### Can I do coding or review in the phone app?

- id: hdi-mobile-041
- roles: coder, reviewer
- surfaces: android
- steps:
  1. Open the DigitVA web app in a browser and sign in with the same account.
  2. Use **VA Code** or **VA Review** from the left menu.
- notes: The phone app shows "Coding and review are done in the DigitVA web app, not on this phone." Collect Plus can code on the phone only when ICD-11 / DORIS coding is enabled in Settings and your project permits it.
- sources: mobile/digitva-collect/src/strings/en.json; docs/policy/expo-client.md ("Unified phone coding access")
- checked: 2026-11-06

### Can I use the app in a browser instead of installing it?

- id: hdi-mobile-042
- roles: interviewer, death_reporter, interview_supervisor
- surfaces: web
- steps:
  1. Sign in to DigitVA in your browser.
  2. Open the app home (Home) and use **Deaths** and **VA Interview**.
- notes: The browser app needs a connection: it saves answers to the server and keeps no offline copy. After 30 minutes without activity it signs you out (warning at 28 minutes). Use it while the Android release is unavailable.
- sources: mobile-app; docs/policy/expo-client.md; app/templates/help/pages/mobile-app.html
- checked: 2026-11-06
