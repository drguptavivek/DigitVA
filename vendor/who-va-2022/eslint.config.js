import eslint from "@eslint/js";
import importPlugin from "eslint-plugin-import-x";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist/**", "demo/dist/**", "coverage/**", "playwright-report/**", "src/generated/**"] },
  eslint.configs.recommended,
  ...tseslint.configs.recommended,
  reactHooks.configs.flat.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    plugins: { "import-x": importPlugin },
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    rules: {
      complexity: ["error", 25],
      "max-depth": ["error", 5],
      "import-x/no-cycle": ["error", { ignoreExternal: true, maxDepth: 10 }],
      "preserve-caught-error": "off",
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
          destructuredArrayIgnorePattern: "^_",
          varsIgnorePattern: "^_"
        }
      ]
    }
  },
  {
    files: ["**/*.{js,mjs}"],
    languageOptions: { globals: { ...globals.browser, ...globals.node } }
  },
  {
    files: ["src/engine/expression.ts"],
    rules: { complexity: ["error", 45] }
  },
  {
    files: ["tests/**/*.{ts,tsx}"],
    rules: { complexity: "off" }
  },
  {
    files: [
      "src/engine/**/*.ts",
      "src/attachments.ts",
      "src/core.ts",
      "src/date.ts",
      "src/draft.ts",
      "src/i18n.ts",
      "src/instrument-loader.ts",
      "src/instrument.ts",
      "src/types.ts"
    ],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["../ui/**", "../web*", "../native*", "../compiler/**"],
              message: "Core and engine modules must not depend on UI, platform adapters, or compiler code."
            }
          ]
        }
      ]
    }
  },
  {
    files: ["src/ui/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["../web*", "../native*", "../compiler/**"],
              message: "Reusable UI must not depend on web/native adapters or compiler code."
            }
          ]
        }
      ]
    }
  }
);
