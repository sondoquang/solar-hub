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
        brand: "var(--color-brand)",
        surface: "var(--color-surface)",
        ink: "var(--color-ink)",
        muted: "var(--color-muted)",
        success: "var(--color-success)",
        warning: "var(--color-warning)",
        danger: "var(--color-danger)",
      },
      fontFamily: {
        display: ["Be Vietnam Pro", "ui-sans-serif", "sans-serif"],
        sans: ["Be Vietnam Pro", "ui-sans-serif", "sans-serif"],
      },
      borderRadius: {
        DEFAULT: "var(--radius)",
      },
      boxShadow: {
        card: "var(--shadow-card)",
      },
    },
  },
  plugins: [],
};
