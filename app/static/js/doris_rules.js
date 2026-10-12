// DORIS certificate field rules V1-V11. Pure ES module, no DOM, no globals.
// Source of truth: docs/policy/doris-certificate-rules.md (the Expo editor
// ports the same spec; the server mirrors the hide rules in
// drop_inapplicable_sections). visibility() says what V1-V6 show, dropHidden()
// strips the keys of everything hidden, warnings() are soft and never block.
'use strict';

export var PREGNANCY_AGE_BAND = [10, 54];
var DAY_MS = 86400000;
var UNIT_DAYS = {Y: 365.25, M: 30.4375, W: 7, D: 1, H: 1 / 24, MI: 1 / 1440, S: 1 / 86400};

// ISO duration (P65Y, P3D, PT5H, PT30M) -> days, or null when blank or odd.
export function durationDays(iso) {
  var m = typeof iso === 'string' ? iso.trim().match(/^P(?:(\d+(?:\.\d+)?)([YMWD]))?(?:T(\d+(?:\.\d+)?)([HMS]))?$/) : null;
  if (!m || !(m[1] || m[3])) return null;
  var days = 0;
  if (m[1]) days += Number(m[1]) * UNIT_DAYS[m[2]];
  if (m[3]) days += Number(m[3]) * UNIT_DAYS[m[4] === 'M' ? 'MI' : m[4]];
  return days;
}

// "2025", "2025-03" or "2025-03-04" -> [y, m|null, d|null], else null.
export function parseDate(value) {
  var m = typeof value === 'string' ? value.trim().match(/^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$/) : null;
  return m ? [Number(m[1]), m[2] ? Number(m[2]) : null, m[3] ? Number(m[3]) : null] : null;
}

function utcDay(parts) { return Date.UTC(parts[0], parts[1] - 1, parts[2]) / DAY_MS; }
function isFull(parts) { return Boolean(parts && parts[1] && parts[2]); }

// Compare at the coarser precision of the two dates: -1, 0, 1, or null.
function compareDates(a, b) {
  if (!a || !b) return null;
  for (var i = 0; i < 3; i += 1) {
    if (a[i] === null || b[i] === null) return 0;
    if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1;
  }
  return 0;
}

function section(cert, name) { return cert && cert[name] && typeof cert[name] === 'object' ? cert[name] : {}; }

// Age at death in days: the estimated age only (null when blank).
export function ageInDays(cert) { return durationDays(section(cert, 'AdministrativeData').EstimatedAge); }

// Text of the not-applicable note a hidden whole card shows in place of its
// fields (docs/policy/doris-certificate-rules.md, "N/A note").
export var NOT_APPLICABLE = {
  fetal: 'This section is not applicable when it is not a fetal or infant death',
  maternalMale: 'This section is not applicable when the selected sex is male',
  maternal: 'This section is not applicable when the selected sex is not female'
};

// What V1-V6 show. An unknown age hides nothing by age; sex must be Female.
export function visibility(cert) {
  var days = ageInDays(cert);
  var manner = section(cert, 'MannerOfDeath').MannerOfDeath;
  return {
    fetal: days === null || days < 365,
    within24: (days === null || days < 7) && section(cert, 'FetalOrInfantDeath').Stillborn !== 1,
    maternal: section(cert, 'AdministrativeData').Sex === 2,
    pregnancyFollowup: section(cert, 'MaternalDeath').WasPregnant === 1,
    surgeryDetail: section(cert, 'Surgery').WasPerformed === 1,
    autopsyFindings: section(cert, 'Autopsy').WasRequested === 1,
    external: typeof manner === 'number' && manner >= 1 && manner <= 7
  };
}

// [visibility flag, section, keys to drop (null = whole section)]
var HIDES = [
  ['fetal', 'FetalOrInfantDeath', null], ['within24', 'FetalOrInfantDeath', ['DeathWithin24h']],
  ['maternal', 'MaternalDeath', null], ['pregnancyFollowup', 'MaternalDeath', ['TimeFromPregnancy', 'PregnancyContribute']],
  ['surgeryDetail', 'Surgery', ['Date', 'Reason']],
  ['autopsyFindings', 'Autopsy', ['Findings']],
  ['external', 'MannerOfDeath', ['DateOfExternalCauseOrPoisoning', 'DescriptionExternalCause', 'PlaceOfOccuranceExternalCause']]
];

