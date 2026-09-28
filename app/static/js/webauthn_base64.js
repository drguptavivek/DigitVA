// Shared base64url <-> ArrayBuffer conversions for the WebAuthn JSON the
// server sends/expects (py_webauthn's options_to_json_dict /
// parse_*_credential_json). Loaded by webauthn_login.js and
// webauthn_profile.js.
(function (global) {
  "use strict";

  function base64urlToBuffer(value) {
    const padded = value.replace(/-/g, "+").replace(/_/g, "/");
    const padding = "=".repeat((4 - (padded.length % 4)) % 4);
    const raw = atob(padded + padding);
    const buffer = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) buffer[i] = raw.charCodeAt(i);
    return buffer.buffer;
  }

  function bufferToBase64url(buffer) {
    const bytes = new Uint8Array(buffer);
    let str = "";
    for (let i = 0; i < bytes.length; i++) str += String.fromCharCode(bytes[i]);
    return btoa(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  global.DigitVaWebAuthn = { base64urlToBuffer, bufferToBase64url };
})(window);
