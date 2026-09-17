import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["src/renderer/**/*.test.ts"],
    environment: "node",
  },
});