// Copy of the certificate without the keys of every hidden control.
export function dropHidden(cert) {
  var out = JSON.parse(JSON.stringify(cert));
  var shown = visibility(cert);
  HIDES.forEach(function (hide) {
    var name = hide[1];
    if (shown[hide[0]] || !out[name]) return;
    if (hide[2]) hide[2].forEach(function (key) { delete out[name][key]; }); else out[name] = {};
    if (!Object.keys(out[name]).length) delete out[name];
  });
  return out;
}

// Interval unit codes (Y M W D H MI S) longer than the age at death: V9 greying.
export function oversizedUnits(cert) {
  var days = ageInDays(cert);
  if (days === null || days <= 0) return [];
  return Object.keys(UNIT_DAYS).filter(function (unit) { return UNIT_DAYS[unit] > days; });
}

function outside(value, low, high) { return typeof value === 'number' && (value < low || value > high); }

// Soft warnings: [{path, message}]. ctx.today is the user's local ISO day;
// ctx.intervals is [{key, iso, part1}] for the filled lines in screen order.
// A path is "Section.Field", or "interval:<key>" for a line's interval.
export function warnings(cert, ctx) {
  var out = [];
  var warn = function (path, message) { out.push({path: path, message: message}); };
  var admin = section(cert, 'AdministrativeData'); var fetal = section(cert, 'FetalOrInfantDeath');
  var days = ageInDays(cert); var shown = visibility(cert);
  var birth = parseDate(admin.DateBirth); var death = parseDate(admin.DateDeath);

  if (shown.maternal && section(cert, 'MaternalDeath').WasPregnant === 1 && days !== null &&
      (days < PREGNANCY_AGE_BAND[0] * 365.25 || days >= (PREGNANCY_AGE_BAND[1] + 1) * 365.25)) {
    warn('MaternalDeath.WasPregnant', 'Pregnancy is unusual at this age');
  }
  if (compareDates(birth, death) === 1) warn('AdministrativeData.DateBirth', 'Date of birth is after the date of death');
  if (compareDates(death, parseDate(ctx && ctx.today)) === 1) warn('AdministrativeData.DateDeath', 'Date of death is in the future');
  if (shown.external) {
    var injury = parseDate(section(cert, 'MannerOfDeath').DateOfExternalCauseOrPoisoning);
    if (compareDates(injury, birth) === -1 || compareDates(injury, death) === 1) {
      warn('MannerOfDeath.DateOfExternalCauseOrPoisoning', 'Date of injury is outside birth to death');
    }
  }
  if (shown.surgeryDetail) {
    var surgery = parseDate(section(cert, 'Surgery').Date);
    if (isFull(surgery) && isFull(death)) {
      var gap = utcDay(death) - utcDay(surgery);
      if (gap < 0 || gap > 28) warn('Surgery.Date', 'Outside the 4 weeks before death');
    }
  }
  if (days !== null && isFull(birth) && isFull(death) && Math.abs(days - (utcDay(death) - utcDay(birth))) > 365.25) {
    warn('AdministrativeData.EstimatedAge', 'Estimated age differs from the dates by more than a year');
  }
  if (shown.fetal) {
    if (outside(fetal.BirthWeight, 200, 7000)) warn('FetalOrInfantDeath.BirthWeight', 'Unusual birth weight (200 to 7000 g)');
    if (outside(fetal.PregnancyWeeks, 20, 45)) warn('FetalOrInfantDeath.PregnancyWeeks', 'Unusual number of weeks (20 to 45)');
    if (outside(fetal.AgeMother, 10, 60)) warn('FetalOrInfantDeath.AgeMother', 'Unusual age of mother (10 to 60)');
    if (shown.within24 && outside(fetal.DeathWithin24h, 0, 24)) warn('FetalOrInfantDeath.DeathWithin24h', 'Hours survived should be 0 to 24');
  }
  var above = null;
  ((ctx && ctx.intervals) || []).forEach(function (entry) {
    var interval = durationDays(entry.iso);
    if (interval === null) return;
    if (days !== null && interval > days) warn('interval:' + entry.key, 'Interval is longer than the age at death');
    else if (entry.part1 && above !== null && interval < above) warn('interval:' + entry.key, 'Usually longer than the line above');
    if (entry.part1) above = interval;
  });
  return out;
}
