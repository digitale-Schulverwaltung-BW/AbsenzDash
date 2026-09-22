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
    // vi.stubEnv() mutates a single import.meta.env object shared by all test files
    // in a worker (even with the default isolate: true, which only resets the DOM
    // environment, not this binding). Without this, a stub from one file (e.g.
    // StudentDetail.test.tsx or StudentList.test.tsx toggling
    // VITE_ANONYMISIERUNG_AKTIV) can leak into another file and cause intermittent
    // failures. This makes Vitest reset all stubbed envs after every test file.
    unstubEnvs: true,
  },
});
