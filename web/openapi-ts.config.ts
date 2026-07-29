import { defineConfig } from "@hey-api/openapi-ts";

// The schema is the single source of truth for both clients. Regenerate with
// `pnpm run generate:api`; CI runs `generate:check` and fails on a diff.
//
// TypeScript is pinned to 5.x in package.json: this generator uses the TS compiler API,
// which TypeScript 7's native port does not expose. Unpin once @hey-api/openapi-ts
// supports TypeScript 7.
export default defineConfig({
  input: "../openapi.json",
  output: { path: "src/api" },
  plugins: ["@hey-api/client-fetch", "@tanstack/react-query"],
});
