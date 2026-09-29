// Possible-duplicate banner of the web intake form (phase 6, digitva-vzk.11).
// A warning only: the interviewer may still submit. The flag button sends the
// existing duplicate flag, which a supervisor confirms or rejects; nothing is
// ever merged. Case details are set as text, never as markup.

// The answers the case's identity is synced from (web_intake_service
// _identity_from_answers): names, sex, date of death and the answers it is
// calculated from.
export const IDENTITY_QUESTIONS = ["Id10017", "Id10018", "Id10019", "Id10023", "Id10023_a", "Id10023_b"];

// Whether a save of *changed* (section name -> answers) touched the identity.
export function touchesIdentity(changed, sectionOf) {
  return IDENTITY_QUESTIONS.some((q) => sectionOf.has(q) && sectionOf.get(q) in changed);
}

export function renderPossibleDuplicates(box, cases, onFlag) {
  box.replaceChildren();
  if (!cases.length) { box.classList.add("d-none"); return; }
  const title = document.createElement("div");
  title.className = "fw-semibold mb-1";
  title.textContent = "Possible duplicate of " + cases.map((c) => c.unique_id).join(", ");
  const list = document.createElement("ul");
  list.className = "mb-1 ps-3";
  for (const c of cases) {
    const item = document.createElement("li");
    // Id, unit and state only: the hint never shows the other case's identity
    // (docs/policy/web-intake.md, "Duplicate and cancel flags").
    item.append([c.unique_id, c.unit_name || "no unit", c.state].join(" · ") + " ");
    const flag = document.createElement("button");
    flag.type = "button";
    flag.className = "btn btn-sm btn-outline-dark py-0";
    flag.textContent = "Flag as duplicate of " + c.unique_id;
    flag.addEventListener("click", () => onFlag(c, flag));
    item.append(flag);
    list.append(item);
  }
  const note = document.createElement("div");
  note.textContent = "You may still continue and submit. A flag goes to a supervisor to confirm or reject.";
  box.append(title, list, note);
  box.classList.remove("d-none");
}
