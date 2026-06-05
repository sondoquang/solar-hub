// antd theme — mirrors the design tokens in src/index.css (:root) so antd
// components share the same palette/radius as Tailwind utilities. Keep the
// raw values here in sync with index.css; index.css remains the conceptual
// single source for the tokens (antd's theme config must be plain JS values,
// it cannot read CSS variables).
import { theme as antdTheme } from "antd";

/** @type {import("antd").ThemeConfig} */
export const theme = {
  algorithm: antdTheme.defaultAlgorithm,
  token: {
    colorPrimary: "#f5a524", // --color-brand (solar amber)
    colorSuccess: "#16a34a", // --color-success
    colorWarning: "#d97706", // --color-warning
    colorError: "#dc2626", // --color-danger
    colorTextBase: "#0f172a", // --color-ink
    colorBgLayout: "#f8fafc", // --color-surface
    borderRadius: 8, // --radius (0.5rem)
    fontFamily:
      '"IBM Plex Sans", ui-sans-serif, system-ui, sans-serif',
  },
  components: {
    // Brand amber is light, so primary buttons read better with dark ink text.
    Button: { primaryColor: "#0f172a" },
  },
};
