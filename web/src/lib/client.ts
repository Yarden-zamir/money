import { client } from "@/api/client.gen";

/**
 * The generated client talks to the same origin that served the app, so the session cookie
 * is sent automatically and there is no base URL to configure per environment.
 */
client.setConfig({
  baseUrl: "",
  credentials: "same-origin",
});

/** Where to send someone who is not signed in. */
export const LOGIN_URL = "/api/v1/auth/github/start";
