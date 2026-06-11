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
    borderRadius: 4, // --radius (0.25rem / 4px)
    fontFamily:
      '"Be Vietnam Pro", ui-sans-serif, system-ui, sans-serif',
  },
  components: {
    // Brand amber is light, so primary buttons read better with dark ink text.
    Button: { primaryColor: "#0f172a" },
    Input: {
      activeBorderColor: "#f5a524",
      hoverBorderColor: "#e59b1e",
      activeShadow: "0 0 0 3px rgba(245, 165, 36, 0.12)",
      errorActiveShadow: "0 0 0 3px rgba(220, 38, 38, 0.10)",
    },
    Select: {
      optionActiveBg: "rgba(245, 165, 36, 0.08)",
      optionSelectedBg: "rgba(245, 165, 36, 0.15)",
    },
    // Brand amber is too washed-out for a small on/off track — use the app's
    // blue accent so the "on" state is unmistakable. The default off-track
    // (near-white gray) disappears on white modals, so tint it light blue too.
    Switch: {
      colorPrimary: "#2563eb", // blue-600 — on
      colorPrimaryHover: "#1d4ed8", // blue-700 — on hover
      colorTextQuaternary: "#93c5fd", // blue-300 — off track
      colorTextTertiary: "#60a5fa", // blue-400 — off hover
    },
  },
};
