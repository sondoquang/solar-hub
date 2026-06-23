// antd theme — mirrors the EvonHub dark design tokens in src/index.css (:root) so
// antd components share the same palette/radius as Tailwind utilities. antd's
// darkAlgorithm derives the full dark text/elevation ramp; we override the seed
// surfaces (black base, raised #1a1b1e containers) + the violet accent. Keep the
// raw values here in sync with index.css; index.css remains the conceptual single
// source for the tokens (antd's theme config must be plain JS values, it cannot
// read CSS variables).
import { theme as antdTheme } from "antd";

/** @type {import("antd").ThemeConfig} */
export const theme = {
  algorithm: antdTheme.darkAlgorithm,
  token: {
    colorPrimary: "#978df8", // --color-brand (EvonHub violet)
    colorInfo: "#978df8",
    colorSuccess: "#22c55e", // --color-success
    colorWarning: "#f59e0b", // --color-warning
    colorError: "#ef4444", // --color-danger
    colorTextBase: "#ffffff", // dark algorithm derives the text opacity ramp from white
    colorBgBase: "#000000", // --color-surface (page background)
    colorBgContainer: "#1a1b1e", // --color-surface-raised (cards, tables, inputs)
    colorBgElevated: "#1f2026", // --color-surface-muted (dropdowns, modals, popovers)
    colorBgLayout: "#000000",
    colorBorder: "#2a2c33", // --color-border
    colorBorderSecondary: "#23252b",
    borderRadius: 6, // --radius
    fontFamily: '"Manrope", ui-sans-serif, system-ui, sans-serif',
  },
  components: {
    // Violet is light, so primary buttons read better with dark ink text
    // (white on #978df8 is ~2.8:1 — fails AA; dark ink is ~6.5:1 — passes).
    Button: { primaryColor: "#16171a" },
    Input: {
      activeBorderColor: "#978df8",
      hoverBorderColor: "#a99ffb",
      activeShadow: "0 0 0 3px rgba(151, 141, 248, 0.18)",
      errorActiveShadow: "0 0 0 3px rgba(239, 68, 68, 0.18)",
    },
    Select: {
      optionActiveBg: "rgba(151, 141, 248, 0.12)",
      optionSelectedBg: "rgba(151, 141, 248, 0.22)",
    },
    Table: {
      headerBg: "#1f2026",
      headerColor: "#cbd5e1",
      rowHoverBg: "rgba(151, 141, 248, 0.07)",
      borderColor: "#2a2c33",
    },
    // Brand violet for the "on" track — clearly visible on dark surfaces.
    Switch: { colorPrimary: "#978df8", colorPrimaryHover: "#a99ffb" },
  },
};
