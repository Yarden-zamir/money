import { client } from "@/api/client.gen";

/**
 * The generated client talks to the same origin that served the app, so the session cookie
 * is sent automatically and there is no base URL to configure per environment.
 */
client.setConfig({
  baseUrl: "",
  credentials: "same-origin",
});
