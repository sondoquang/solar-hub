import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { getMe, loginUser, refreshAccessToken } from "../api/auth.js";

const REFRESH_KEY = "solar_hub_refresh";

const AuthContext = createContext(null);

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

  return (
    <AuthContext.Provider
      value={{ user, isAuthenticated: !!user, isLoading, login, logout, updateUser, silentRefresh }}
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
