import { defineApp } from "kitshn";

// kitshn 2 (https://kit.yarden-zamir.com): a Compose app on a machine labelled "docker". The app has its
// own GitHub login, so its address stays open like before.
export default defineApp({
  compose: { runsOn: ["docker"] },
  deploy: [
    { on: "push", branch: "main", name: "prod", address: "money.yarden-zamir.com", startsIn: "Everyone" },
    { on: "pull_request", name: "pr-{pr}", ephemeral: true, startsIn: "Everyone" },
  ],
});
