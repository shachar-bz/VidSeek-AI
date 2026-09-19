/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The hosted API's origin in development. The website is served from a different origin
// than the API, which is the whole reason §14 of the specification has the API drop its
// loopback gate and allow the website's origin; proxying here keeps development honest
// about that rather than hiding it behind a same-origin URL that production will not have.
const API_TARGET = process.env.VIDSEEK_API_URL ?? "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/v1": { target: API_TARGET, changeOrigin: true }
    }
  },
  build: {
    outDir: "dist",
    emptyOutDir: true
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"]
  }
});
