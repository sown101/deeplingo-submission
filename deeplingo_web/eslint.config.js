// W07 static-quality gate — narrow, correctness-oriented linting.
//
// Scope: Rules of Hooks (blocking) and exhaustive-deps (advisory). No style,
// formatting, import-order or naming rules. Generated/build outputs,
// Playwright artifacts and unrelated projects are ignored.
import parser from "@typescript-eslint/parser";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";

export default [
  {
    ignores: [
      "dist/**",
      "node_modules/**",
      "test-results/**",
      "playwright-report/**",
      "coverage/**",
      "*.log",
      "e2e-failure.png",
      "review-*.png",
    ],
  },
  {
    files: ["src/**/*.{ts,tsx}", "e2e/**/*.{ts,tsx}"],
    languageOptions: {
      parser,
      ecmaVersion: 2022,
      sourceType: "module",
      globals: {
        ...globals.browser,
        ...globals.es2022,
      },
    },
    plugins: {
      "react-hooks": reactHooks,
    },
    rules: {
      // Blocking: invalid/conditional hook usage breaks React semantics.
      "react-hooks/rules-of-hooks": "error",
      // Advisory: dependency-array findings are reported for review. Findings
      // in architecture-owned files must be reported, never silently fixed;
      // mechanical dependency additions can change workflow semantics.
      "react-hooks/exhaustive-deps": "warn",
    },
  },
];
