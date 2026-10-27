/**
 * Path C standalone Collect Plus settings (docs/policy/field-data-collection.md, "Path C"). One place, so the
 * owner can retune a threshold without touching a screen.
 */
/** A standalone record not pushed or backed up for longer than this many days shows an age warning. */
export const STANDALONE_AGE_WARNING_DAYS = 30;

/** The home screen reminds the user to back up every this many days since the last backup (or first record). */
export const BACKUP_REMINDER_DAYS = 7;

/** DigitVA extensions a standalone interview enables; the owner default is none (equity joins once it ships). */
export const STANDALONE_DEFAULT_EXTENSIONS: readonly string[] = [];
