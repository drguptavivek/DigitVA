// Run: node tests/js/doris_rules_check.mjs (no test runner; throws on failure).
// Mirrors tests/services/test_doris_certificate_rules.py for the editor's rules module.
import assert from 'node:assert/strict';
const R = await import(new URL('../../app/static/js/doris_rules.js', import.meta.url));
// Age table shared with tests/services/test_doris_certificate_rules.py (_age_days): keep both in step.
for (const [iso, days] of [['PT30M', 30 / 1440], ['PT90S', 90 / 86400], ['PT23H', 23 / 24], ['P6D', 6], ['P7D', 7], ['P364D', 364], ['P1Y', 365.25], ['PT', null], ['P1H', null], ['abc', null], ['', null]]) {
  const got = R.durationDays(iso);
  if (days === null) assert.equal(got, null, iso); else assert.ok(Math.abs(got - days) < 1e-12, iso);
}
const cert = (age, sex, extra = {}) => ({AdministrativeData: {EstimatedAge: age, Sex: sex}, ...extra});

assert.equal(R.durationDays('P1Y'), 365.25); assert.equal(R.durationDays('PT12H'), 0.5); assert.equal(R.durationDays('P'), null);
// V1 / V2
assert.equal(R.visibility(cert('P11M', 1)).fetal, true); assert.equal(R.visibility(cert('P12M', 1)).fetal, false);
assert.equal(R.visibility(cert('P1Y', 1)).fetal, false); assert.equal(R.visibility(cert(undefined, 1)).fetal, true);
assert.equal(R.visibility(cert('P6D', 1)).within24, true); assert.equal(R.visibility(cert('P7D', 1)).within24, false);
assert.equal(R.visibility(cert('P1D', 1, {FetalOrInfantDeath: {Stillborn: 1}})).within24, false);
// V3
assert.deepEqual([1, 2, 9, undefined].map(s => R.visibility(cert('P30Y', s)).maternal), [false, true, false, false]);
assert.equal(R.visibility(cert('P30Y', 2, {MaternalDeath: {WasPregnant: 0}})).pregnancyFollowup, false);
// V4 V5 V6
assert.equal(R.visibility(cert('P30Y', 1, {Surgery: {WasPerformed: 9}})).surgeryDetail, false);
assert.equal(R.visibility(cert('P30Y', 1, {Autopsy: {WasRequested: 1}})).autopsyFindings, true);
assert.deepEqual([0, 1, 2, 3, 4, 5, 6, 7, 9, undefined].map(m => R.visibility(cert('P30Y', 1, {MannerOfDeath: {MannerOfDeath: m}})).external),
  [false, true, true, true, true, true, true, true, false, false]);
// dropHidden removes exactly the hidden keys and never mutates the input
const full = cert('P40Y', 1, {FetalOrInfantDeath: {BirthWeight: 2000}, MaternalDeath: {WasPregnant: 1}, Surgery: {WasPerformed: 0, Date: '2025-01-01', Reason: 'x'},
  Autopsy: {WasRequested: 0, Findings: 1}, MannerOfDeath: {MannerOfDeath: 0, DescriptionExternalCause: 'x', PlaceOfOccuranceExternalCause: 1}});
