---
title: DORIS picker rules observed from WHO's coding tool
doc_type: kb
status: active
owner: engineering
last_updated: 2026-09-27
---

# DORIS picker rules observed from WHO's coding tool

These rules were observed on `icd.who.int/doris/workspace/en` (WHO ECT 1.8)
on 2026-09-27 and are what `app/static/js/digitva_icd11_picker.js` mirrors.
Each rule names the WHO behaviour, the evidence, and DigitVA's behaviour.
The policy baseline is `docs/policy/doris-cod-workflow.md`; the JSON
shapes are in `docs/kb/doris-certificate-ui-contract.md`.

## Search rows

1. **Code plain, title emphasised.** WHO shows the code in normal weight
   and the title in bold. DigitVA renders `span.doris-search-code` plain and
   the title semibold; hover is a light background, not a link underline.
2. **Mandatory postcoordination withholds direct selection.** A stem whose
   WHO `postcoordinationAvailability` is 2 (for example `BD54`, whose
   "Has causing condition" axis is required) offers Build only; `Use` is
   withheld until the expression is complete. Availability 1 (for example
   `NC72.7`, all axes optional, coding note present) keeps `Use`. The
   "Mandatory postcoordination" text seen on WHO's rows is a row icon's
   accessible name, not a code property; the local WHO API is the source.
3. **A composite result opens its stem.** The "+" on a complete expression
   such as `BD54/MC85` opens the builder for `BD54` with `MC85` already
   chosen under "Has manifestation" and the remaining axes offered.
   DigitVA passes the other parts as `preselect`; a part that is a root
   option is pressed directly, otherwise it is resolved through `codeinfo`
   and attached to the first axis that takes stem codes (an X code goes to
   "Other postcoordination"), and it renders as a pressed chip.

## Builder (postcoordination panel)

4. **Axis order and wording.** Required axes first, then the others in WHO
   scale order. Headings read `Label (code also.)` for a required stem axis
   and `Label (use additional code, if desired.)` otherwise. Axis labels are
   the WHO axis id in sentence case (ECT uses `upperFirst(lowerCase(id))`),
   so "Object or substance producing injury" needs no name table.
5. **Search inside an axis.** Every axis has a "search in axis" box that
   searches WHO MMS within the axis's root subtree. DigitVA sends
   `subtree_uris` on the shared `terms` route, forwarded as WHO
   `subtreesFilter`.
6. **"Other postcoordination?" is an open-ended search, not a group.** ECT
   synthesises it as a search over the extension chapter (foundation
   979408586, release URI `.../mms/979408586`) and shows it only for MMS
   category stems outside chapter X. A pick is accepted only if WHO
   `codeinfo` resolves `stem&code`: `BD54&XK9J` resolves, `BD54&XS5W` does
   not. DigitVA checks at pick time and shows "WHO does not accept X as an
   extension of STEM."
7. **Uncoded folders expand, never select.** A `▷` node such as
   "Meningiomas, benign" or "23 External causes" expands inline; clicking
   its title only highlights it. DigitVA renders them as `▷` nodes with no
   select control and no alert.
8. **Expression grammar.** WHO canonicalises `stem&ext&ext/stem&ext`: an
   `&` after a `/` belongs to the second stem. DigitVA emits X extensions
   before `/` stems, each group in WHO axis order, so `BD54&XK9J/5A11`
   rather than `BD54/5A11&XK9J`.
9. **Stable footer.** The live expression ("Building: …", with "required
   axis missing" when applicable) and the "Use complete expression" and
   "Use stem without extensions" actions sit in the sticky modal footer,
   which WHO shows as `Code: JB64.4 / BD54 ✓ Select` at the top of its
   panel. Re-rendering after "More choices" keeps the scroll offset and
   does not move focus.

## Related maternal and perinatal categories

10. **The composite is the primary related choice.** WHO's Details show
    "Related categories in maternal chapter: … (JB64.4/BD54)". Clicking the
    link opens the builder for `JB64.4` with `BD54` already chosen under
    "Associated with"; Select gives `JB64.4 / BD54`. DigitVA's `J`/`K`
    panel lists the composite first, and clicking it opens the builder the
    same way (rule 3); the broader category and its children follow.

## Details panel

11. **No matching terms.** Matching terms are search entry points and are
    not shown in the details panel; the details response omits them. The
    panel shows the coding note first, then definition, fully specified
    name, inclusions and exclusions.

## Certificate form (DORIS workspace)

12. **Part I lines carry no underlying-cause label.** DORIS labels lines
    A to D with "Due to" between them and computes the underlying cause
    itself; no line is marked as the underlying cause and there is no field
    for it. DigitVA heads the first line "Immediate cause" and each later
    line "Due to", under "Part I: Cause of death", and never labels a line
    as the underlying cause. The line letters are not shown, so a blank-line
    error names the line by number.
13. **Estimated age is a number and a unit.** DORIS shows "Estimated age"
    with an "Age unit" list: Years, Months, Weeks, Days, Hours, Minutes,
    Seconds, Unknown. DigitVA uses the same units through
    `doris_interval.js` and still sends an ISO 8601 duration (`P44Y`,
    `P2D`); Unknown omits the age.
14. **The fetal or infant section is always shown.** DORIS has no
    applicable switch. DigitVA shows the section and sends
    `FetalOrInfantDeath` only when at least one of its fields is filled.

15. **No fetal or infant field is mandatory, and only Stillborn changed
    the selection.** DORIS marks the section "fields are not mandatory" and
    keeps it on screen at age 44 years. Local engine runs on 2026-09-27: a
    stillbirth certificate gave `KD3B.1` with `Stillborn` 1 and `KD5Z`
    without it; a 2-day neonate gave `KB23.0Z` with or without the section,
    but CoDEdit raised `FER-CE-934` (birth weight and completed weeks
    missing, advisory) for any age under one year. Fetal data on an adult
    raised `FER-CE-987`. For VA, send Stillborn when relevant and birth
    weight and weeks when the interview has them; omit the rest.
16. **`DeathWithin24h` is hours survived.** WHO's exchange format and the
    DORIS label ("If death within 24h specify number of hours survived")
    define an integer count of hours, not yes/no. DigitVA's field is a
    0-24 number, matching the server's existing bound.

17. **DORIS's injury cluster is not a codeinfo code.** For an injury death
    DORIS returns the external cause first (`PA60/NC72.Z`, stem `PA60`),
    the mortality convention. WHO `codeinfo` on the local 2026-01 release
    returns not found for that string and resolves only `NC72.Z/PA60`, whose
    stem is the injury. Step 2's "Use DORIS result" therefore offers DORIS's
    full code when codeinfo resolves it and otherwise its stem (`PA60`), the
    underlying cause itself; never the reversed cluster. Observed
    2026-09-27 in the clinical editor on a SADEMO case.

## Not observed or deliberately different

- WHO's per-term "+" inside Details (one per matching term) is not
  reproduced; DigitVA opens the builder from the row.
- WHO's ECT keyboard mode and flexible search are not reproduced.
