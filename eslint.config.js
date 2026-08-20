import eslint from "@eslint/js";
import globals from "globals";

export default [
  {
    ignores: [
      "artifacts/**",
      "content/**",
      "frontend/assets/error-tracking/**",
      "frontend/locales/**",
      "node_modules/**",
    ],
  },
  eslint.configs.recommended,
  {
    files: ["frontend/**/*.{js,mjs}"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: {
        ...globals.browser,
        Telegram: "readonly",
      },
    },
    rules: {
      "no-empty": ["error", { allowEmptyCatch: true }],
      "no-unused-vars": "off",
      "no-useless-assignment": "off",
      "no-useless-catch": "off",
      "no-useless-escape": "off",
    },
  },
  {
    files: ["frontend/error-tracking-entry.js", "frontend/page-loader.js"],
    rules: {
      "no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
  {
    files: ["tools/**/*.mjs"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: globals.node,
    },
    rules: {
      "no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
  {
    files: ["tools/browser-e2e.mjs"],
    languageOptions: {
      globals: {
        ...globals.node,
        ...globals.browser,
      },
    },
    rules: {
      "no-useless-assignment": "off",
    },
  },
];
