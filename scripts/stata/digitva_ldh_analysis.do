* =============================================================================
* DigitVA: routine use of versions 1 and 2 (Lancet Digital Health manuscript)
* Reproduces table 2, the documents-ill-defined-cause risk ratio and figures 2-3.
*
* Inputs (de-identified, git-ignored; built by scripts/stata/digitva_ldh_export.sql):
*   private/ldh-analysis/digitva_ldh_cases.csv     one row per verbal autopsy
*   private/ldh-analysis/digitva_ldh_syncruns.csv  one row per synchronisation run
* Data cut-off: May 31, 2026.
* Run from the repository root:
*   /Applications/Stata/StataSE.app/Contents/MacOS/stata-se -b do scripts/stata/digitva_ldh_analysis.do
* =============================================================================
version 17
clear all
set more off
local in  "private/ldh-analysis"
local out "private/ldh-analysis/output"
capture mkdir "`out'"
capture log close
log using "`out'/digitva_ldh_analysis.log", replace text

* ---------------------------------------------------------------------------
* 1. Load and label
* ---------------------------------------------------------------------------
import delimited "`in'/digitva_ldh_cases.csv", varnames(1) clear stringcols(3 4 9)

label define version 1 "Version 1 (UNSW)" 2 "Version 2 (ICMR)"
label values version version
label define ageband 0 "Unknown" 1 "<15 years" 2 "15-69 years" 3 ">=70 years"
label values ageband ageband
label define place 1 "Health facility" 2 "Home" 3 "Other or unknown"
label values place place

* Derived indicators
label define narr_class 0 "Empty or placeholder" 1 "Pointer to uploaded photo" 2 "Short statement (<100 characters)" 3 "Narrative (>=100 characters)"
label values narr_class narr_class
gen byte narr_text    = narr_class == 3
gen byte narr_any     = narr_class == 3 | narr_image | narr_audio
gen byte narr_short_only = narr_class == 2 & !narr_image & !narr_audio
gen byte narr_none    = narr_class <= 1 & !narr_image & !narr_audio
gen byte docs         = doc_pages > 0
gen byte reversioned  = payload_versions > 1
gen byte answers_changed = answer_changes > 0
gen coded_day = date(coded_date, "YMD")
format coded_day %td
gen coded_month = mofd(coded_day)
gen sub_m = monthly(sub_month, "YM")
format coded_month sub_m %tm

* Interval guards as in the manuscript Methods: 0 to 3650 days
replace death_to_interview_d = . if death_to_interview_d < 0 | death_to_interview_d > 3650
replace sub_to_final_d = . if sub_to_final_d < 0

label var version              "Platform version"
label var coded                "Coded (active final assessment)"
label var death_to_interview_d "Death to interview, days"
label var sub_to_final_d       "Submission to final cause, days"
label var coding_min           "Coding time (allocation to final), min"
label var narr_text            "Written narrative (>=100 characters)"
label var narr_any             "Narrative in any form (written, photo or audio)"
label var narr_short_only      "Short statement only, no photo or audio"
label var narr_none            "No narrative in any form"
label var narr_image           "Photographed narrative"
label var narr_audio           "Audio narrative"
label var docs                 "Medical documents attached"
label var ill_defined          "Ill-defined final cause (ICD-10 R00-R99)"
label var flagged              "Flagged difficult to code"
label var recoded              "Final cause recoded"
label var reversioned          "Later version received from ODK"
label var odk_edited           "Edited in ODK Central (new instance ID)"
label var answers_changed      "Questionnaire answers changed in later version"

* ---------------------------------------------------------------------------
* 2. Table 2: reach, coverage and data capture
* ---------------------------------------------------------------------------
di _n "== Verbal autopsies and coding coverage"
tab version coded, row
egen byte coder_tag = tag(version coder) if coder > 0
di _n "== Physician coders per version"
tab version if coder_tag == 1
* Coders across both versions cannot be pooled from per-version pseudonyms;
* the distinct total (79) comes from the database (three coders worked in both).

di _n "== Interview languages, n (%)"
tab lang, sort
tab lang version, col

