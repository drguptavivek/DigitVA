// Drives the contact form's slide-to-slot puzzle: the native range input moves
// the piece across the picture (keyboard and touch come with the input), and
// the position plus coarse telemetry (time from first move, number of moves)
// fill the slide_* hidden fields. All values are viewBox units; the server
// decides (app/services/slide_captcha_service.py).
(function () {
  "use strict";

  const form = document.getElementById("login-email-form");
  const range = document.getElementById("slide-captcha-range");
  const piece = document.getElementById("slide-captcha-piece");
  if (!form || !range || !piece) return;

  const statusEl = document.getElementById("captcha-status");
  let startedAt = null;
  let moves = 0;

  function fillField(name, value) {
    const field = form.querySelector(`[name="${name}"]`);
    if (field) field.value = value;
  }

  range.addEventListener("input", () => {
    const now = performance.now();
    if (startedAt === null) startedAt = now;
    moves += 1;
    const x = Number(range.value) || 0;
    piece.setAttribute("transform", `translate(${x} 0)`);
    fillField("slide_x", String(x));
    fillField("slide_moves", String(moves));
    fillField("slide_ms", String(Math.round(now - startedAt)));
  });

  // Arrow keys step one unit (native); Shift + arrow steps ten, so a
  // keyboard user does not need hundreds of presses.
  range.addEventListener("keydown", (event) => {
    if (!event.shiftKey || (event.key !== "ArrowLeft" && event.key !== "ArrowRight")) return;
    event.preventDefault();
    const step = event.key === "ArrowRight" ? 10 : -10;
    range.value = String(Math.min(Number(range.max), Math.max(0, Number(range.value) + step)));
    range.dispatchEvent(new Event("input"));
  });

  form.addEventListener("submit", (event) => {
    if (moves === 0) {
      event.preventDefault();
      if (statusEl) statusEl.textContent = "Please move the puzzle piece into the gap first.";
      range.focus();
    }
  });
})();
