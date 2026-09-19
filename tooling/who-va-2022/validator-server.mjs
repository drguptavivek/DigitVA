// WHO VA 2022 validator service.
//
// One HTTP endpoint that re-runs the questionnaire package's own
// validateSubmission() on a submitted payload, so the Flask side never has to
// trust a browser's "valid: true". Decision W1 in
// docs/planning/who-va-2022-web-intake-plan.md.
//
//   POST /validate  {"data": {...WHO answers...}}
//        -> 200 {"valid": bool, "issues": [...], "instrument": {...}}
//   GET  /health    -> 200 {"status": "ok", ...}
//
// No framework and no dependencies beyond the bundle built by
// build-validator.mjs. The service holds no state, no database handle and no
// secrets, and never logs answer content (VA payloads are PII).
import { createServer } from "node:http";
import { timingSafeEqual } from "node:crypto";

import { validateSubmission, whoVa2022Instrument, WHO_VA_FORM_VERSION } from "./dist-node/validator-bundle.mjs";

const PORT = Number(process.env.VAFORM_VALIDATOR_PORT ?? 5175);
const HOST = process.env.VAFORM_VALIDATOR_HOST ?? "0.0.0.0";
// Shared secret with the Flask side. The service listens only on the compose
// network, but an internal network is not an authorization boundary.
const SHARED_KEY = process.env.VAFORM_VALIDATOR_KEY ?? "";
// A full WHO VA payload is ~450 scalar answers; 2 MB is generous headroom.
const MAX_BODY_BYTES = Number(process.env.VAFORM_VALIDATOR_MAX_BYTES ?? 2 * 1024 * 1024);

const INSTRUMENT_INFO = {
  id: whoVa2022Instrument.id,
  version: whoVa2022Instrument.version,
  formVersion: WHO_VA_FORM_VERSION,
  questionCount: whoVa2022Instrument.questions.length,
};

const SECURITY_HEADERS = {
  "cache-control": "no-store",
  "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
  "referrer-policy": "no-referrer",
  "x-content-type-options": "nosniff",
};

function sendJson(response, statusCode, body) {
  const payload = JSON.stringify(body);
  response.writeHead(statusCode, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(payload),
    ...SECURITY_HEADERS,
  });
  response.end(payload);
}

function keyAccepted(request) {
  if (!SHARED_KEY) return true;
  const supplied = String(request.headers["x-vaform-key"] ?? "");
  const expected = Buffer.from(SHARED_KEY, "utf8");
  const actual = Buffer.from(supplied, "utf8");
  // timingSafeEqual throws on a length mismatch, which is itself a leak of
  // length only; compare lengths first and keep the comparison constant-time.
  if (expected.length !== actual.length) return false;
  return timingSafeEqual(expected, actual);
}

async function readJsonBody(request) {
  const contentType = String(request.headers["content-type"] ?? "").split(";")[0].trim().toLowerCase();
  if (contentType !== "application/json") {
    throw new HttpError(415, "Request content type must be application/json.");
  }
  const chunks = [];
  let total = 0;
  for await (const chunk of request) {
    total += chunk.length;
    if (total > MAX_BODY_BYTES) throw new HttpError(413, "Payload exceeds the maximum request size.");
    chunks.push(chunk);
  }
  if (total === 0) throw new HttpError(400, "Request body is empty.");
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new HttpError(400, "Request body must be valid JSON.");
  }
}

class HttpError extends Error {
  constructor(statusCode, message) {
    super(message);
    this.statusCode = statusCode;
  }
}

const server = createServer(async (request, response) => {
  const url = new URL(request.url ?? "/", "http://localhost");

  if (request.method === "GET" && url.pathname === "/health") {
    sendJson(response, 200, { status: "ok", instrument: INSTRUMENT_INFO });
    return;
  }

  if (url.pathname !== "/validate") {
    sendJson(response, 404, { error: "Not found." });
    return;
  }
  if (request.method !== "POST") {
    sendJson(response, 405, { error: "Use POST." });
    return;
  }
  if (!keyAccepted(request)) {
    sendJson(response, 401, { error: "Unauthorized." });
    return;
  }

  try {
    const body = await readJsonBody(request);
    const data = body?.data;
    if (data === null || typeof data !== "object" || Array.isArray(data)) {
      throw new HttpError(400, "Body must carry a 'data' object of answers.");
    }
    const assessment = validateSubmission(whoVa2022Instrument, data);
    // `assessment.data` is the normalized answer set. It is deliberately not
    // returned: it is PII, the caller already holds it, and echoing it would
    // double the size of every response.
    sendJson(response, 200, {
      valid: assessment.valid === true,
      issues: assessment.issues ?? [],
      instrument: INSTRUMENT_INFO,
    });
  } catch (error) {
    if (error instanceof HttpError) {
      sendJson(response, error.statusCode, { error: error.message });
      return;
    }
    // Never surface an internal message: it could quote answer content.
    console.error(`validate failed: ${error?.name ?? "Error"}`);
    sendJson(response, 500, { error: "Validation failed." });
  }
});

server.listen(PORT, HOST, () => {
  console.log(
    `who-va-2022 validator listening on ${HOST}:${PORT} | instrument ${INSTRUMENT_INFO.id} ${INSTRUMENT_INFO.version} | ${INSTRUMENT_INFO.questionCount} questions | key ${SHARED_KEY ? "required" : "not set"}`,
  );
});

for (const signal of ["SIGTERM", "SIGINT"]) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
