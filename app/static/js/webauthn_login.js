// Drives the "Use a passkey" button on the second login page. See
// docs/policy/authentication-factors.md section 2 and
// app/routes/va_auth.py's va_login_passkey_options/verify.
(function () {
  "use strict";

  const btn = document.getElementById("passkey-login-btn");
  if (!btn) return;

  const statusEl = document.getElementById("passkey-status");
  const optionsUrl = btn.dataset.optionsUrl;
  const verifyUrl = btn.dataset.verifyUrl;
  const csrfInput = document.querySelector('input[name="csrf_token"]');
  const csrfToken = csrfInput ? csrfInput.value : "";
  const { base64urlToBuffer, bufferToBase64url } = window.DigitVaWebAuthn;

  function setStatus(text) {
    if (statusEl) statusEl.textContent = text;
  }

  // No navigator.credentials support at all: hide the button rather than
  // offer a control that can only fail, per the task's explicit-button
  // requirement -- the password form stays the only path.
  if (!window.PublicKeyCredential || !navigator.credentials || !navigator.credentials.get) {
    btn.hidden = true;
    setStatus("Passkeys are not supported in this browser. Use your password below.");
    return;
  }

  btn.addEventListener("click", async () => {
    btn.disabled = true;
    setStatus("Waiting for your passkey…");
    try {
      const optionsResponse = await fetch(optionsUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrfToken },
      });
      const options = await optionsResponse.json();
      if (!optionsResponse.ok) throw new Error(options.error || "options failed");

      options.challenge = base64urlToBuffer(options.challenge);
      options.allowCredentials = (options.allowCredentials || []).map((cred) => ({
        ...cred,
        id: base64urlToBuffer(cred.id),
      }));

      const assertion = await navigator.credentials.get({ publicKey: options });

      const credentialJson = {
        id: assertion.id,
        rawId: bufferToBase64url(assertion.rawId),
        type: assertion.type,
        response: {
          authenticatorData: bufferToBase64url(assertion.response.authenticatorData),
          clientDataJSON: bufferToBase64url(assertion.response.clientDataJSON),
          signature: bufferToBase64url(assertion.response.signature),
          userHandle: assertion.response.userHandle
            ? bufferToBase64url(assertion.response.userHandle)
            : null,
        },
      };

      const verifyResponse = await fetch(verifyUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
        body: JSON.stringify({ credential: credentialJson }),
      });
      const result = await verifyResponse.json();
      if (!verifyResponse.ok || !result.redirect) {
        throw new Error(result.error || "verification failed");
      }
      setStatus("");
      window.location.href = result.redirect;
    } catch (err) {
      // Cancellation (NotAllowedError) and any other failure both get the
      // same neutral message; the password form below remains usable.
      setStatus("Could not sign in with a passkey. You can use your password instead.");
      btn.disabled = false;
    }
  });
})();
