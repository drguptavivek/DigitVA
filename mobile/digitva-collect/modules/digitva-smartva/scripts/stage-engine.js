#!/usr/bin/env node
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const MODULE_DIR = path.resolve(__dirname, "..");
const RELATIVE_LIBRARY = path.join("arm64-v8a", "libsmartva_rust.so");

function findLibrary(from = MODULE_DIR) {
  for (let dir = from; ; dir = path.dirname(dir)) {
    const candidate = path.join(dir, "private", "generated", "smartva-android", RELATIVE_LIBRARY);
    if (fs.existsSync(candidate)) return candidate;
    if (dir === path.dirname(dir)) return undefined;
  }
}

function sha256(file) {
  return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

function stageSmartva({ moduleDir = MODULE_DIR } = {}) {
  const source = findLibrary(moduleDir);
  if (!source || !fs.existsSync(source)) {
    throw new Error(
      "Collect Plus needs private/generated/smartva-android/arm64-v8a/libsmartva_rust.so; build the private Android library first.",
    );
  }
  const destination = path.join(moduleDir, "android", "src", "main", "jniLibs", RELATIVE_LIBRARY);
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  if (!fs.existsSync(destination) || sha256(source) !== sha256(destination)) fs.copyFileSync(source, destination);
  return { source, destination, sha256: sha256(source), bytes: fs.statSync(source).size };
}

module.exports = { findLibrary, stageSmartva };

if (require.main === module) {
  try {
    const staged = stageSmartva();
    console.log(`Collect Plus: SmartVA binary staged (${staged.bytes} bytes, sha256 ${staged.sha256})`);
  } catch (error) {
    console.error(error.message);
    process.exit(1);
  }
}
