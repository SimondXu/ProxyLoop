import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

// The web never carries prompt text (AGENTS rule 4): prompts come only from
// prompts.jsonl. The acceptance check is tests/web/test_no_prompt_text.py; this
// catches the Fast grammar's directives early.
const PROMPTISH = "/@slow:|@hold|@end_call|CASE AGENT|output format/i";

export default tseslint.config(
  { ignores: ["dist", "node_modules", "test-results", "playwright-report"] },
  js.configs.recommended,
  ...tseslint.configs.strict,
  {
    files: ["**/*.{ts,tsx}"],
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "no-restricted-syntax": [
        "error",
        { selector: `Literal[value=${PROMPTISH}]`, message: "No prompt text in the web." },
        { selector: `TemplateElement[value.raw=${PROMPTISH}]`, message: "No prompt text in the web." },
        { selector: `JSXText[value=${PROMPTISH}]`, message: "No prompt text in the web." },
      ],
    },
  },
  {
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/**/*.test.ts"],
    rules: {
      "no-restricted-imports": ["error", { patterns: ["node:*", "fs", "path"] }],
    },
  },
);
