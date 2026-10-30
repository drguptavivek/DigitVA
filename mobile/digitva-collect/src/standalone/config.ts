/**
 * Path C standalone Collect Plus settings (docs/policy/field-data-collection.md, "Path C"). One place, so the
 * owner can retune a threshold without touching a screen.
 */
/** A standalone record not pushed or backed up for longer than this many days shows an age warning. */
export const STANDALONE_AGE_WARNING_DAYS = 30;

/** The home screen reminds the user to back up every this many days since the last backup (or first record). */
export const BACKUP_REMINDER_DAYS = 7;

/**
 * DigitVA extensions a standalone interview enables: the medical and death document photographs, as in an
 * enrolled project (owner, 2026-10-30). Equity joins once it ships.
 */
export const STANDALONE_DEFAULT_EXTENSIONS: readonly string[] = ["medical_records", "death_summary"];

/** SmartVA form options are explicit and fixed for standalone interviews. */
export const STANDALONE_SMARTVA_DEFAULTS = { hce: true, freetext: true } as const;
