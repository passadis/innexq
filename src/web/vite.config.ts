import { defineConfig } from "vitest/config";
import { resolve } from "node:path";

export default defineConfig({
  build: { rollupOptions: { input: {
    main: resolve(import.meta.dirname, "index.html"),
    redirect: resolve(import.meta.dirname, "redirect.html"),
  } } },
  server: { proxy: { "/config.json": "http://127.0.0.1:8080" } },
  test: { environment: "jsdom", setupFiles: ["./src/test-setup.ts"], include: ["src/**/*.test.ts", "src/**/*.test.tsx"] },
});
