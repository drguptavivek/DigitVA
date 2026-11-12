# Maestro flows (local only, never CI)

End-to-end flows for the Collect Plus debug build on the Android emulator
`DigitVA_Pixel_7` (`emulator-5554`). Test data only. Metro must already serve
the bundle on 8081 and the app must point at the dev server
(`http://10.0.2.2:8051`). The phone needs the profiles `test.all` and
`test.sn.dh01`, enrolled and unlocked once.

| Flow | Checks |
| --- | --- |
| `consent-cancel.yaml` | Consent Yes + respondent sex Female, change consent to No, Cancel the delete dialog: answers kept, also after leaving and reopening the draft |
| `media-resume.yaml` | Audio recording and camera photo attached, app backgrounded and relaunched, unlock, reopen draft: both still present |
| `lock-unlock.yaml` | Lock now from the Account menu, unlock, Drafts count and draft answers intact |
| `switch-profile.yaml` | Switch to `test.sn.dh01` and back, Drafts count and draft answers intact |

Shared subflows (not run alone): `start.yaml`, `unlock.yaml`, `new-interview.yaml`,
`drafts-count.yaml`, `open-draft-check.yaml`. Each flow creates one new draft
(Drafts count +1) on `test.all`; nothing is deleted or signed out.

## PINs

PINs never go into files here. Pass them as environment variables (the values
are in `private/emulator-test-accounts.md`, which is local only):

```
export MAESTRO_PIN=<test.all PIN>          # 6 digits
export MAESTRO_PIN_OTHER=<test.sn.dh01 PIN>
make maestro-android                        # all flows
cd mobile/digitva-collect
maestro --device emulator-5554 test -e PIN="$MAESTRO_PIN" .maestro/lock-unlock.yaml
maestro --device emulator-5554 test -e PIN="$MAESTRO_PIN" -e PIN_OTHER="$MAESTRO_PIN_OTHER" .maestro/switch-profile.yaml
```

Always pass `--device emulator-5554`: a physical phone may also be on adb.

## Notes

- The PIN boxes drop fast input: `unlock.yaml` types one digit at a time, then taps Unlock.
- Do not use `hideKeyboard` in flows: on Android it sends Back and leaves the form.
- Selectors are testIDs (`question-<name>-choice-<value>`) plus the English strings
  in `src/strings/en.json`; flows assume the app language is English.
- The "sex Female" answer is the respondent's sex (`Id10007a`), the first sex
  question that follows the consent section on this form; the deceased's sex is
  not asked until later.
- Flows are slow (about 3 minutes each) because long forms are scrolled to the target question.
