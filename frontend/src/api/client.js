import axios from "axios";

// Single axios instance for the whole app. baseURL comes from env so local
// and prod differ only in .env. Never hard-code the backend URL elsewhere.
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "/api",
});

// Request: attach auth token (placeholder until auth is built).
api.interceptors.request.use((config) => config);

// Response: central error handling (placeholders — 401 → /login, 5xx → toast).
api.interceptors.response.use(
  (response) => response,
  (error) => Promise.reject(error)
);
