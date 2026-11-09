// Expo's default config, plus the Flask intake page's attachment modules: the web interview imports
// app/static/js/intake/attachment_buffer.js and attachment_platform.js as they are, so the encrypted
// buffer and its uploader have one source (docs/policy/web-intake.md, "Attachments").
const path = require("path");
const { getDefaultConfig } = require("expo/metro-config");

const config = getDefaultConfig(__dirname);
config.watchFolders = [...config.watchFolders, path.resolve(__dirname, "../../app/static/js/intake")];

// Load each screen's modules on first use, not at startup (docs/policy/expo-client.md: heavy screens load on first use).
config.transformer = { ...config.transformer, getTransformOptions: async () => ({ transform: { experimentalImportSupport: true, inlineRequires: true } }) };

// With inline requires an import becomes a require(), and the WHO package exposes only an "import" condition.
config.resolver.unstable_conditionNames = [...(config.resolver.unstable_conditionNames ?? []), "import"];

module.exports = config;
