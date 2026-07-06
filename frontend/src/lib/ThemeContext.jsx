import { createContext, useCallback, useContext, useEffect, useState } from "react";

// Persisted only once the user picks a theme by hand. While absent, the app
// follows the OS (prefers-color-scheme) and reacts to system changes live.
const THEME_KEY = "solar_hub_theme";

export const ThemeContext = createContext(null);

function systemMode() {
  if (typeof window === "undefined" || !window.matchMedia) return "dark";
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function storedMode() {
  if (typeof window === "undefined") return null;
  const v = window.localStorage?.getItem(THEME_KEY);
  return v === "light" || v === "dark" ? v : null;
}

// Initial mode mirrors the anti-FOUC script in index.html: stored choice wins,
// else the OS preference.
function initialMode() {
  return storedMode() ?? systemMode();
}

export function ThemeProvider({ children }) {
  const [mode, setModeState] = useState(initialMode);

  // Reflect the mode onto <html data-theme> so the CSS variables in index.css
  // switch. Runs on mount too, keeping React and the anti-FOUC script aligned.
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", mode);
  }, [mode]);

  // While the user hasn't chosen manually, track the OS preference live.
  useEffect(() => {
    if (storedMode() || typeof window === "undefined" || !window.matchMedia) return;
    const mql = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = (e) => {
      if (!storedMode()) setModeState(e.matches ? "light" : "dark");
    };
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [mode]);

  // Explicit choice — persists, so it stops following the OS from now on.
  const setMode = useCallback((next) => {
    window.localStorage?.setItem(THEME_KEY, next);
    setModeState(next);
  }, []);

  const toggleTheme = useCallback(() => {
    setModeState((prev) => {
      const next = prev === "dark" ? "light" : "dark";
      window.localStorage?.setItem(THEME_KEY, next);
      return next;
    });
  }, []);

  return (
    <ThemeContext.Provider value={{ mode, toggleTheme, setMode }}>
      {children}
    </ThemeContext.Provider>
  );
}

// Safe outside a provider (isolated component tests): defaults to dark with
// no-op setters, mirroring useCan — the app shell always wraps ThemeProvider.
export function useTheme() {
  const ctx = useContext(ThemeContext);
  return ctx ?? { mode: "dark", toggleTheme: () => {}, setMode: () => {} };
}
