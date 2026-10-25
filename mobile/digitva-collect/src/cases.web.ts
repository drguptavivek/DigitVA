/**
 * Browser entrypoint for case/registration helpers.
 *
 * Keep the encrypted native case store out of the initial web route graph;
 * the registration rules are intentionally platform-neutral.
 */
export {
  localToday,
  registrationAgeInfoIssue,
  registrationAgeRange,
  registrationNeedsAgeConfirmation,
  validateRegistration,
  visitAt,
  type RegistrationFields,
} from "./registrationRules";
