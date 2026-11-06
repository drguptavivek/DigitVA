---
title: How-Do-I Corpus - Account and Sign-in
doc_type: help-corpus
status: draft
owner: engineering
last_updated: 2026-11-06
---

# How-Do-I Corpus - Account and Sign-in

Entries on signing in, passwords, email verification, the profile and
questionnaire translation suggestions. Format and truth rules:
`docs/policy/help-chatbot.md`.

### How do I sign in on the web?

- id: hdi-account-001
- roles: coder, reviewer, coding_tester
- surfaces: web
- steps:
  1. On the login page enter your email or 10-digit mobile number and continue.
  2. On the next page enter your password and press the sign-in button, or press **Use a passkey**.
- notes: Email is not case-sensitive. After sign-in you land on the DigitVA app home. Sign-in attempts are rate limited (10 a minute per address and 20 an hour per account), so wait a few minutes after repeated failures. On the next page "Not you? Start again" returns to the first step.
- sources: authentication; `app/templates/va_frontpages/va_login.html`; `app/templates/va_frontpages/va_login_password.html`; `app/routes/va_auth.py`; docs/policy/authentication-factors.md
- checked: 2026-11-06

### What does "Invalid email or password. Please, re-check and login again." mean?

- id: hdi-account-002
- roles: coder, reviewer, coding_tester
- surfaces: web
- steps:
  1. Re-enter your identifier and the password exactly as emailed (the three words, the number and the hyphens).
  2. If it still fails, use **Forgot Password?**.
- notes: The same message appears for an unknown or inactive account, so it does not tell you which part was wrong.
- sources: `app/routes/va_auth.py` (`INVALID_LOGIN_MESSAGE`)
- checked: 2026-11-06

### Why do I see "Please verify your email address before logging in"?

- id: hdi-account-003
- roles: coder, reviewer, coding_tester
- surfaces: web
- steps:
  1. Open the verification email DigitVA sent when your account was created and press **Verify my email** on its page.
  2. If you cannot find it or the link expired, press **Resend verification email** on the login page, enter your email and send.
- notes: Verification links expire after 24 hours and work once. Check spam. The resend form always replies "If that email address needs verification, we've sent a new link." and allows 3 requests an hour per address.
- sources: email-verification; `app/templates/va_frontpages/va_resend_verification.html`; `app/templates/va_frontpages/va_login.html`; `app/routes/va_auth.py`
- checked: 2026-11-06

### I verified my email but I have no password. What now?

- id: hdi-account-004
- roles: coder, reviewer, coding_tester
- surfaces: web
- steps:
  1. After **Verify my email**, the page says "Your email is verified." and "Please check your email for your password."; DigitVA emails you the password.
  2. Wait a few minutes, check spam, then sign in with it.
- notes: The page never shows the password. Nobody chooses their own password. If no email arrives, ask whoever created your account to check the address.
- sources: email-verification; `app/templates/va_frontpages/va_email_verified.html`; docs/policy/account-onboarding-and-passwords.md
- checked: 2026-11-06

### I forgot my password. How do I get a new one?

- id: hdi-account-005
- roles: coder, reviewer, coding_tester
- surfaces: web
- steps:
  1. On the login page press **Forgot Password?**, enter your email and send the link.
  2. Open the link from your inbox and press **Email me a new password**.
  3. Sign in with the emailed password.
- notes: The link expires after 1 hour and works once. Your old password stops working and every signed-in session ends. Opening or requesting does not change the password; only pressing the button does. The reply is the same whether or not the account exists.
- sources: password-reset; `app/templates/va_frontpages/va_forgot_password.html`; `app/templates/va_frontpages/va_reset_password.html`; `app/routes/va_auth.py`
- checked: 2026-11-06

### I only have a mobile number. How do I sign in or get a new password?

- id: hdi-account-006
- roles: coder, reviewer, coding_tester
- surfaces: web
- steps:
  1. Ask the person who created your account (for example your data manager or an administrator) for your sign-in code (6 digits).
  2. On the login page press **I have a code**, enter your mobile number (or email) and the code, accept the terms and continue.
  3. Write down the new password shown once, then continue to sign in.
- notes: The code works once and expires after 72 hours (policy). The password is shown only on that page.
- sources: `app/templates/va_frontpages/va_login_code.html`; `app/templates/va_frontpages/va_login_code_password.html`; docs/policy/account-onboarding-and-passwords.md; password-reset
- checked: 2026-11-06

### Can I choose my own password?

- id: hdi-account-007
- roles: coder, reviewer, coding_tester
- surfaces: both
- steps:
  1. Open **My Profile** and press **Generate a new password** to get a fresh one.
- notes: Every password is generated for you (three words and a number, for example river-mango-lamp-4821). Only public-demo accounts choose their own.
- sources: profile; `app/templates/va_frontpages/va_myprofile.html`; docs/policy/account-onboarding-and-passwords.md
- checked: 2026-11-06

### How do I change my password from my profile?

