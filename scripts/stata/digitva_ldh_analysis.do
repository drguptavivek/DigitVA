* =============================================================================
* DigitVA: routine use of versions 1 and 2 (Lancet Digital Health manuscript)
*
* Purpose: reproduce every number in table 2 and the Results text of
*   docs/manuscript/DigitVA_LDH_Manuscript.docx (and the appendix flow, missing
*   data and sensitivity numbers), each commented with the manuscript item.
*
* Inputs (de-identified, in this folder; built by scripts/stata/build_package.sh):
*   data/digitva_ldh_cases.csv      one row per verbal autopsy (7917 rows)
*   data/digitva_ldh_syncruns.csv   one row per ODK synchronisation run
* Data cut-off: May 31, 2026 (submissions and active final causes before June 1).
*
* Outputs (output/):
*   digitva_ldh_analysis.log        full log
*   digitva_ldh_tables.xlsx         sheets "Table 2", "Results text", "Check"
*   figure2_monthly.png, figure3_workload.png
*
* How to run (Stata 17 or later), from this folder:
*   /Applications/Stata/StataSE.app/Contents/MacOS/stata-se -b do digitva_ldh_analysis.do
*   or, in Stata: cd to this folder, then  do digitva_ldh_analysis.do
*
* Manuscript values are typed below with a full stop for the decimal point.
* Every table 2 cell and every Results sentence is compared with its computed
* value; mismatches are listed in the log and in the "Check" sheet.
*
* Not reproducible from the data sheet (database or other sources; see README):
*   - Hosting cost per month (mean US$28, range 23-42, Mar 2025-May 2026): AWS invoices.
*   - Flagged-reason wording ("insufficient information", language): free text,
*     not exported. SQL: select va_coder_review reason text grouped by reason.
*   - "No attachment ... refused or recorded with an error" (16 751 files):
*     select count(*) from va_submission_attachments where status/error set.
*   - "Most interviews were loaded on April 2, 2026": needs the exact
*     submission date (the sheet holds submission month only).
*   - Commit counts in Costs (43 days, VG 39, TS 5): git log.
* =============================================================================
version 17
clear all
set more off
capture mkdir "output"
capture log close
log using "output/digitva_ldh_analysis.log", replace text

* ---------------------------------------------------------------------------
* Helpers. Results are posted to two files and written to Excel at the end.
*   T2: table 2 rows (item, computed v1/v2/total, manuscript v1/v2/total)
*   RT: Results-text items (item, manuscript, computed)
* ---------------------------------------------------------------------------
tempfile t2file rtfile
postfile T2 str90 item str40 c1 str40 c2 str40 ct str40 m1 str40 m2 str40 mt using `t2file', replace
postfile RT str110 item str60 manuscript str60 computed using `rtfile', replace

capture program drop t2row
program define t2row
    args item c1 c2 ct m1 m2 mt
    post T2 ("`item'") ("`c1'") ("`c2'") ("`ct'") ("`m1'") ("`m2'") ("`mt'")
    di as text "T2 | `item' | `c1' | `c2' | `ct'   [ms: `m1' | `m2' | `mt']"
end

capture program drop rt
program define rt
    args item man comp
    post RT ("`item'") ("`man'") ("`comp'")
    di as text "RT | `item' | ms: `man' | computed: `comp'"
end

