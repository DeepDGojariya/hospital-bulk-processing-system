import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const API = "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  // FastAPI serves the build from app/static, so one service hosts API and UI.
  build: { outDir: "../app/static", emptyOutDir: true },
  server: {
    proxy: {
      "/hospitals": { target: API, ws: true },
      "/health": API,
      "/docs": API,
      "/openapi.json": API,
    },
  },
  test: { environment: "jsdom", globals: true, setupFiles: "./src/test-setup.js" },
});