- id: hdi-account-008
- roles: coder, reviewer, coding_tester
- surfaces: web
- steps:
  1. Open the account menu and choose **Profile** (classic pages: your name, then **My Profile**).
  2. Under Password, enter your **Current Password** (needed if you did not sign in within the last ten minutes).
  3. Press **Generate a new password**, then press **Sign in again** and use the new password.
- notes: With a verified email the new password is emailed; otherwise it is shown once. Your old password stops working and you sign in again. If the breach check or email is unavailable, nothing changes; try again.
- sources: profile; `app/templates/va_frontpages/va_myprofile.html`; `mobile/digitva-collect/src/workspace/AccountMenu.web.tsx`
- checked: 2026-11-06

### What are the terms and conditions screen after my first sign-in?

- id: hdi-account-009
- roles: coder, reviewer, coding_tester
- surfaces: web
- steps:
  1. Read the terms, tick "I agree to the above Terms and Conditions." and press **Continue**.
- notes: It appears at your first sign-in and again after every password reset. It does not change your password.
- sources: profile; `app/routes/profile.py` (`force-password-change`); `app/templates/va_form_partials/va_forcepwreset.html`
- checked: 2026-11-06

### How do I sign out, and why was I signed out?

- id: hdi-account-010
- roles: coder, reviewer, coding_tester
- surfaces: web
- steps:
  1. Open the account menu and press **Sign out** (classic pages: **Logout**).
- notes: You are signed out after 30 minutes of inactivity ("Signed out after 30 minutes of inactivity.") and after 12 hours in total ("Your session ended after 12 hours. Please sign in again."). The login page has no "Remember Me" option. The app warns "Still there?" two minutes before inactivity sign-out and offers **Stay signed in**.
- sources: `app/utils/idle_session.py`; `mobile/digitva-collect/src/strings/en.json` (`idle*`); `mobile/digitva-collect/src/workspace/AccountMenu.web.tsx`
- checked: 2026-11-06

### What if my session ended while I was saving work?

- id: hdi-account-011
- roles: coder, reviewer
- surfaces: web
- steps:
  1. Press **Sign in again** (it opens a new tab) and sign in.
  2. Return and press **Resume saving**.
- notes: "Your session ended. Your answers are kept on this device and are not lost." Coding allocations are still bound by their one-hour limit.
- sources: `mobile/digitva-collect/src/strings/en.json` (`sessionEndedKept`, `sessionEndedResume`)
- checked: 2026-11-06

### Why does the login page say the site is under maintenance?

- id: hdi-account-012
- roles: coder, reviewer, coding_tester
- surfaces: web
- steps:
  1. Wait for the maintenance window to end and try again.
- notes: During maintenance only administrators can sign in. The login page shows any message the administrator set.
- sources: authentication; `app/routes/va_auth.py`; docs/policy/site-maintenance-mode.md
- checked: 2026-11-06

### How do I add a passkey?

- id: hdi-account-013
- roles: coder, reviewer, coding_tester
- surfaces: web
- steps:
  1. Open **My Profile**, find **Passkeys** and press **Add a passkey**.
  2. Confirm your password when asked, then approve with your device's screen lock or biometric.
- notes: Passkeys are optional and password sign-in keeps working. Adding, renaming or removing one needs a recent password or passkey sign-in. Native app passkey sign-in is not built.
- sources: `app/templates/va_frontpages/va_myprofile.html`; docs/policy/authentication-factors.md
- checked: 2026-11-06

### How do I change my time zone?

- id: hdi-account-014
- roles: coder, reviewer, coding_tester
- surfaces: web
- steps:
  1. Open **My Profile**, find **Time Zone**, choose yours and press **Update Time Zone**.
- notes: All times in the system, including recode deadlines and coding dates, are then shown in that zone. The default is Asia/Kolkata.
- sources: profile; `app/templates/va_frontpages/va_myprofile.html`
- checked: 2026-11-06

### Can I change my coding languages or role myself?

- id: hdi-account-015
- roles: coder, reviewer
- surfaces: web
- steps:
  1. Ask your data manager, project PI or administrator.
- notes: The profile shows your name, email, coding languages and time zone, but languages and role grants are assigned by others. You can set an optional **Job title** (visible to people who see you in lists; it gives no access).
- sources: profile; `app/templates/va_frontpages/va_myprofile.html`
- checked: 2026-11-06

### How do I see what projects and roles I have?

- id: hdi-account-016
- roles: coder, reviewer
- surfaces: both
- steps:
  1. On the web open the Home screen: "My projects & roles" lists each role with its scope, such as "Within Area: <unit>".
  2. On Android open **Settings** and **Profile and project access**.
- notes: "Within Area" means only deaths from that facility, block or district; "All" means the whole project. If a project you expect is missing, ask your administrator to check that your grant is active.
- sources: profile; user-roles; `mobile/digitva-collect/src/strings/en.json` (`homeProjectsAndRolesTitle`, `homeScopeUnit`, `profileAccessTitle`)
- checked: 2026-11-06

### How do I ask for my account to be deleted?

