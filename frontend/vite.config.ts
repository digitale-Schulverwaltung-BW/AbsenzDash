/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: fileURLToPath(new URL("../wordpress-plugin/absenzdash/assets/spa", import.meta.url)),
    emptyOutDir: true,
    manifest: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
