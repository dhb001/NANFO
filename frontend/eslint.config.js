import js from "@eslint/js";
import tseslint from "@typescript-eslint/eslint-plugin";
import tsParser from "@typescript-eslint/parser";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";

const typeScriptFiles = ["**/*.{ts,tsx}"];
const testFiles = ["**/*.test.{ts,tsx}", "src/test/**", "tests/**", "**/*.test-data.ts", "src/**/*[Ff]ixtures.ts"];

export default [
  {
    ignores: ["dist/**", "coverage/**", "playwright-report/**", "test-results/**", "src/shared/types/generated/**"],
  },
  js.configs.recommended,
  {
    files: typeScriptFiles,
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaVersion: "latest",
        sourceType: "module",
        // Type-aware linting: every linted file belongs to one of these programs
        // (the first that includes it wins, so tests resolve with test-only types).
        project: ["./tsconfig.app.json", "./tsconfig.test.json", "./tsconfig.node.json", "./tests/fullstack/tsconfig.json"],
        tsconfigRootDir: import.meta.dirname,
      },
      globals: {
        window: true,
        document: true,
      },
    },
    plugins: {
      "@typescript-eslint": tseslint,
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...tseslint.configs["flat/eslint-recommended"].rules,
      "no-undef": "off",
      ...tseslint.configs["recommended-type-checked"].rules,
      ...reactHooks.configs.recommended.rules,
      "react-hooks/exhaustive-deps": "error",
      "react-refresh/only-export-components": [
        "warn",
        {
          allowConstantExport: true,
          // Test hook exported next to the bridge component.
          allowExportNames: ["flushRealtimeFrames"],
        },
      ],
      "@typescript-eslint/no-explicit-any": "off",
      // React event handlers may be async; they own their error handling.
      "@typescript-eslint/no-misused-promises": ["error", { checksVoidReturn: { attributes: false } }],
    },
  },
  {
    // Tests work with loosely typed mocks and spies; promise, assertion and unused-code rules still apply.
    files: testFiles,
    rules: {
      "@typescript-eslint/no-unsafe-assignment": "off",
      "@typescript-eslint/no-unsafe-member-access": "off",
      "@typescript-eslint/no-unsafe-call": "off",
      "@typescript-eslint/no-unsafe-return": "off",
      "@typescript-eslint/no-unsafe-argument": "off",
      "@typescript-eslint/require-await": "off",
      "@typescript-eslint/unbound-method": "off",
      "@typescript-eslint/no-base-to-string": "off",
      "react-refresh/only-export-components": "off",
    },
  },
];
