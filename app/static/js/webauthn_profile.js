// Passkeys card on the Profile page: list, register, rename, revoke, and
// the reauth prompt required by docs/policy/authentication-factors.md
// section 7. Loaded by va_myprofile.html.
(function () {
  "use strict";

  const root = document.getElementById("passkeys-card");
  if (!root) return;

  const { base64urlToBuffer, bufferToBase64url } = window.DigitVaWebAuthn;
  const CSRF = root.dataset.csrf;
  const listEl = document.getElementById("passkeys-list");
  const msgEl = document.getElementById("passkeys-msg");
  const addBtn = document.getElementById("passkey-add-btn");
  const nameInput = document.getElementById("passkey-name-input");
  const reauthWrap = document.getElementById("passkey-reauth");
  const reauthPassword = document.getElementById("passkey-reauth-password");
  const reauthBtn = document.getElementById("passkey-reauth-btn");
  const reauthMsg = document.getElementById("passkey-reauth-msg");

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

  function escapeHtml(s) {
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

  function renderList(passkeys) {
    if (!passkeys.length) {
      listEl.innerHTML = '<p class="text-muted small mb-0">No passkeys registered yet.</p>';
      return;
    }
    listEl.innerHTML = passkeys
      .map(
        (p) => `
      <div class="d-flex align-items-center justify-content-between border-bottom py-2" data-id="${p.id}">
        <div>
          <div class="fw-bold">${escapeHtml(p.name)} ${p.backed_up ? '<span class="badge bg-secondary">Synced</span>' : ""}</div>
          <div class="small text-muted">
            Added ${p.created_at ? new Date(p.created_at).toLocaleDateString() : "-"}
            &bull; Last used ${p.last_used_at ? new Date(p.last_used_at).toLocaleDateString() : "never"}
          </div>
        </div>
        <div>
          <button class="btn btn-sm btn-outline-secondary passkey-rename" data-id="${p.id}">Rename</button>
          <button class="btn btn-sm btn-outline-danger passkey-revoke" data-id="${p.id}">Revoke</button>
        </div>
      </div>`
      )
      .join("");
  }

  async function loadPasskeys() {
    const { ok, data } = await apiFetch("/api/v1/profile/passkeys");
    if (ok) renderList(data.passkeys || []);
  }

  function needsReauth(status) {
    if (status === 401) {
      reauthWrap.hidden = false;
      return true;
    }
    return false;
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

  addBtn.addEventListener("click", async () => {
    if (!window.PublicKeyCredential || !navigator.credentials || !navigator.credentials.create) {
      showMsg("Passkeys are not supported in this browser.", false);
      return;
    }
    const name = (nameInput.value || "").trim() || "Passkey";
    addBtn.disabled = true;
    showMsg("", true);
    try {
      const { ok, status, data: options } = await apiFetch("/api/v1/profile/passkeys/options", "POST");
      if (!ok) {
        if (needsReauth(status)) return;
        throw new Error(options.error || "could not start registration");
      }

      options.challenge = base64urlToBuffer(options.challenge);
      options.user.id = base64urlToBuffer(options.user.id);
      options.excludeCredentials = (options.excludeCredentials || []).map((c) => ({
        ...c,
        id: base64urlToBuffer(c.id),
      }));

      const credential = await navigator.credentials.create({ publicKey: options });

      const credentialJson = {
        id: credential.id,
        rawId: bufferToBase64url(credential.rawId),
        type: credential.type,
        response: {
          attestationObject: bufferToBase64url(credential.response.attestationObject),
          clientDataJSON: bufferToBase64url(credential.response.clientDataJSON),
          transports: credential.response.getTransports ? credential.response.getTransports() : [],
        },
      };

      const result = await apiFetch("/api/v1/profile/passkeys", "POST", {
        credential: credentialJson,
        name,
      });
      if (!result.ok) throw new Error(result.data.error || "could not register passkey");
      nameInput.value = "";
      showMsg("Passkey added.", true);
      await loadPasskeys();
    } catch (err) {
      showMsg("Could not add that passkey. Please try again.", false);
    } finally {
      addBtn.disabled = false;
    }
  });

  listEl.addEventListener("click", async (event) => {
    const renameBtn = event.target.closest(".passkey-rename");
    const revokeBtn = event.target.closest(".passkey-revoke");
    if (renameBtn) {
      const id = renameBtn.dataset.id;
      const name = window.prompt("New name for this passkey:");
      if (!name) return;
      const { ok, status, data } = await apiFetch(`/api/v1/profile/passkeys/${id}`, "PATCH", { name });
      if (!ok) {
        if (needsReauth(status)) return;
        showMsg(data.error || "Could not rename passkey.", false);
        return;
      }
      showMsg("Passkey renamed.", true);
      await loadPasskeys();
    } else if (revokeBtn) {
      const id = revokeBtn.dataset.id;
      if (!window.confirm("Revoke this passkey? This cannot be undone.")) return;
      const { ok, status, data } = await apiFetch(`/api/v1/profile/passkeys/${id}`, "DELETE");
      if (!ok) {
        if (needsReauth(status)) return;
        showMsg(data.error || "Could not revoke passkey.", false);
        return;
      }
      showMsg("Passkey revoked.", true);
      await loadPasskeys();
    }
  });

  loadPasskeys();
})();
