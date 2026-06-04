import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// host:true binds 0.0.0.0 so the container's dev server is reachable via the
// published port. test.* configures Vitest (jsdom + RTL setup).
export default defineConfig({
  plugins: [react()],
  server: { host: true, port: 5173 },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: "./vitest.setup.js",
  },
});
