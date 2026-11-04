#!/usr/bin/env node
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const MODULE_DIR = path.resolve(__dirname, "..");
const RELATIVE_LIBRARY = path.join("arm64-v8a", "libsmartva_rust.so");
// scripts/build-smartva-ios.sh (macOS) writes it; ios/DigitvaSmartva.podspec vendors it from the module's ios/ folder.
const IOS_XCFRAMEWORK = "SmartvaRust.xcframework";

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

function findXcframework(from = MODULE_DIR) {
  for (let dir = from; ; dir = path.dirname(dir)) {
    const candidate = path.join(dir, "private", "generated", "smartva-ios", IOS_XCFRAMEWORK);
    if (fs.existsSync(path.join(candidate, "Info.plist"))) return candidate;
    if (dir === path.dirname(dir)) return undefined;
  }
}

/** Files under [dir], relative and sorted, so the digest below does not depend on directory order. */
function listTree(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    return entry.isDirectory() ? listTree(full).map((file) => path.join(entry.name, file)) : [entry.name];
  }).sort();
}

/** One sha256 over every file's relative path and contents. */
function treeDigest(dir) {
  const hash = crypto.createHash("sha256");
  let bytes = 0;
  for (const file of listTree(dir)) {
    const content = fs.readFileSync(path.join(dir, file));
    bytes += content.length;
    hash.update(`${file.split(path.sep).join("/")}\0${content.length}\0`).update(content);
  }
  return { sha256: hash.digest("hex"), bytes };
}

/**
 * iOS Plus: copies private/generated/smartva-ios/SmartvaRust.xcframework into ios/ of this module, replacing a staged
 * copy whose files differ. The podspec vendors it (and turns the engine on) only when it is there.
 */
function stageSmartvaIos({ moduleDir = MODULE_DIR } = {}) {
  const source = findXcframework(moduleDir);
  if (!source) {
    throw new Error(
      "Collect Plus for iOS needs private/generated/smartva-ios/SmartvaRust.xcframework; run scripts/build-smartva-ios.sh on a Mac first.",
    );
  }
  const destination = path.join(moduleDir, "ios", IOS_XCFRAMEWORK);
  const wanted = treeDigest(source);
  if (!fs.existsSync(destination) || treeDigest(destination).sha256 !== wanted.sha256) {
    fs.rmSync(destination, { recursive: true, force: true });
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    fs.cpSync(source, destination, { recursive: true });
  }
  return { source, destination, sha256: wanted.sha256, bytes: wanted.bytes };
}

module.exports = { findLibrary, stageSmartva, findXcframework, stageSmartvaIos, treeDigest };

if (require.main === module) {
  try {
    if (process.argv[2] === "--ios") {
      const staged = stageSmartvaIos();
      console.log(`Collect Plus: SmartVA xcframework staged (${staged.bytes} bytes, sha256 ${staged.sha256})`);
    } else {
      const staged = stageSmartva();
      console.log(`Collect Plus: SmartVA binary staged (${staged.bytes} bytes, sha256 ${staged.sha256})`);
    }
  } catch (error) {
    console.error(error.message);
    process.exit(1);
  }
}
