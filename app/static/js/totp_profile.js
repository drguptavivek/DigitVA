// TOTP and recovery-codes card on the Profile page: enrol, confirm, remove,
// and reveal recovery codes exactly once (docs/policy/
// authentication-factors.md sections 4, 7). Loaded by va_myprofile.html.
(function () {
  "use strict";

  const root = document.getElementById("totp-card");
  if (!root) return;

  const CSRF = root.dataset.csrf;
  const statusEl = document.getElementById("totp-status");
  const msgEl = document.getElementById("totp-msg");
  const enrollBtn = document.getElementById("totp-enroll-btn");
  const removeBtn = document.getElementById("totp-remove-btn");
  const setupWrap = document.getElementById("totp-setup");
  const qrWrap = document.getElementById("totp-qr");
  const secretEl = document.getElementById("totp-secret");
  const codeInput = document.getElementById("totp-confirm-code");
  const confirmBtn = document.getElementById("totp-confirm-btn");
  const reauthWrap = document.getElementById("totp-reauth");
  const reauthPassword = document.getElementById("totp-reauth-password");
  const reauthBtn = document.getElementById("totp-reauth-btn");
  const reauthMsg = document.getElementById("totp-reauth-msg");
  const recoveryRemaining = document.getElementById("recovery-remaining");
  const recoveryRegenBtn = document.getElementById("recovery-regenerate-btn");
  const recoveryReveal = document.getElementById("recovery-reveal");
  const recoveryList = document.getElementById("recovery-codes-list");
  const recoveryAck = document.getElementById("recovery-ack");
  const recoveryDone = document.getElementById("recovery-done-btn");
  const recoveryCopy = document.getElementById("recovery-copy-btn");
  const recoveryDownload = document.getElementById("recovery-download-btn");

  function apiFetch(url, method, body) {
    return fetch(url, {
      method: method || "GET",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": CSRF },
      body: body ? JSON.stringify(body) : undefined,
    }).then((r) => r.json().then((d) => ({ ok: r.ok, status: r.status, data: d })));
  }

  function showMsg(text, ok) {
    msgEl.className = `small mb-2 ${ok ? "text-success" : "text-danger"}`;
    msgEl.textContent = text;
  }

  function needsReauth(status) {
    if (status === 401) {
      reauthWrap.hidden = false;
      // The prompt sits at the top of its card; bring it to the button's user.
      reauthWrap.scrollIntoView({ block: "center", behavior: "smooth" });
      reauthPassword.focus({ preventScroll: true });
      return true;
    }
    return false;
  }

  function recoveryCodeLines() {
    return Array.from(recoveryList.children).map((el) => el.textContent);
  }

  function showRecoveryCodes(codes) {
    recoveryList.innerHTML = codes.map((c) => `<div>${c}</div>`).join("");
    recoveryAck.checked = false;
    recoveryDone.disabled = true;
    recoveryReveal.hidden = false;
  }

  reauthBtn.addEventListener("click", async () => {
    const { ok, data } = await apiFetch("/api/v1/profile/reauth", "POST", {
      password: reauthPassword.value,
    });
    reauthMsg.className = `small mt-2 ${ok ? "text-success" : "text-danger"}`;
    reauthMsg.textContent = data.message || data.error;
    if (ok) {
      reauthPassword.value = "";
      reauthWrap.hidden = true;
    }
  });

  async function refreshStatus() {
    const [totpResp, recoveryResp] = await Promise.all([
      apiFetch("/api/v1/profile/totp"),
      apiFetch("/api/v1/profile/recovery-codes"),
    ]);
    if (totpResp.ok) {
      statusEl.textContent = totpResp.data.enrolled ? "Enabled" : "Not enabled";
      enrollBtn.hidden = totpResp.data.enrolled;
      removeBtn.hidden = !totpResp.data.enrolled;
    }
    if (recoveryResp.ok) {
      recoveryRemaining.textContent = recoveryResp.data.remaining;
    }
  }

  enrollBtn.addEventListener("click", async () => {
    showMsg("", true);
    const { ok, status, data } = await apiFetch("/api/v1/profile/totp/enroll", "POST");
    if (!ok) {
      if (needsReauth(status)) return;
      showMsg(data.error || "Could not start enrolment.", false);
      return;
    }
    secretEl.textContent = data.secret;
    qrWrap.innerHTML = data.qr_svg;
    codeInput.value = "";
    setupWrap.hidden = false;
  });

  confirmBtn.addEventListener("click", async () => {
    const code = (codeInput.value || "").trim();
    if (!code) return;
    const { ok, status, data } = await apiFetch("/api/v1/profile/totp/confirm", "POST", { code });
    if (!ok) {
      if (needsReauth(status)) return;
      showMsg(data.error || "Invalid code.", false);
      return;
    }
    codeInput.value = "";
    setupWrap.hidden = true;
    showMsg("TOTP enabled.", true);
    if (data.recovery_codes) showRecoveryCodes(data.recovery_codes);
    await refreshStatus();
  });

  removeBtn.addEventListener("click", async () => {
    if (!(await window.confirmDialog("You will need another way to sign in if it was your only factor.", { title: "Remove TOTP?", okLabel: "Remove" }))) return;
    const { ok, status, data } = await apiFetch("/api/v1/profile/totp", "DELETE");
    if (!ok) {
      if (needsReauth(status)) return;
      showMsg(data.error || "Could not remove TOTP.", false);
      return;
    }
    showMsg("TOTP removed.", true);
    await refreshStatus();
  });

  recoveryRegenBtn.addEventListener("click", async () => {
    if (!(await window.confirmDialog("Your existing recovery codes will stop working.", { title: "Regenerate recovery codes?", okLabel: "Regenerate" }))) return;
    const { ok, status, data } = await apiFetch("/api/v1/profile/recovery-codes/regenerate", "POST");
    if (!ok) {
      if (needsReauth(status)) return;
      showMsg(data.error || "Could not regenerate codes.", false);
      return;
    }
    showRecoveryCodes(data.recovery_codes);
    await refreshStatus();
  });

  recoveryAck.addEventListener("change", () => {
    recoveryDone.disabled = !recoveryAck.checked;
  });

  recoveryDone.addEventListener("click", () => {
    recoveryReveal.hidden = true;
    recoveryList.innerHTML = "";
  });

  recoveryCopy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(recoveryCodeLines().join("\n"));
      showMsg("Recovery codes copied.", true);
    } catch (err) {
      showMsg("Could not copy codes.", false);
    }
  });

  recoveryDownload.addEventListener("click", () => {
    const blob = new Blob([recoveryCodeLines().join("\n") + "\n"], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "digitva-recovery-codes.txt";
    a.click();
    URL.revokeObjectURL(url);
  });

  refreshStatus();
})();
