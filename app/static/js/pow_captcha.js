// Drives the email-step proof-of-work CAPTCHA: fetches a signed challenge,
// hands it to a Web Worker (pow_captcha_worker.js) to solve, then fills the
// hidden form fields and enables Continue. See
// docs/policy/authentication-factors.md section 5 and
// app/services/pow_captcha_service.py.
(function () {
  "use strict";

  const form = document.getElementById("login-email-form");
  if (!form) return;

  const submitButton = form.querySelector('button[type="submit"], input[type="submit"]');
  const statusEl = document.getElementById("captcha-status");
  const challengeUrl = form.dataset.captchaChallengeUrl;
  const workerUrl = form.dataset.captchaWorkerUrl;

  function setStatus(text) {
    if (statusEl) statusEl.textContent = text;
  }

  function fillField(name, value) {
    const field = form.querySelector(`[name="${name}"]`);
    if (field) field.value = value;
  }

  if (submitButton) submitButton.disabled = true;
  setStatus("Preparing sign-in check…");

  fetch(challengeUrl, { credentials: "same-origin" })
    .then((response) => {
      if (!response.ok) throw new Error("challenge request failed");
      return response.json();
    })
    .then((challenge) => {
      const worker = new Worker(workerUrl);
      worker.onmessage = (event) => {
        const { solution, error } = event.data || {};
        worker.terminate();
        if (error || !solution) {
          setStatus(
            "Could not complete the sign-in check. Please reload the page."
          );
          return;
        }
        fillField("captcha_salt", challenge.salt);
        fillField("captcha_difficulty", challenge.difficulty);
        fillField("captcha_expires", challenge.expires);
        fillField("captcha_signature", challenge.signature);
        fillField("captcha_solution", solution);
        if (submitButton) submitButton.disabled = false;
        setStatus("");
      };
      worker.onerror = () => {
        setStatus(
          "Could not complete the sign-in check. Please reload the page."
        );
      };
      worker.postMessage({ salt: challenge.salt, difficulty: challenge.difficulty });
    })
    .catch(() => {
      setStatus("Could not prepare the sign-in check. Please reload the page.");
    });
})();
