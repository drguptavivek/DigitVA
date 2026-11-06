#!/usr/bin/env node
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const MODULE_DIR = path.resolve(__dirname, "..");
const RELATIVE_LIBRARY = path.join("arm64-v8a", "libsmartva_rust.so");
// scripts/build-smartva-ios.sh writes it; ios/DigitvaSmartva.podspec links the staged copy.
const IOS_FRAMEWORK = "SmartvaRust.xcframework";

/** The first ancestor of [from] that has private/generated/<folder>/<relative>, or undefined. */
function findGenerated(from, folder, relative) {
  for (let dir = from; ; dir = path.dirname(dir)) {
    const candidate = path.join(dir, "private", "generated", folder, relative);
    if (fs.existsSync(candidate)) return candidate;
    if (dir === path.dirname(dir)) return undefined;
  }
}

function findLibrary(from = MODULE_DIR) {
  return findGenerated(from, "smartva-android", RELATIVE_LIBRARY);
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

/** iOS: copies private/generated/smartva-ios/SmartvaRust.xcframework (scripts/build-smartva-ios.sh) to ios/Engine/. */
function stageSmartvaIos({ moduleDir = MODULE_DIR } = {}) {
  const source = findGenerated(moduleDir, "smartva-ios", IOS_FRAMEWORK);
  if (!source || !fs.existsSync(path.join(source, "Info.plist"))) {
    throw new Error(`Collect Plus for iOS needs private/generated/smartva-ios/${IOS_FRAMEWORK}; run scripts/build-smartva-ios.sh first.`);
  }
  const destination = path.join(moduleDir, "ios", "Engine", IOS_FRAMEWORK);
  fs.rmSync(destination, { recursive: true, force: true });
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.cpSync(source, destination, { recursive: true });
  return { source, destination };
}

module.exports = { findLibrary, stageSmartva, stageSmartvaIos };

if (require.main === module) {
  try {
    if (process.argv[2] === "--ios") {
      console.log(`Collect Plus: SmartVA iOS framework staged from ${stageSmartvaIos().source}`);
    } else {
      const staged = stageSmartva();
      console.log(`Collect Plus: SmartVA binary staged (${staged.bytes} bytes, sha256 ${staged.sha256})`);
    }
  } catch (error) {
    console.error(error.message);
    process.exit(1);
  }
}
