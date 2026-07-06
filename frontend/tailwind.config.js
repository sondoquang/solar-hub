/** @type {import('tailwindcss').Config} */
// Design tokens reference CSS variables defined in src/index.css, so raw
// values live in exactly one place (no magic values scattered in components).
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  // antd is the primary UI/design system (see docs/frontend/ARCHITECTURE.md §9c).
  // Disable Tailwind's preflight reset so it doesn't fight antd's own reset
  // (antd/dist/reset.css, imported in main.jsx). Tailwind stays for utility
  // tweaks only; antd resets the base.
  corePlugins: { preflight: false },
  theme: {
    extend: {
      colors: {
        // RGB-channel form so Tailwind opacity modifiers work (e.g. bg-brand/15,
        // ring-brand/40). The hex --color-brand stays for antd/NProgress/inline.
        brand: "rgb(var(--color-brand-rgb) / <alpha-value>)",
        "brand-hover": "var(--color-brand-hover)",
        "brand-active": "var(--color-brand-active)",
        surface: "var(--color-surface)",
        "surface-raised": "var(--color-surface-raised)",
        "surface-muted": "var(--color-surface-muted)",
        ink: "var(--color-ink)",
        text: "var(--color-text)",
        muted: "var(--color-muted)",
        border: "var(--color-border)",
        "border-strong": "var(--color-border-strong)",
        success: "var(--color-success)",
        warning: "var(--color-warning)",
        danger: "var(--color-danger)",
        info: "var(--color-info)",
        // Neutral overlay — RGB-channel form so opacity modifiers work
        // (bg-overlay/5, bg-overlay/10). Inverts white↔near-black per theme.
        overlay: "rgb(var(--color-overlay-rgb) / <alpha-value>)",
      },
      fontFamily: {
        display: ["Manrope", "ui-sans-serif", "sans-serif"],
        sans: ["Manrope", "ui-sans-serif", "sans-serif"],
      },
      borderRadius: {
        DEFAULT: "var(--radius)",
        lg: "var(--radius-lg)",
      },
      boxShadow: {
        card: "var(--shadow-card)",
      },
    },
  },
  plugins: [],
};
