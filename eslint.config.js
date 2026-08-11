const { defineConfig } = require("eslint/config");
const eslintJs = require("@eslint/js");
const globals = require("globals");

module.exports = defineConfig([
  // This root ESLint gate covers only the guarded MCP server entry points under scripts/.
  // Salesforce source under force-app/ is versioned but not linted here.
  {
    files: ["scripts/**/*.mjs"],
    languageOptions: {
      sourceType: "module",
      ecmaVersion: "latest",
      globals: {
        ...globals.node
      }
    },
    plugins: {
      eslintJs
    },
    extends: ["eslintJs/recommended"]
  }
]);
