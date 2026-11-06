/**
 * A project name for display. Servers store some names in capitals ("GUJARAT HEALTH SYSTEM"), which shouts on a
 * phone: an all-capitals name is title-cased ("Gujarat Health System"); any name with a lower-case letter, or in a
 * script without case (Hindi), is shown as stored.
 * ponytail: words of up to 3 letters and words with digits stay capitals (PHC, CHC, UP, AIIMS01), but a longer
 * acronym in an all-capitals name ("AIIMS DELHI") becomes "Aiims Delhi"; store the proper name on the server to fix.
 */
const SMALL_WORDS = new Set(["OF", "AND", "THE", "FOR", "IN", "AT"]);

export function displayProjectName(name: string | undefined): string {
  if (!name) return "";
  if (name !== name.toLocaleUpperCase() || name === name.toLocaleLowerCase()) return name;
  return name
    .split(" ")
    .map((word, index) => {
      if (index > 0 && SMALL_WORDS.has(word)) return word.toLocaleLowerCase();
      if (word.length <= 3 || /\d/.test(word)) return word;
      return word.charAt(0) + word.slice(1).toLocaleLowerCase();
    })
    .join(" ");
}
