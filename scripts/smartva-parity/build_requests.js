#!/usr/bin/env node
/*
 * Turns export.py's stream (stdin) into PII-free SmartVA requests with the app's own code: INPUT_JS is
 * mobile/digitva-collect/src/smartva/input.ts compiled by tsc (run.sh does it). Raw payloads are read from the pipe and
 * never written.
 *
 * Two inputs per case:
 *   server  the values the server's SmartVA read (_clean_payload_for_smartva's row), restricted to the fields the
 *           phone keeps (cleanSmartVaInput's key set: its PII filter), through createSmartVaRequest. This is "the same
 *           case": the main comparison.
 *   phone   cleanSmartVaInput applied to the JSON payload, as the app would. It differs from `server` only in how a
 *           JSON number is spelt (JS String(5) is "5", Python str(5.0) is "5.0"); kept to show that does not change a
 *           result.
 * Writes into OUT_DIR (under private/smartva-parity/):
 *   requests.tsv, requests-phone.tsv   id \t country \t hiv \t malaria \t hce \t freetext \t rows_json (harness.c input;
 *                    rows_json is [input], what SmartvaService.kt and DigitvaSmartvaModule.swift pass to smartva_score_json)
 *   expected.jsonl   {id, engine, options, options_source, input, refused, expected}; input describes how the phone's
 *                    cleaned row differs from the server's: dropped (fields the server read that the phone drops),
 *                    added, numeric (values equal as numbers, spelt differently), other (values that differ otherwise)
 *   server_icds.json the server's VA_SMARTVA_ICDS
 * id is the first 16 hex of sha256(va_sid).
 * usage: INPUT_JS=.../input.js node build_requests.js OUT_DIR < export stream
 */
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const readline = require("node:readline");

const { cleanSmartVaInput, createSmartVaRequest } = require(process.env.INPUT_JS);
const out = process.argv[2];
const sha = (text) => crypto.createHash("sha256").update(text, "utf8").digest("hex");

fs.mkdirSync(out, { recursive: true });
const serverRequests = fs.createWriteStream(path.join(out, "requests.tsv"));
const phoneRequests = fs.createWriteStream(path.join(out, "requests-phone.tsv"));
const expected = fs.createWriteStream(path.join(out, "expected.jsonl"));
const totals = { cases: 0, refused: 0, dropped: 0, added: 0, numeric: 0, other: 0 };

function requestLine(id, input, options) {
  const request = createSmartVaRequest(input, options);
  const o = request.options;
  const flags = [o.hiv, o.malaria, o.hce, o.freetext].map((flag) => (flag ? 1 : 0));
  return [id, o.country, ...flags, JSON.stringify([request.input])].join("\t") + "\n";
}

/** Field-name-free account of how the phone's cleaned row differs from the server's. */
function inputDifference(phone, server) {
  const dropped = Object.keys(server).filter((key) => !(key in phone)).length;
  const added = Object.keys(phone).filter((key) => !(key in server)).length;
  let numeric = 0;
  let other = 0;
  for (const key of Object.keys(phone)) {
    if (!(key in server) || phone[key] === server[key]) continue;
    const a = Number(phone[key]);
    if (phone[key].trim() !== "" && server[key].trim() !== "" && a === Number(server[key])) numeric += 1;
    else other += 1;
  }
  return { dropped, added, numeric, other };
}

readline.createInterface({ input: process.stdin }).on("line", (line) => {
  if (!line.startsWith("SVP\t")) return;
  const record = JSON.parse(line.slice(4));
  if (record.kind === "icds") {
    fs.writeFileSync(path.join(out, "server_icds.json"), JSON.stringify(record.icds));
    return;
  }
  totals.cases += 1;
  const id = sha(record.sid).slice(0, 16);
  const phone = cleanSmartVaInput(record.payload, record.sid, record.sealed);
  const server = Object.fromEntries(Object.keys(phone).filter((key) => key in record.server_row)
    .map((key) => [key, record.server_row[key]]));
  const difference = inputDifference(phone, record.server_row);
  for (const key of ["dropped", "added", "numeric", "other"]) if (difference[key]) totals[key] += 1;
  let refused = false;
  try {
    const lines = [requestLine(id, server, record.options), requestLine(id, phone, record.options)];
    serverRequests.write(lines[0]);
    phoneRequests.write(lines[1]);
  } catch {
    refused = true;
    totals.refused += 1;
  }
  expected.write(JSON.stringify({
    id, engine: record.engine, options: record.options, options_source: record.options_source,
    input: difference, refused, expected: record.expected,
  }) + "\n");
}).on("close", () => {
  serverRequests.end();
  phoneRequests.end();
  expected.end();
  console.error(`cases ${totals.cases}; cases whose phone-cleaned row has fields dropped ${totals.dropped}, added `
    + `${totals.added}, numbers spelt differently ${totals.numeric}, other value differences ${totals.other}; `
    + `refused by createSmartVaRequest ${totals.refused}`);
  if (!fs.existsSync(path.join(out, "server_icds.json"))) process.exitCode = 1;
});
