// Expo's default config, plus the Flask intake page's attachment modules: the web interview imports
// app/static/js/intake/attachment_buffer.js and attachment_platform.js as they are, so the encrypted
// buffer and its uploader have one source (docs/policy/web-intake.md, "Attachments").
const path = require("path");
const { getDefaultConfig } = require("expo/metro-config");

const config = getDefaultConfig(__dirname);
config.watchFolders = [...config.watchFolders, path.resolve(__dirname, "../../app/static/js/intake")];

module.exports = config;