* n (x.x%) for the condition `num' among `den', by version and total.
* Optional third argument "nN" gives n/N (x.x%).
capture program drop npct
program define npct, rclass
    args num den fmt
    foreach v in 1 2 t {
        local w = cond("`v'" == "t", "1", "version == `v'")
        quietly count if (`num') & `w'
        local n = r(N)
        quietly count if (`den') & `w'
        local d = r(N)
        local p = string(100 * `n' / `d', "%4.1f")
        if "`p'" == "100.0" local p 100
        if "`fmt'" == "nN" return local s`v' "`n'/`d' (`p'%)"
        else return local s`v' "`n' (`p'%)"
        return scalar n`v' = `n'
        return scalar d`v' = `d'
    }
end

* median (IQR) of variable `var' among `cond'; `dec' = decimals
capture program drop medi
program define medi, rclass
    args var cond dec
    local f = "%4.`dec'f"
    foreach v in 1 2 t {
        local w = cond("`v'" == "t", "1", "version == `v'")
        quietly summarize `var' if (`cond') & `w', detail
        return local s`v' "`=string(r(p50), "`f'")' (`=string(r(p25), "`f'")'–`=string(r(p75), "`f'")')"
    }
end

* ---------------------------------------------------------------------------
* 1. Load and derive
* ---------------------------------------------------------------------------
import delimited "data/digitva_ldh_cases.csv", varnames(1) clear stringcols(4 5 11)
assert _N == 7917

label define version 1 "Version 1 (UNSW)" 2 "Version 2 (ICMR)"
label values version version
gen byte narr_text       = narr_class == 3
gen byte narr_short      = narr_class == 2
gen byte narr_pointer    = narr_class == 1
gen byte narr_placeholder = narr_class == 0
gen byte narr_any        = narr_class == 3 | narr_image == 1 | narr_audio == 1
gen byte narr_none       = narr_class <= 1 & narr_image == 0 & narr_audio == 0
gen byte docs            = doc_pages > 0
gen byte reversioned     = payload_versions > 1
gen byte answers_changed = answer_changes > 0
gen coded_day   = date(coded_date, "YMD")
gen coded_month = mofd(coded_day)
gen sub_m       = monthly(sub_month, "YM")
format coded_day %td
format coded_month sub_m %tm

* Interval guards (Methods): death to interview 0-3650 days; negative
* submission-to-final intervals set to missing.
replace death_to_interview_d = . if death_to_interview_d < 0 | death_to_interview_d > 3650
replace sub_to_final_d = . if sub_to_final_d < 0

* Step 1 vs step 2 against SmartVA (cause groups of the WHO 2022 VA list)
gen byte shift = .
replace shift = 1 if s12_bucket_chg == 1 & s1_sv_agree == 0 & s2_sv_agree == 1
replace shift = 2 if s12_bucket_chg == 1 & s1_sv_agree == 1 & s2_sv_agree == 0
replace shift = 3 if s12_bucket_chg == 1 & s1_sv_agree == 0 & s2_sv_agree == 0
gen byte groups_ok = !missing(s12_bucket_chg)            // cause group assigned at both steps
gen byte agr_ok    = groups_ok & !missing(s1_sv_agree, s2_sv_agree)

* ---------------------------------------------------------------------------
* 2. TABLE 2 (manuscript order)
* ---------------------------------------------------------------------------

* Table 2, "Sites; interview languages": V1 4; 6, V2 7; 5, total 11; 9
foreach v in 1 2 {
    quietly summarize site if version == `v'
    local sites`v' = r(max)
    quietly levelsof lang if version == `v', local(l)
    local nl`v' : word count `l'
}
quietly levelsof lang, local(l)
local nlt : word count `l'
t2row "Sites; interview languages" "`sites1'; `nl1'" "`sites2'; `nl2'" "`=`sites1'+`sites2''; `nlt'" "4; 6" "7; 5" "11; 9"

* Table 2, "Verbal autopsies": 965 / 6952 / 7917
quietly count if version == 1
local n1 = r(N)
quietly count if version == 2
local n2 = r(N)
t2row "Verbal autopsies" "`n1'" "`n2'" "`=_N'" "965" "6952" "7917"

* Table 2, "Coded, n (%)": 949 (98.3%), 6928 (99.7%), 7877 (99.5%)
npct "coded == 1" "1"
t2row "Coded, n (%)" "`r(s1)'" "`r(s2)'" "`r(st)'" "949 (98.3%)" "6928 (99.7%)" "7877 (99.5%)"

* Table 2, "Physician coders": 24, 58, total 79 (three coded in both programmes)
egen byte ctag = tag(version coder) if coder > 0
egen byte catag = tag(coder_all) if coder_all > 0
quietly count if ctag == 1 & version == 1
local k1 = r(N)
quietly count if ctag == 1 & version == 2
local k2 = r(N)
quietly count if catag == 1
local kt = r(N)
t2row "Physician coders" "`k1'" "`k2'" "`kt'" "24" "58" "79"
* Results: "Three physicians coded in both programmes"
bysort coder_all: egen byte cv_min = min(version) if coder_all > 0
bysort coder_all: egen byte cv_max = max(version) if coder_all > 0
quietly count if catag == 1 & cv_min != cv_max
rt "Physicians who coded in both programmes" "3" "`r(N)'"

* Table 2, "Death to interview, days": 114 (54-179), 208 (126-300), 193 (114-289)
* (coded deaths with a valid interval)
medi death_to_interview_d "coded == 1" 0
t2row "Death to interview, days" "`r(s1)'" "`r(s2)'" "`r(st)'" "114 (54–179)" "208 (126–300)" "193 (114–289)"

* Table 2, "Submission to final cause, days": 60 (34-114), 99 (72-133), 96 (68-132)
medi sub_to_final_d "coded == 1" 0
t2row "Submission to final cause, days" "`r(s1)'" "`r(s2)'" "`r(st)'" "60 (34–114)" "99 (72–133)" "96 (68–132)"

* Table 2, "Coding time, min": 5.1 (3.0-8.3), 2.5 (1.6-4.3), total not computed
medi coding_min "coded == 1" 1
t2row "Coding time, min" "`r(s1)'" "`r(s2)'" "··" "5.1 (3.0–8.3)" "2.5 (1.6–4.3)" "··"

* Table 2, "Deaths per coder-day": 7 (4-12), 15 (6-40), total not computed
bysort version coder coded_day: gen pcd = _N if coded == 1 & coder > 0 & _n == 1
medi pcd "1" 0
t2row "Deaths per coder-day" "`r(s1)'" "`r(s2)'" "··" "7 (4–12)" "15 (6–40)" "··"

* Table 2, "Peak deaths coded in a day": 70, 421
bysort version coded_day: gen perday = _N if coded == 1 & _n == 1
quietly summarize perday if version == 1
local pk1 = r(max)
quietly summarize perday if version == 2
local pk2 = r(max)
t2row "Peak deaths coded in a day" "`pk1'" "`pk2'" "··" "70" "421" "··"

* Table 2, "Written narrative >=100 characters": 903 (93.6%), 4354 (62.6%), 5257 (66.4%)
npct "narr_text == 1" "1"
t2row "Written narrative ≥100 characters, n (%)" "`r(s1)'" "`r(s2)'" "`r(st)'" "903 (93.6%)" "4354 (62.6%)" "5257 (66.4%)"

* Table 2, "Written placeholder only": 40 (4.1%), 1206 (17.3%), 1246 (15.7%)
npct "narr_placeholder == 1" "1"
t2row "Written placeholder only, n (%)" "`r(s1)'" "`r(s2)'" "`r(st)'" "40 (4.1%)" "1206 (17.3%)" "1246 (15.7%)"

* Table 2, "Photographed narrative": 110 (11.4%), 3507 (50.4%), 3617 (45.7%)
npct "narr_image == 1" "1"
t2row "Photographed narrative, n (%)" "`r(s1)'" "`r(s2)'" "`r(st)'" "110 (11.4%)" "3507 (50.4%)" "3617 (45.7%)"

* Table 2, "Audio narrative": 10 (1.0%), 433 (6.2%), 443 (5.6%)
npct "narr_audio == 1" "1"
t2row "Audio narrative, n (%)" "`r(s1)'" "`r(s2)'" "`r(st)'" "10 (1.0%)" "433 (6.2%)" "443 (5.6%)"

* Table 2, "Narrative in any form": 955 (99.0%), 6895 (99.2%), 7850 (99.2%)
* (written >=100 characters, photograph or audio; the rest are short statements or none)
npct "narr_any == 1" "1"
t2row "Narrative in any form, n (%)" "`r(s1)'" "`r(s2)'" "`r(st)'" "955 (99.0%)" "6895 (99.2%)" "7850 (99.2%)"

* Table 2, "Medical documents": 127 (13.2%), 490 (7.0%), 617 (7.8%)
npct "docs == 1" "1"
t2row "Medical documents, n (%)" "`r(s1)'" "`r(s2)'" "`r(st)'" "127 (13.2%)" "490 (7.0%)" "617 (7.8%)"

* Table 2, "Flagged difficult to code": 17 (1.8%), 51 (0.7%), 68 (0.9%)
npct "flagged == 1" "1"
t2row "Flagged difficult to code, n (%)" "`r(s1)'" "`r(s2)'" "`r(st)'" "17 (1.8%)" "51 (0.7%)" "68 (0.9%)"

* Table 2, "Recoded": 33 (3.5%), 52 (0.8%), 85 (1.1%) (of coded deaths)
npct "recoded == 1" "coded == 1"
t2row "Recoded, n (%)" "`r(s1)'" "`r(s2)'" "`r(st)'" "33 (3.5%)" "52 (0.8%)" "85 (1.1%)"

* Table 2, "SmartVA result available": 965 (100%), 6932 (99.7%), 7897 (99.7%)
npct "sv_available == 1" "1"
t2row "SmartVA result available, n (%)" "`r(s1)'" "`r(s2)'" "`r(st)'" "965 (100%)" "6932 (99.7%)" "7897 (99.7%)"

* Table 2, "Cause group changed from step 1 to step 2, n/N": 179/944 (19.0%), 674/6914 (9.7%), 853/7858 (10.9%)
npct "s12_bucket_chg == 1" "groups_ok == 1" nN
t2row "Cause group changed from step 1 to step 2, n/N (%)" "`r(s1)'" "`r(s2)'" "`r(st)'" "179/944 (19.0%)" "674/6914 (9.7%)" "853/7858 (10.9%)"

* Table 2, "Of changes, into agreement with SmartVA": 85 (47.5%), 360 (53.4%), 445 (52.2%)
npct "shift == 1" "s12_bucket_chg == 1"
t2row "Of changes, into agreement with SmartVA, n (%)" "`r(s1)'" "`r(s2)'" "`r(st)'" "85 (47.5%)" "360 (53.4%)" "445 (52.2%)"

* Table 2, "Agreement with SmartVA cause group, step 1 -> step 2, %": 37.5 -> 44.2, 44.3 -> 48.4, 43.5 -> 47.9
foreach v in 1 2 t {
    local w = cond("`v'" == "t", "1", "version == `v'")
    quietly summarize s1_sv_agree if agr_ok & `w'
    local a1`v' = string(100 * r(mean), "%4.1f")
    quietly summarize s2_sv_agree if agr_ok & `w'
    local a2`v' = string(100 * r(mean), "%4.1f")
}
t2row "Agreement with SmartVA cause group, step 1 → step 2, %" "`a11' → `a21'" "`a12' → `a22'" "`a1t' → `a2t'" "37.5 → 44.2" "44.3 → 48.4" "43.5 → 47.9"

* Table 2, "Later version from ODK": 964 (99.9%), 107 (1.5%), 1071 (13.5%)
npct "reversioned == 1" "1"
t2row "Later version from ODK, n (%)" "`r(s1)'" "`r(s2)'" "`r(st)'" "964 (99.9%)" "107 (1.5%)" "1071 (13.5%)"

* Table 2, "Edited in ODK Central": 510 (52.8%), 32 (0.5%), 542 (6.8%)
npct "odk_edited == 1" "1"
t2row "Edited in ODK Central, n (%)" "`r(s1)'" "`r(s2)'" "`r(st)'" "510 (52.8%)" "32 (0.5%)" "542 (6.8%)"

* Table 2, "Attachment files": 1648, 15103, 16751
quietly summarize attachments if version == 1
local at1 = r(sum)
quietly summarize attachments if version == 2
local at2 = r(sum)
t2row "Attachment files" "`=string(`at1', "%9.0f")'" "`=string(`at2', "%9.0f")'" "`=string(`at1'+`at2', "%9.0f")'" "1648" "15103" "16751"

* Table 2, "Hosting cost per month, US$, mean (range)": 28 (23-42) (AWS invoices; not in the data sheet)
t2row "Hosting cost per month, US$, mean (range)" "··" "··" "not in data" "··" "··" "28 (23–42)"

* ---------------------------------------------------------------------------
* 3. RESULTS TEXT, paragraph 1 ("Of 7917 verbal autopsies from 11 sites ...")
* ---------------------------------------------------------------------------
* "Of 7917 verbal autopsies from 11 sites, 79 physicians coded 7877 (99.5%)": see table 2.
rt "Verbal autopsies" "7917" "`=_N'"
rt "Sites" "11" "`=`sites1'+`sites2''"
rt "Physicians who coded" "79" "`kt'"
rt "Languages" "9" "`nlt'"

* "Hindi (3444 [43.5%]), Tamil (1301 [16.4%]), Odia (1246 [15.7%]), Khasi (966 [12.2%]), English (469 [5.9%])"
local ms_hindi "3444 [43.5%]"
local ms_tamil "1301 [16.4%]"
local ms_odia "1246 [15.7%]"
local ms_khasi "966 [12.2%]"
local ms_english "469 [5.9%]"
foreach l in hindi tamil odia khasi english {
    quietly count if lang == "`l'"
    rt "Language: `l'" "`ms_`l''" "`r(N)' [`=string(100 * r(N) / _N, "%4.1f")'%]"
}
* "four other languages accounted for 491 (6.2%)": all languages other than the five above
quietly count if !inlist(lang, "hindi", "tamil", "odia", "khasi", "english")
rt "Other languages (n, %)" "491 (6.2%)" "`r(N)' (`=string(100 * r(N) / _N, "%4.1f")'%)"
quietly levelsof lang if !inlist(lang, "hindi", "tamil", "odia", "khasi", "english"), local(ol)
rt "Number of other languages" "4" "`: word count `ol''"

* "median interval from death to interview was 114 days (IQR 54-179) in version 1 and 208 days (126-300) in version 2" (table 2)
* "median interval from submission to final cause was 60 days (34-114) in version 1 and 99 days (72-133) in version 2" (table 2)

* "5915 deaths were coded in April, 2026 [version 2], with a peak of 421 deaths in a day"
quietly count if version == 2 & coded_month == tm(2026m4)
rt "Version 2 deaths coded in April 2026" "5915" "`r(N)'"
rt "Version 2 peak deaths coded in a day" "421" "`pk2'"

* ---------------------------------------------------------------------------
* 4. RESULTS TEXT, paragraph 2 (coding time, workload)
* ---------------------------------------------------------------------------
* "median coding time 5.1 min (IQR 3.0-8.3) in version 1 and 2.5 min (1.6-4.3) in version 2",
* "median of seven deaths (4-12) per coder-day in version 1 and 15 (6-40) in version 2": see table 2.
* "top 10% of coders coded 26% of deaths in version 1 and 44% in version 2 (figure 3)"
preserve
    keep if coded == 1 & coder > 0
    contract version coder, freq(cases)
    gsort version -cases
    by version: gen rank = _n
    by version: gen ncod = _N
    by version: egen tot = total(cases)
    gen byte top10 = rank <= ceil(0.10 * ncod)
    by version: egen top10_cases = total(cases * top10)
    gen share_top10 = 100 * top10_cases / tot
    quietly summarize share_top10 if version == 1
    rt "Share coded by top 10% of coders, version 1 (%)" "26" "`=string(r(mean), "%2.0f")'"
    quietly summarize share_top10 if version == 2
    rt "Share coded by top 10% of coders, version 2 (%)" "44" "`=string(r(mean), "%2.0f")'"
    * Figure 3: deaths coded per coder, ranked
    twoway bar cases rank, barwidth(0.8) color(navy) ///
        by(version, note("") rows(1) xrescale yrescale) ///
        ytitle("Deaths coded") xtitle("Physician coders, ranked by number of deaths coded") ///
        graphregion(color(white))
    graph export "output/figure3_workload.png", width(2400) replace
restore

* ---------------------------------------------------------------------------
* 5. RESULTS TEXT, paragraph 3 (narrative, documents, ill-defined cause)
* ---------------------------------------------------------------------------
* "narrative of at least 100 characters for 5257 (66.4%) deaths: 903 (93.6%) in version 1 and 4354 (62.6%) in version 2": table 2
* "short statements 1072 (13.5%)"
npct "narr_short == 1" "1"
rt "Short statements (<100 characters)" "1072 (13.5%)" "`r(st)'"
* "342 (4.3%) referred to an uploaded photograph"
npct "narr_pointer == 1" "1"
rt "Pointer to uploaded photograph" "342 (4.3%)" "`r(st)'"
* "1246 (15.7%) were empty or placeholders; 1206 of the placeholders were in version 2": table 2
quietly count if narr_placeholder == 1 & version == 2
rt "Placeholders in version 2" "1206" "`r(N)'"
* "photograph attached for 3617 (45.7%) deaths (50.4% in version 2 vs 11.4% in version 1)" and "audio narrative 443 (5.6%)": table 2
* "7850 (99.2%) deaths had a narrative in some form and 44 (0.6%) had none"
npct "narr_none == 1" "1"
rt "No narrative in any form" "44 (0.6%)" "`r(st)'"
* "Medical documents ... 617 (7.8%) (13.2% in version 1 and 7.0% in version 2)": table 2
* "with a median of three pages"
quietly summarize doc_pages if docs == 1, detail
rt "Median document pages" "3" "`r(p50)'"
* "Deaths with documents were more often facility deaths (38.0% vs 20.1%)"
quietly count if docs == 1 & place == 1 & coded == 1
local f1 = r(N)
quietly count if docs == 1 & coded == 1
local f1p = 100 * `f1' / r(N)
quietly count if docs == 0 & place == 1 & coded == 1
local f0 = r(N)
quietly count if docs == 0 & coded == 1
local f0p = 100 * `f0' / r(N)
rt "Facility deaths, with documents vs without (%)" "38.0 vs 20.1" "`=string(`f1p', "%4.1f")' vs `=string(`f0p', "%4.1f")'"
* "ill-defined final cause for 34 (5.5%) of 615 coded deaths with documents and 1509 (20.8%) of 7262 without"
quietly count if ill_defined == 1 & docs == 1 & coded == 1
local i1 = r(N)
quietly count if docs == 1 & coded == 1
local d1 = r(N)
quietly count if ill_defined == 1 & docs == 0 & coded == 1
local i0 = r(N)
quietly count if docs == 0 & coded == 1
local d0 = r(N)
rt "Ill-defined cause, with documents" "34 (5.5%) of 615" "`i1' (`=string(100*`i1'/`d1', "%4.1f")'%) of `d1'"
rt "Ill-defined cause, without documents" "1509 (20.8%) of 7262" "`i0' (`=string(100*`i0'/`d0', "%4.1f")'%) of `d0'"
* "after stratification by programme, age group and place of death, the risk ratio was 0.34 (95% CI 0.25-0.47)"
egen stratum = group(version ageband place) if coded == 1
cs ill_defined docs if coded == 1, by(stratum)
rt "Mantel-Haenszel risk ratio (95% CI)" "0.34 (0.25–0.47)" "`=string(r(rr), "%4.2f")' (`=string(r(lb_rr), "%4.2f")'–`=string(r(ub_rr), "%4.2f")')"
* Appendix S6: crude risk ratio 0.27
cs ill_defined docs if coded == 1
rt "Crude risk ratio (appendix)" "0.27" "`=string(r(rr), "%4.2f")'"
* Appendix S6: 0.35 when the 1246 deaths with an empty or placeholder written narrative are excluded
cs ill_defined docs if coded == 1 & narr_placeholder == 0, by(stratum)
rt "Mantel-Haenszel risk ratio excluding placeholders (appendix)" "0.35" "`=string(r(rr), "%4.2f")'"

* ---------------------------------------------------------------------------
* 6. RESULTS TEXT, paragraph 4 (flags, recoding, later versions, SmartVA, sync)
* ---------------------------------------------------------------------------
* "Coders flagged 68 (0.9%) deaths as difficult to code": table 2
* "48 were coded by the cut-off"
quietly count if flagged == 1 & coded == 1
rt "Flagged deaths coded by the cut-off" "48" "`r(N)'"
* "Final causes were recoded for 85 (1.1%) deaths": table 2
* "the three-character ICD-10 code changed for 26 deaths"
quietly count if recoded_code_chg == 1
rt "Recoded with a changed three-character ICD-10 code" "26" "`r(N)'"
* "A later version arrived from ODK for 1071 (13.5%) submissions, including 542 edited in ODK Central": table 2
* "991 had at least one changed answer (median three fields)"
quietly count if answers_changed == 1
local ac = r(N)
quietly summarize answer_changes if answers_changed == 1, detail
rt "Later version with at least one changed answer" "991" "`ac'"
rt "Median changed fields" "3" "`r(p50)'"
* "In version 1 ... 44 were rejected" (deaths with a rejected version)
quietly count if rejected_versions > 0
rt "Deaths with a rejected later version" "44" "`r(N)'"
* "SmartVA results were available for 7897 (99.7%) deaths; the 20 without a result were not coded"
quietly count if sv_available == 0
rt "Deaths without a SmartVA result" "20" "`r(N)'"
quietly count if sv_available == 0 & coded == 1
rt "Deaths without a SmartVA result that were coded" "0" "`r(N)'"
* "SmartVA failed at least once for 3477 version 2 deaths [April, 2026 batch]"
* sv_failed_any = any failed SmartVA run on the case (any date; reruns later succeeded).
* The manuscript counts failures during the April 2026 batch load; the database
* query for that is: select count(distinct va_sid) from va_smartva_results
*   where va_smartva_outcome = 'failed' and va_smartva_addedat >= '2026-04-01' and < '2026-05-01'
quietly count if sv_failed_any == 1 & version == 2
rt "Version 2 deaths with a failed SmartVA run (any time)" "3477" "`r(N)'"
* "No attachment among the 16 751 files": total, table 2
rt "Attachment files" "16751" "`=string(`at1'+`at2', "%9.0f")'"

* ---------------------------------------------------------------------------
* 7. RESULTS TEXT, paragraph 5 (step 1 versus step 2)
* ---------------------------------------------------------------------------
* "Coders recorded both steps for 7875 (>99.9%) coded deaths"
quietly count if two_step == 1 & coded == 1
local ts = r(N)
rt "Coded deaths with both steps" "7875" "`ts'"
rt "... as % of coded" ">99.9" "`=cond(100 * `ts' / 7877 > 99.9, ">99.9", string(100 * `ts' / 7877, "%5.2f"))'"
* "underlying ICD-10 code changed for 231 (24.3%) in version 1 and 904 (13.1%) in version 2"
npct "s12_code_chg == 1" "two_step == 1"
rt "Underlying ICD-10 code changed, V1" "231 (24.3%)" "`r(s1)'"
rt "Underlying ICD-10 code changed, V2" "904 (13.1%)" "`r(s2)'"
* "cause group for 179 (19.0%) of 944 and 674 (9.7%) of 6914": table 2
* "cause category changed for 141 (14.9%) and 525 (7.6%)"
npct "s12_cat_chg == 1" "groups_ok == 1"
rt "Cause category changed, V1" "141 (14.9%)" "`r(s1)'"
rt "Cause category changed, V2" "525 (7.6%)" "`r(s2)'"
* "Of the 853 group changes, 445 (52.2%) into agreement, 101 (11.8%) out, 307 (36.0%) between two other groups"
npct "shift == 1" "s12_bucket_chg == 1"
rt "Group changes into agreement" "445 (52.2%)" "`r(st)'"
npct "shift == 2" "s12_bucket_chg == 1"
rt "Group changes out of agreement" "101 (11.8%)" "`r(st)'"
npct "shift == 3" "s12_bucket_chg == 1"
rt "Group changes between two other groups" "307 (36.0%)" "`r(st)'"
* "Agreement rose from 37.5% to 44.2% in version 1 (difference 6.7 percentage points, 95% CI 4.5-8.9; McNemar p<0.0001)
*  and from 44.3% to 48.4% in version 2 (4.1, 3.5-4.7; p<0.0001)": Stata mcc difference and interval
local mdiff1 "6.7 pp (4.5–8.9); p<0.0001"
local mdiff2 "4.1 pp (3.5–4.7); p<0.0001"
forvalues v = 1/2 {
    quietly mcc s2_sv_agree s1_sv_agree if agr_ok & version == `v'
    local d = 100 * r(D_f)
    local lo = 100 * r(lb_D_f)
    local hi = 100 * r(ub_D_f)
    local p = cond(chiprob(1, r(chi2)) < 0.0001, "<0.0001", "=" + string(chiprob(1, r(chi2)), "%6.4f"))
    rt "McNemar paired difference, version `v'" "`mdiff`v''" "`=string(`d', "%3.1f")' pp (`=string(`lo', "%3.1f")'–`=string(`hi', "%3.1f")'); p`p'"
}
* "SmartVA assigned an undetermined cause to 213 (22.4%) deaths in version 1 and 2384 (34.4%) in version 2"
npct "sv_undetermined == 1 & coded == 1" "coded == 1"
rt "SmartVA undetermined, V1" "213 (22.4%)" "`r(s1)'"
rt "SmartVA undetermined, V2" "2384 (34.4%)" "`r(s2)'"
* "when SmartVA assigned a cause, agreement rose from 40.1% to 48.2% and from 46.6% to 51.8%"
foreach v in 1 2 {
    quietly summarize s1_sv_agree if agr_ok & version == `v' & sv_undetermined == 0
    local x1 = string(100 * r(mean), "%4.1f")
    quietly summarize s2_sv_agree if agr_ok & version == `v' & sv_undetermined == 0
    local x2 = string(100 * r(mean), "%4.1f")
    rt "Agreement excluding undetermined SmartVA, V`v'" "`=cond(`v'==1, "40.1 → 48.2", "46.6 → 51.8")'" "`x1' → `x2'"
}
* Findings (abstract): "coders changed the cause group for 853 (10.9%) deaths, 445 (52.2%) of them into agreement"
npct "s12_bucket_chg == 1" "groups_ok == 1" nN
rt "Abstract: cause group changed" "853/7858 (10.9%)" "`r(st)'"
* Findings (abstract): medians death to interview 193 (114-289), submission to final 96 (68-132): table 2.

* ---------------------------------------------------------------------------
* 8. APPENDIX: flow of submissions (table S4), missing data (table S6), sensitivity
* ---------------------------------------------------------------------------
* S4 "Not coded by the cut-off": 16, 24, 40
npct "coded == 0" "1"
rt "S4 Not coded, V1" "16" "`r(n1)'"
rt "S4 Not coded, V2" "24" "`r(n2)'"
rt "S4 Not coded, total" "40" "`r(nt)'"
* S4 "No SmartVA result" (among not coded): 20
quietly count if coded == 0 & sv_available == 0
rt "S4 Not coded, no SmartVA result" "20" "`r(N)'"
* S4 "Flagged by a coder as difficult and not coded": 20
quietly count if coded == 0 & flagged == 1
rt "S4 Not coded, flagged" "20" "`r(N)'"
* S4 "Cause group assigned at both steps": 944, 6914, 7858
quietly count if groups_ok == 1 & version == 1
rt "S4 Cause group at both steps, V1" "944" "`r(N)'"
quietly count if groups_ok == 1 & version == 2
rt "S4 Cause group at both steps, V2" "6914" "`r(N)'"
quietly count if groups_ok == 1
rt "S4 Cause group at both steps, total" "7858" "`r(N)'"

* S6 missing data (n=965 version 1, n=6952 version 2)
foreach v in 1 2 {
    quietly count if version == `v' & missing(death_to_interview_d)
    local mi`v'_a = r(N)
    quietly count if version == `v' & missing(s12_code_chg)
    local mi`v'_b = r(N)
    quietly count if version == `v' & missing(s12_bucket_chg)
    local mi`v'_c = r(N)
    quietly count if version == `v' & sv_available == 0
    local mi`v'_d = r(N)
    quietly count if version == `v' & coded == 0
    local mi`v'_e = r(N)
}
rt "S6 Missing: final cause, V1 / V2" "16 / 24" "`mi1_e' / `mi2_e'"
rt "S6 Missing: death to interview, V1 / V2" "2 / 51" "`mi1_a' / `mi2_a'"
rt "S6 Missing: step 1 to step 2 code change, V1 / V2" "16 / 26" "`mi1_b' / `mi2_b'"
rt "S6 Missing: cause group at both steps, V1 / V2" "21 / 38" "`mi1_c' / `mi2_c'"
rt "S6 Missing: SmartVA cause, V1 / V2" "0 / 20" "`mi1_d' / `mi2_d'"

* S6 batch load sensitivity: 6813 version 2 deaths coded on or after April 2, 2026;
* median interval from the load (April 2) to final cause 21 days (IQR 16-26)
gen loadint = coded_day - mdy(4, 2, 2026) if version == 2 & coded_day >= mdy(4, 2, 2026)
quietly summarize loadint, detail
rt "S6 Version 2 deaths coded on/after April 2" "6813" "`r(N)'"
rt "S6 Median days from load to final cause (IQR)" "21 (16–26)" "`=string(r(p50), "%3.0f")' (`=string(r(p25), "%3.0f")'–`=string(r(p75), "%3.0f")')"

* ---------------------------------------------------------------------------
* 9. FIGURE 2: interviews submitted and deaths coded per month
* ---------------------------------------------------------------------------
preserve
    contract version sub_m, freq(submitted)
    rename sub_m month
    tempfile s
    save `s'
restore
preserve
    keep if coded == 1
    contract version coded_month, freq(coded_n)
    rename coded_month month
    merge 1:1 version month using `s', nogenerate
    replace submitted = 0 if missing(submitted)
    replace coded_n = 0 if missing(coded_n)
    sort version month
    twoway (bar submitted month, color(gs11) barwidth(0.8)) ///
           (connected coded_n month, lcolor(navy) mcolor(navy) msize(small)), ///
        by(version, note("") rows(2) yrescale legend(position(6))) ///
        xlabel(`=tm(2025m3)'(2)`=tm(2026m5)', format(%tmMon_CCYY) angle(45)) ///
        xtitle("") ytitle("Number per month") ///
        legend(order(1 "Interviews submitted" 2 "Deaths coded") rows(1)) ///
        graphregion(color(white))
    graph export "output/figure2_monthly.png", width(2400) replace
    list version month submitted coded_n, sepby(version) noobs
restore

* ---------------------------------------------------------------------------
* 10. Synchronisation reliability (ODK sync runs, March 31 to May 31, 2026)
* ---------------------------------------------------------------------------
* "976 (96.8%) of 1008 ODK synchronisation runs completed" (reporting-view
* refreshes, triggered_by analytics_mv, are counted separately)
preserve
    import delimited "data/digitva_ldh_syncruns.csv", varnames(1) clear
    keep if in_window == 1 & triggered_by != "analytics_mv"
    di _n "== ODK synchronisation runs by status, in window"
    tab status
    quietly count
    local runs = r(N)
    quietly count if status == "success"
    rt "ODK sync runs completed, n (%) of runs" "976 (96.8%) of 1008" "`r(N)' (`=string(100 * r(N) / `runs', "%4.1f")'%) of `runs'"
restore

* ---------------------------------------------------------------------------
* 11. Excel output and automatic check
* ---------------------------------------------------------------------------
postclose T2
postclose RT

* Table 2 sheet: laid out like the manuscript
preserve
    use `t2file', clear
    gen match = (c1 == m1 & c2 == m2 & ct == mt) | ct == "not in data"
    rename (item c1 c2 ct) (Indicator Version_1 Version_2 Total)
    putexcel set "output/digitva_ldh_tables.xlsx", sheet("Table 2") replace
    putexcel A1 = ("Indicator") B1 = ("Version 1") C1 = ("Version 2") D1 = ("Total")
    local r = 2
    forvalues i = 1/`=_N' {
        putexcel A`r' = (Indicator[`i']) B`r' = (Version_1[`i']) C`r' = (Version_2[`i']) D`r' = (Total[`i'])
        local ++r
    }
    putexcel A`r' = ("Table 2: Routine-use indicators, versions 1 and 2. Data are n, n (%) or median (IQR). Data cut-off May 31, 2026.")
    putexcel A1:D1, bold

    * Check sheet part 1: every table 2 cell
    tempfile chk1
    rename (Version_1 Version_2 Total) (c1 c2 ct)
    keep Indicator c1 c2 ct m1 m2 mt
    gen long k = _n
    reshape long c m, i(k Indicator) j(col) string
    gen str12 colname = cond(col == "1", "Version 1", cond(col == "2", "Version 2", "Total"))
    rename (Indicator c m) (item computed manuscript)
    replace item = "Table 2: " + item + " [" + colname + "]"
    replace manuscript = subinstr(manuscript, "··", "not reported", .) 
    replace computed = "not reported" if computed == "··"
    replace computed = manuscript if computed == "not in data" 
    keep item manuscript computed k col
    sort k col
    save `chk1'
restore

preserve
    use `rtfile', clear
    putexcel set "output/digitva_ldh_tables.xlsx", sheet("Results text") modify
    putexcel A1 = ("Item") B1 = ("Expected (manuscript)") C1 = ("Computed")
    local r = 2
    forvalues i = 1/`=_N' {
        putexcel A`r' = (item[`i']) B`r' = (manuscript[`i']) C`r' = (computed[`i'])
        local ++r
    }
    putexcel A1:C1, bold
    gen long k = 1000 + _n
    gen str1 col = "x"
    append using `chk1'
    gen str3 match = cond(manuscript == computed, "yes", "no")
    sort k col
    putexcel set "output/digitva_ldh_tables.xlsx", sheet("Check") modify
    putexcel A1 = ("Item") B1 = ("Manuscript") C1 = ("Computed") D1 = ("Match")
    local r = 2
    forvalues i = 1/`=_N' {
        putexcel A`r' = (item[`i']) B`r' = (manuscript[`i']) C`r' = (computed[`i']) D`r' = (match[`i'])
        local ++r
    }
    putexcel A1:D1, bold
    quietly count
    local total = r(N)
    quietly count if match == "yes"
    di _n as result "== CHECK: `r(N)' of `total' manuscript values reproduced"
    di as error "== MISMATCHES (manuscript vs computed)"
    list item manuscript computed if match == "no", noobs clean abbreviate(60) separator(0)
restore

log close
