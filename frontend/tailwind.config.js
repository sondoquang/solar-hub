/** @type {import('tailwindcss').Config} */
// Design tokens reference CSS variables defined in src/index.css, so raw
// values live in exactly one place (no magic values scattered in components).
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
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
        display: ["Space Grotesk", "ui-sans-serif", "sans-serif"],
        sans: ["IBM Plex Sans", "ui-sans-serif", "sans-serif"],
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
