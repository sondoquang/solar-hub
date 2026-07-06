import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { getMe, loginUser, refreshAccessToken } from "../api/auth.js";
import { can } from "./permissions.js";

const REFRESH_KEY = "solar_hub_refresh";

// Exported so tests can inject a restricted `hasPerm` via AuthContext.Provider.
export const AuthContext = createContext(null);

// Module-level ref so the axios interceptor can read the token without
// needing to be inside a React component.
let _accessToken = null;

export function getAccessToken() {
  return _accessToken;
}

export function setAccessToken(token) {
  _accessToken = token;
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const navigate = useNavigate();
  const isRefreshing = useRef(false);

  const setTokens = useCallback((access, refresh) => {
    _accessToken = access;
    if (refresh) {
      localStorage.setItem(REFRESH_KEY, refresh);
    }
  }, []);

  const clearTokens = useCallback(() => {
    _accessToken = null;
    localStorage.removeItem(REFRESH_KEY);
  }, []);

  // Called by the axios response interceptor on 401 so it can get a fresh token.
  const silentRefresh = useCallback(async () => {
    if (isRefreshing.current) return null;
    const storedRefresh = localStorage.getItem(REFRESH_KEY);
    if (!storedRefresh) return null;
    isRefreshing.current = true;
    try {
      const data = await refreshAccessToken(storedRefresh);
      setTokens(data.access, data.refresh ?? storedRefresh);
      return data.access;
    } catch {
      clearTokens();
      setUser(null);
      return null;
    } finally {
      isRefreshing.current = false;
    }
  }, [setTokens, clearTokens]);

  // On mount: try to restore session from stored refresh token.
  useEffect(() => {
    const storedRefresh = localStorage.getItem(REFRESH_KEY);
    if (!storedRefresh) {
      setIsLoading(false);
      return;
    }
    (async () => {
      try {
        const data = await refreshAccessToken(storedRefresh);
        setTokens(data.access, data.refresh ?? storedRefresh);
        const me = await getMe();
        setUser(me);
      } catch {
        clearTokens();
      } finally {
        setIsLoading(false);
      }
    })();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const login = useCallback(
    async (credentials) => {
      const tokens = await loginUser(credentials);
      setTokens(tokens.access, tokens.refresh);
      const me = await getMe();
      setUser(me);
    },
    [setTokens],
  );

  const logout = useCallback(() => {
    clearTokens();
    setUser(null);
    navigate("/login", { replace: true });
  }, [clearTokens, navigate]);

  // Replace the cached user (e.g. after a profile update) so the UI reflects it.
  const updateUser = useCallback((next) => setUser(next), []);

  // RBAC gate for the UI: hasPerm("orders.view_order") — superusers pass all.
  // Permissions come from /auth/me/ and refresh on login/reload; the backend
  // stays the real enforcement boundary.
  const hasPerm = useCallback((...perms) => can(user, ...perms), [user]);

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isLoading,
        login,
        logout,
        updateUser,
        silentRefresh,
        hasPerm,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

// Permission gate for hiding UI a user can't act on. Returns the `hasPerm`
// function; safe to call outside AuthProvider (isolated component tests) where
// it defaults to permissive — the app shell always wraps AuthProvider, so real
// use always gets the true check, and the backend enforces regardless.
export function useCan() {
  const ctx = useContext(AuthContext);
  return ctx?.hasPerm ?? (() => true);
}
