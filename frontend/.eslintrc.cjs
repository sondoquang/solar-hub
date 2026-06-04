module.exports = {
  root: true,
  env: { browser: true, es2022: true, node: true },
  extends: [
    "eslint:recommended",
    "plugin:react/recommended",
    "plugin:react/jsx-runtime",
    "plugin:react-hooks/recommended",
    "prettier",
  ],
  parserOptions: { ecmaVersion: "latest", sourceType: "module", ecmaFeatures: { jsx: true } },
  settings: { react: { version: "detect" } },
  rules: {
    // Not adopting prop-types in this phase (JSX without TypeScript); revisit
    // if/when components grow or we migrate to TS.
    "react/prop-types": "off",
  },
  ignorePatterns: ["dist", "node_modules"],
};
