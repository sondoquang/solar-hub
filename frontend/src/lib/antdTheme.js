// antd theme — mirrors the EvonHub design tokens in src/index.css (:root and
// :root[data-theme="light"]) so antd components share the same palette/radius as
// the Tailwind utilities. antd's theme config must be plain JS values (it can't
// read CSS variables), so we keep the raw values here in sync with index.css and
// pick the right set per mode via makeAntdTheme(mode). index.css stays the
// conceptual single source for the tokens.
import { theme as antdTheme } from "antd";

// Unified control height for every form control (Input, Select, InputNumber,
// pickers…). We pin all three size steps so antd derives padding + vertical
// centering itself for each variant — single/multiple Select, affix inputs,
// InputNumber, TreeSelect — which a raw CSS `min-height` cannot do (it stretched
// multiple-mode selects past 40px). Default == large == 40px so an input added
// without a `size` prop is already 40px; only size="small" stays compact (24px)
// for deliberately dense controls (variation table, filter bars). controlHeightLG
// is pinned so antd doesn't re-derive it to 50px from the bumped controlHeight.
const FORM_CONTROL_SIZE = {
  controlHeight: 40,
  controlHeightLG: 40,
  controlHeightSM: 24,
};

// Shared status hues (same across themes — antd tints them itself). Only the
// surface/text/brand seeds differ between dark and light.
const STATUS = {
  colorSuccess: "#22c55e", // --color-success
  colorWarning: "#f59e0b", // --color-warning
  colorError: "#ef4444", // --color-danger
};

// Per-mode seeds. Keep in sync with the matching block in src/index.css.
const PALETTE = {
  dark: {
    algorithm: antdTheme.darkAlgorithm,
    brand: "#978df8", // --color-brand (EvonHub violet)
    brandHover: "#a99ffb",
    textBase: "#ffffff", // dark algorithm derives the text opacity ramp from white
    bgBase: "#000000", // --color-surface (page background)
    bgContainer: "#1a1b1e", // --color-surface-raised (cards, tables, inputs)
    bgElevated: "#1f2026", // --color-surface-muted (dropdowns, modals, popovers)
    bgLayout: "#000000",
    border: "#2a2c33", // --color-border
    borderSecondary: "#23252b",
    // Violet is light, so primary buttons read better with dark ink text here
    // (white on #978df8 is ~2.8:1 — fails AA; dark ink is ~6.5:1 — passes).
    buttonPrimaryColor: "#16171a",
    tableHeaderBg: "#1f2026",
    tableHeaderColor: "#cbd5e1",
  },
  light: {
    algorithm: antdTheme.defaultAlgorithm,
    brand: "#6d5ef6", // deeper violet so text/active clear AA on white
    brandHover: "#5b4ff0",
    textBase: "#0f172a", // --color-ink (light)
    bgBase: "#ffffff",
    bgContainer: "#ffffff", // --color-surface-raised (light)
    bgElevated: "#ffffff",
    bgLayout: "#f4f5f7", // --color-surface (light page)
    border: "#e2e8f0", // --color-border (light)
    borderSecondary: "#eef0f3",
    // On the deeper violet, white text clears AA (~4.6:1), so use it.
    buttonPrimaryColor: "#ffffff",
    tableHeaderBg: "#f4f5f7",
    tableHeaderColor: "#475569",
  },
};

/**
 * Build the antd ThemeConfig for a theme mode.
 * @param {"dark"|"light"} mode
 * @returns {import("antd").ThemeConfig}
 */
export function makeAntdTheme(mode = "dark") {
  const p = PALETTE[mode] ?? PALETTE.dark;
  return {
    algorithm: p.algorithm,
    token: {
      colorPrimary: p.brand,
      colorInfo: p.brand,
      ...STATUS,
      colorTextBase: p.textBase,
      colorBgBase: p.bgBase,
      colorBgContainer: p.bgContainer,
      colorBgElevated: p.bgElevated,
      colorBgLayout: p.bgLayout,
      colorBorder: p.border,
      colorBorderSecondary: p.borderSecondary,
      borderRadius: 6, // --radius
      fontFamily: '"Manrope", ui-sans-serif, system-ui, sans-serif',
    },
    components: {
      Button: { primaryColor: p.buttonPrimaryColor },
      Input: {
        ...FORM_CONTROL_SIZE,
        activeBorderColor: p.brand,
        hoverBorderColor: p.brandHover,
        activeShadow: `0 0 0 3px ${mode === "light" ? "rgba(109, 94, 246, 0.18)" : "rgba(151, 141, 248, 0.18)"}`,
        errorActiveShadow: "0 0 0 3px rgba(239, 68, 68, 0.18)",
      },
      InputNumber: { ...FORM_CONTROL_SIZE },
      Select: {
        ...FORM_CONTROL_SIZE,
        optionActiveBg:
          mode === "light" ? "rgba(109, 94, 246, 0.10)" : "rgba(151, 141, 248, 0.12)",
        optionSelectedBg:
          mode === "light" ? "rgba(109, 94, 246, 0.16)" : "rgba(151, 141, 248, 0.22)",
      },
      TreeSelect: { ...FORM_CONTROL_SIZE },
      Cascader: { ...FORM_CONTROL_SIZE },
      AutoComplete: { ...FORM_CONTROL_SIZE },
      Mentions: { ...FORM_CONTROL_SIZE },
      DatePicker: { ...FORM_CONTROL_SIZE },
      TimePicker: { ...FORM_CONTROL_SIZE },
      Table: {
        headerBg: p.tableHeaderBg,
        headerColor: p.tableHeaderColor,
        rowHoverBg:
          mode === "light" ? "rgba(109, 94, 246, 0.06)" : "rgba(151, 141, 248, 0.07)",
        borderColor: p.border,
      },
      // Brand violet for the "on" track — clearly visible on both surfaces.
      Switch: { colorPrimary: p.brand, colorPrimaryHover: p.brandHover },
    },
  };
}
