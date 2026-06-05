import axios from "axios";

import { getAccessToken, setAccessToken } from "../lib/AuthContext.jsx";

const REFRESH_KEY = "solar_hub_refresh";
const BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api";

// Single axios instance for the whole app.
export const api = axios.create({ baseURL: BASE_URL });

// Separate instance for the token refresh call so it never triggers the
// 401 interceptor recursively.
const refreshApi = axios.create({ baseURL: BASE_URL });

// Request: attach Bearer token when available.
api.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

let refreshPromise = null;

// Response: on 401 attempt a silent token refresh then replay the request.
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;
    // Skip refresh logic for auth endpoints — a 401 there means wrong credentials, not an expired token.
    if (error.response?.status !== 401 || original._retry || original.url?.includes("/auth/token/")) {
      return Promise.reject(error);
    }

    original._retry = true;

    // Deduplicate concurrent 401s: all of them wait on the same refresh call.
    if (!refreshPromise) {
      const storedRefresh = localStorage.getItem(REFRESH_KEY);
      if (!storedRefresh) {
        window.location.replace("/login");
        return Promise.reject(error);
      }
      refreshPromise = refreshApi
        .post("/auth/token/refresh/", { refresh: storedRefresh })
        .then(({ data }) => {
          setAccessToken(data.access);
          if (data.refresh) localStorage.setItem(REFRESH_KEY, data.refresh);
          return data.access;
        })
        .catch(() => {
          setAccessToken(null);
          localStorage.removeItem(REFRESH_KEY);
          window.location.replace("/login");
          return null;
        })
        .finally(() => {
          refreshPromise = null;
        });
    }

    const newToken = await refreshPromise;
    if (!newToken) return Promise.reject(error);

    original.headers.Authorization = `Bearer ${newToken}`;
    return api(original);
  },
);