const kept = R.dropHidden(full);
// pregnancy follow-ups go unless WasPregnant is Yes
const mat = (m) => R.dropHidden(cert('P30Y', 2, {MaternalDeath: m})).MaternalDeath;
assert.deepEqual(mat({WasPregnant: 1, TimeFromPregnancy: 0, PregnancyContribute: 1}), {WasPregnant: 1, TimeFromPregnancy: 0, PregnancyContribute: 1});
assert.deepEqual(mat({WasPregnant: 0, TimeFromPregnancy: 0, PregnancyContribute: 1}), {WasPregnant: 0});
assert.deepEqual(mat({WasPregnant: 9, TimeFromPregnancy: 0}), {WasPregnant: 9});
assert.equal(mat({TimeFromPregnancy: 0}), undefined);
// N/A notes
assert.match(R.NOT_APPLICABLE.fetal, /not a fetal or infant death$/);
assert.match(R.NOT_APPLICABLE.maternalMale, /is male$/); assert.match(R.NOT_APPLICABLE.maternal, /is not female$/);
assert.deepEqual(kept, {AdministrativeData: {EstimatedAge: 'P40Y', Sex: 1}, Surgery: {WasPerformed: 0}, Autopsy: {WasRequested: 0}, MannerOfDeath: {MannerOfDeath: 0}});
assert.ok(full.FetalOrInfantDeath && full.MaternalDeath);
// V9 greying and warnings
assert.deepEqual(R.oversizedUnits(cert('P3D', 1)), ['Y', 'M', 'W']); assert.deepEqual(R.oversizedUnits(cert(undefined, 1)), []);
const msgs = (c, ctx) => R.warnings(c, ctx).map(w => w.path + ': ' + w.message);
assert.deepEqual(msgs(cert('P2D', 1), {intervals: [{key: 0, iso: 'P3D', part1: true}]}), ['interval:0: Interval is longer than the age at death']);
assert.deepEqual(msgs(cert('P40Y', 1), {intervals: [{key: 0, iso: 'P5Y', part1: true}, {key: 1, iso: 'P2Y', part1: true}, {key: 2, iso: 'P2Y', part1: true}]}), ['interval:1: Usually longer than the line above']);
assert.deepEqual(msgs(cert('P40Y', 1), {intervals: [{key: 0, iso: 'P5Y', part1: true}, {key: 'p2', iso: 'P1Y', part1: false}]}), []);
// V3 age band, V10, V11
assert.deepEqual(msgs(cert('P9Y', 2, {MaternalDeath: {WasPregnant: 1}})), ['MaternalDeath.WasPregnant: Pregnancy is unusual at this age']);
assert.deepEqual(msgs(cert('P54Y', 2, {MaternalDeath: {WasPregnant: 1}})), []); assert.equal(msgs(cert('P55Y', 2, {MaternalDeath: {WasPregnant: 1}})).length, 1);
assert.equal(msgs(cert('P55Y', 2, {MaternalDeath: {WasPregnant: 0}})).length, 0);
const dates = (b, d, extra = {}) => ({AdministrativeData: {DateBirth: b, DateDeath: d, Sex: 1, ...extra}});
assert.deepEqual(msgs(dates('2025-05-02', '2025-05-01')), ['AdministrativeData.DateBirth: Date of birth is after the date of death']);
assert.deepEqual(msgs(dates('2025', '2025-05-01')), []);
assert.deepEqual(msgs(dates('2000', '2999-01-01'), {today: '2026-10-12'}), ['AdministrativeData.DateDeath: Date of death is in the future']);
assert.deepEqual(msgs(dates('2000-01-01', '2020-01-01', {EstimatedAge: 'P40Y'})), ['AdministrativeData.EstimatedAge: Estimated age differs from the dates by more than a year']);
assert.deepEqual(msgs(dates('2000-01-01', '2020-01-01', {EstimatedAge: 'P20Y'})), []);
const injury = (date) => ({...dates('2000-01-01', '2020-01-01'), MannerOfDeath: {MannerOfDeath: 1, DateOfExternalCauseOrPoisoning: date}});
assert.equal(msgs(injury('1999-12-31')).length, 1); assert.equal(msgs(injury('2020-01-02')).length, 1); assert.equal(msgs(injury('2010-06')).length, 0);
const surgery = (date) => ({...dates('2000-01-01', '2020-01-30'), Surgery: {WasPerformed: 1, Date: date}});
assert.equal(msgs(surgery('2020-01-02')).length, 0); assert.equal(msgs(surgery('2020-01-01')).length, 1); assert.equal(msgs(surgery('2020-01-31')).length, 1);
// partial precision: compared at the coarser of the two; surgery needs a full surgery date and a full death date
assert.equal(msgs(surgery('2020-01')).length, 0); assert.equal(msgs(surgery('2019')).length, 0);
assert.equal(msgs({...dates('2000-01-01', '2020'), Surgery: {WasPerformed: 1, Date: '2019-01-01'}}).length, 0);
assert.equal(msgs({...dates('2000-01-01', '2020-01-30'), Surgery: {WasPerformed: 0, Date: '2015-01-01'}}).length, 0);
assert.equal(msgs(injury('2021')).length, 1); assert.equal(msgs(injury('2020')).length, 0); assert.equal(msgs(injury('1999')).length, 1); assert.equal(msgs(injury('2000')).length, 0);
assert.equal(msgs(injury('2020-02')).length, 1); assert.equal(msgs(injury('2020-01')).length, 0);
assert.deepEqual(msgs(dates('2021', '2020-06-01')), ['AdministrativeData.DateBirth: Date of birth is after the date of death']);
assert.deepEqual(msgs(dates('2020-07', '2020-06-30')), ['AdministrativeData.DateBirth: Date of birth is after the date of death']);
assert.deepEqual(msgs(dates('2020-06', '2020-06-30')), []);
// date of death is a full date; a saved partial one still compares at its own precision
assert.deepEqual(msgs(dates('2000', '2999-01-01'), {today: '2026-10-12'}), ['AdministrativeData.DateDeath: Date of death is in the future']);
assert.deepEqual(msgs(dates('2000', '2026-10-12'), {today: '2026-10-12'}), []);
assert.deepEqual(msgs(dates('2000', '2026'), {today: '2026-10-12'}), []); assert.equal(msgs(dates('2000', '2027'), {today: '2026-10-12'}).length, 1);
const baby = (fetal) => cert('P2D', 1, {FetalOrInfantDeath: fetal});
assert.equal(msgs(baby({BirthWeight: 199})).length, 1); assert.equal(msgs(baby({BirthWeight: 200, PregnancyWeeks: 20, AgeMother: 10})).length, 0);
assert.equal(msgs(baby({BirthWeight: 7001, PregnancyWeeks: 46, AgeMother: 61, DeathWithin24h: 25})).length, 4);
// no warnings for a hidden control's stale value
assert.equal(msgs(cert('P40Y', 1, {FetalOrInfantDeath: {BirthWeight: 1}})).length, 0);
console.log('doris_rules ok');