di _n "== Narrative and document capture, n (%)"
tab narr_class version, col
foreach v in narr_text narr_image narr_audio narr_any narr_short_only narr_none docs flagged reversioned odk_edited answers_changed {
    di _n "-- `: var label `v''"
    tab `v' version, col
}
tabstat narr_chars if narr_text, by(version) stat(p50 p25 p75) format(%9.0f)
tabstat doc_pages if docs, by(version) stat(p50 p25 p75 max) format(%9.0f)
tab rejected_versions version if rejected_versions > 0
tabstat answer_changes if answers_changed, by(version) stat(p50 p25 p75) format(%9.0f)
tabstat attachments, by(version) stat(sum) format(%12.0fc)

di _n "== SmartVA: see the database query in the export notes"
di _n "== Recoded among coded deaths"
tab recoded version if coded, col

* ---------------------------------------------------------------------------
* 2b. SmartVA and coder behaviour: masked Step 1 vs Step 2 (SmartVA shown)
*     Cause compared by WHO 2022 VA cause bucket (field) and its category.
* ---------------------------------------------------------------------------
label var s12_bucket_chg "Cause bucket changed from Step 1 to Step 2"
label var s12_cat_chg    "Cause category changed from Step 1 to Step 2"
label var s12_code_chg   "Underlying ICD-10 code changed from Step 1 to Step 2"
label var s1_sv_agree    "Step 1 bucket = SmartVA bucket"
label var s2_sv_agree    "Step 2 bucket = SmartVA bucket"
gen byte shift = .
replace shift = 1 if s12_bucket_chg == 1 & s1_sv_agree == 0 & s2_sv_agree == 1
replace shift = 2 if s12_bucket_chg == 1 & s1_sv_agree == 1 & s2_sv_agree == 0
replace shift = 3 if s12_bucket_chg == 1 & s1_sv_agree == 0 & s2_sv_agree == 0
label define shift 1 "Into agreement with SmartVA" 2 "Out of agreement with SmartVA" 3 "Between two other buckets"
label values shift shift
di _n "== Deaths with both steps recorded"
tab version two_step if coded, row
foreach v in s12_code_chg s12_bucket_chg s12_cat_chg s1_sv_agree s2_sv_agree {
    di _n "-- `: var label `v''"
    tab `v' version if two_step, col
}
di _n "== Direction of bucket changes"
tab shift version if two_step, col
di _n "== SmartVA undetermined (R code)"
tab sv_undetermined version if two_step, col
* Paired change in agreement with SmartVA (McNemar), all deaths and
* deaths where SmartVA assigned a cause
forvalues v = 1/2 {
    di _n "-- Version `v': all two-step deaths"
    mcc s2_sv_agree s1_sv_agree if two_step & version == `v'
    di _n "-- Version `v': SmartVA assigned a cause"
    mcc s2_sv_agree s1_sv_agree if two_step & version == `v' & sv_undetermined == 0
}

* ---------------------------------------------------------------------------
* 3. Timeliness and coding time: median (IQR)
* ---------------------------------------------------------------------------
di _n "== Intervals, median (IQR)"
foreach v in death_to_interview_d sub_to_final_d coding_min {
    di _n "-- `: var label `v''"
    tabstat `v' if coded, by(version) stat(n p50 p25 p75) format(%9.1f)
}

* ---------------------------------------------------------------------------
* 4. Throughput and workload
* ---------------------------------------------------------------------------
preserve
    keep if coded
    * deaths per coder-day
    contract version coder coded_day, freq(per_coder_day)
    di _n "== Deaths coded per coder-day, median (IQR)"
    tabstat per_coder_day, by(version) stat(n p50 p25 p75) format(%9.0f)
restore
preserve
    keep if coded
    contract version coded_day, freq(per_day)
    di _n "== Deaths coded per calendar day: peak"
    tabstat per_day, by(version) stat(max n) format(%9.0f)
restore
preserve
    keep if coded
    contract version coder, freq(cases)
    di _n "== Deaths per coder, median (IQR), max"
    tabstat cases, by(version) stat(n p50 p25 p75 max) format(%9.0f)
    * share of deaths coded by the top 10% of coders
    gsort version -cases
    by version: gen rank = _n
    by version: gen ncod = _N
    by version: egen tot = total(cases)
    gen byte top10 = rank <= ceil(0.10 * ncod)
    by version: egen top10_cases = total(cases * top10)
    gen share_top10 = 100 * top10_cases / tot
    di _n "== Share of deaths coded by the top 10% of coders (%)"
    tabstat share_top10, by(version) stat(mean) format(%9.1f)

    * Figure 3: deaths coded per coder, ranked
    twoway bar cases rank, barwidth(0.8) color(navy) ///
        by(version, note("") rows(1) xrescale yrescale) ///
        ytitle("Deaths coded") xtitle("Physician coders, ranked by number of deaths coded") ///
        graphregion(color(white))
    graph export "`out'/figure3_workload.png", width(2400) replace
restore

* ---------------------------------------------------------------------------
* 5. Medical documents and ill-defined final cause
*    Mantel-Haenszel risk ratio stratified by version, age band and place of death
* ---------------------------------------------------------------------------
di _n "== Ill-defined final cause by documents (coded deaths)"
tab docs ill_defined if coded, row
tab place docs if coded, col
egen stratum = group(version ageband place) if coded
cs ill_defined docs if coded, by(stratum)
* Crude, for comparison
cs ill_defined docs if coded

* ---------------------------------------------------------------------------
* 6. Figure 2: interviews submitted and deaths coded per month
* ---------------------------------------------------------------------------
preserve
    contract version sub_m, freq(submitted)
    rename sub_m month
    tempfile s
    save `s'
restore
preserve
    keep if coded
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
    graph export "`out'/figure2_monthly.png", width(2400) replace
    list version month submitted coded_n, sepby(version) noobs
restore

* ---------------------------------------------------------------------------
* 7. Synchronisation reliability (ODK sync runs; reporting-view refreshes apart)
* ---------------------------------------------------------------------------
import delimited "`in'/digitva_ldh_syncruns.csv", varnames(1) clear
gen byte odk_sync = triggered_by != "analytics_mv"
label define odk 0 "Reporting-view refresh" 1 "ODK synchronisation"
label values odk_sync odk
di _n "== Synchronisation runs by status, March 31 to May 31, 2026"
tab status odk_sync, col

log close
