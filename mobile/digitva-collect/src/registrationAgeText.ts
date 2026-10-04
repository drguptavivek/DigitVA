import { t } from "./i18n";
import { sameRegistrationAgeParts, type RegistrationAgeDisplay, type RegistrationAgeParts } from "./registrationAgeDisplay";

function sameCalendarUnits(left: RegistrationAgeParts, right: RegistrationAgeParts): boolean {
  return left.years === right.years && left.months === right.months;
}

function hasCalendarUnits(value: RegistrationAgeParts): boolean {
  return value.years > 0 || value.months > 0;
}

/**
 * Localise the calculated age without hiding a meaningful day-only result.
 * Calendar ages for adults stay concise; newborn and partial ranges retain
 * days when the calendar units alone would misleadingly read as zero months.
 */
export function formatRegistrationAge(display: RegistrationAgeDisplay): string {
  const { min, max } = display;
  if (display.exact) {
    if (display.kind === "days") return t("ageAtDeathCalculatedDays", { days: min.days });
    if (!hasCalendarUnits(min)) {
      return t("ageAtDeathCalculatedFull", { years: min.years, months: min.months, days: min.days });
    }
    return t("ageAtDeathCalculated", { years: min.years, months: min.months });
  }

  const sameUnits = sameCalendarUnits(min, max);
  const sameParts = sameRegistrationAgeParts(min, max);
  if (sameUnits && !sameParts) {
    return t("ageAtDeathFullRange", {
      minYears: min.years,
      minMonths: min.months,
      minDays: min.days,
      maxYears: max.years,
      maxMonths: max.months,
      maxDays: max.days
    });
  }
  if (display.kind === "days") {
    if (min.days === max.days) return t("ageAtDeathEstimatedDays", { days: min.days });
    return t("ageAtDeathDaysRange", { minDays: min.days, maxDays: max.days });
  }
  if (sameParts) {
    if (!hasCalendarUnits(min)) {
      return t("ageAtDeathEstimatedFull", { years: min.years, months: min.months, days: min.days });
    }
    return t("ageAtDeathEstimated", { years: min.years, months: min.months });
  }
  if (display.kind === "mixed") {
    return t("ageAtDeathMixedRange", {
      minDays: min.days,
      maxYears: max.years,
      maxMonths: max.months,
      maxDays: max.days
    });
  }
  return t("ageAtDeathRange", {
    minYears: min.years,
    minMonths: min.months,
    maxYears: max.years,
    maxMonths: max.months
  });
}
