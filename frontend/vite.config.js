import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// host:true binds 0.0.0.0 so the container's dev server is reachable via the
// published port. test.* configures Vitest (jsdom + RTL setup).
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    // Cho phép host ngrok (Vite chặn host lạ mặc định). true = mọi host, đủ cho demo.
    allowedHosts: true,
    // Proxy /api sang backend trong cùng mạng docker => chỉ cần 1 tunnel ngrok.
    proxy: {
      "/api": { target: "http://backend:8000", changeOrigin: true },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: "./vitest.setup.js",
  },
});