- id: hdi-account-017
- roles: coder, reviewer
- surfaces: web
- steps:
  1. Open **My Profile** and press **Request account deletion**.
- notes: The team confirms with you before acting, and security and sign-in audit history is kept. Demo accounts can delete themselves at once with **Delete my account**.
- sources: `app/templates/va_frontpages/va_myprofile.html`
- checked: 2026-11-06

### How do I sign in on the DigitVA Collect phone app?

- id: hdi-account-018
- roles: coder, reviewer
- surfaces: android
- steps:
  1. Scan the sign-in or enrolment QR your supervisor gives you, or choose **Log in without a QR code**, enter the server address and your account details.
  2. If asked, confirm the server and project, then set a PIN.
- notes: A sign-in QR lasts 6 hours and works once; if it fails ask for a new one. "This phone is already enrolled there" means use Settings to change server or re-enrol.
- sources: mobile-app; `mobile/digitva-collect/src/strings/en.json` (`enrol*`, `errSignInQrInvalid`); docs/policy/mobile-sign-in.md
- checked: 2026-11-06

### How do I unlock the app, and what if I forget my PIN?

- id: hdi-account-019
- roles: coder, reviewer
- surfaces: android
- steps:
  1. Enter your PIN (6 to 16 digits) on the **Unlock** screen, or use fingerprint or screen lock if you turned that on.
- notes: A forgotten PIN cannot be recovered: you sign in again and unsent interviews are lost. After too many wrong PINs the interviewer's interviews are erased from the phone. The app also locks after a period of non-use.
- sources: `mobile/digitva-collect/src/strings/en.json` (`pin*`, `unlock*`, `autoLockInfo`)
- checked: 2026-11-06

### The phone says "Sign in again" or my session was revoked. What now?

- id: hdi-account-020
- roles: coder, reviewer
- surfaces: android
- steps:
  1. Press **Sign in again** and use your account.
- notes: Signing in again keeps work on the phone. "Your session was revoked. This interviewer's data has been removed from the phone." means an administrator revoked access; ask your supervisor. "This device has been revoked. Enrol it again." needs a new enrolment.
- sources: `mobile/digitva-collect/src/strings/en.json` (`signInAgain*`, `sessionRevoked`, `errDeviceRevoked`)
- checked: 2026-11-06

### How do I suggest a better wording for a questionnaire translation?

- id: hdi-account-021
- roles: coder, reviewer, interviewer, data_manager
- surfaces: web
- steps:
  1. Open **Translations** in the Manage menu (page "Questionnaire translations").
  2. Choose the **Project** and **Language**.
  3. Find the question and press **Suggest** beside the string.
  4. Type your wording ("Your suggested wording"), a reason (required) and press **Send suggestion**.
- notes: Any user with an active grant in a project can read the translations the project serves and suggest. You cannot edit directly: an administrator or the project PI accepts or rejects. Strings not yet translated show "not yet translated". Nothing changes until accepted.
- sources: `app/routes/translation_suggestions_page.py`; `app/static/js/translation_suggestions.js`; `app/templates/va_intermediate_partials/va_navbar.html`; docs/policy/va-form-project-configuration.md ("District review and suggestions")
- checked: 2026-11-06

### Why does the translations page say there is nothing to show?

- id: hdi-account-022
- roles: coder, reviewer, interviewer
- surfaces: web
- steps:
  1. Ask your administrator for a grant on an active project that serves a translated language.
- notes: The page reads "you hold no grant on an active project that serves a translated language."
- sources: `app/templates/va_frontpages/va_translation_suggestions.html`
- checked: 2026-11-06

### What happens to my translation suggestion?

- id: hdi-account-023
- roles: coder, reviewer, interviewer
- surfaces: web
- steps:
  1. Wait for the administrator or project PI to decide.
- notes: You have at most one pending suggestion per string and 50 pending in total. Accepting changes that language for every project using that locale of the questionnaire. No email is sent.
- sources: docs/policy/va-form-project-configuration.md
- checked: 2026-11-06

### How do I switch the app language?

- id: hdi-account-024
- roles: coder, reviewer
- surfaces: android
- steps:
  1. Open **Settings** and the **Language** section.
- notes: This changes the app's screens. Questionnaire languages for interviews are set by the project.
- sources: `mobile/digitva-collect/src/strings/en.json` (`settingsLanguage`); `mobile/digitva-collect/src/nativeRoutes/settings.tsx`
- checked: 2026-11-06

### Where do I get help and contact the team?

- id: hdi-account-025
- roles: coder, reviewer, coding_tester
- surfaces: web
- steps:
  1. Open **Help** in the menu or **Help & guides** on the home screen.
  2. For technical issues, contact the Central Admin Team at AIIMS, New Delhi and quote the VA Form ID or SID.
- notes: Do not send names or case details in chat questions.
- sources: `app/templates/va_intermediate_partials/va_navbar.html`; `app/templates/va_frontpages/va_coding.html`; `mobile/digitva-collect/src/strings/en.json` (`homeOpenHelp`)
- checked: 2026-11-06
