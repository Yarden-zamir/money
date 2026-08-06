import { client } from "@/api/client.gen";
import { actingAsHeader } from "@/lib/actingAs";

/**
 * The generated client talks to the same origin that served the app, so the session cookie
 * is sent automatically and there is no base URL to configure per environment.
 */
client.setConfig({
  baseUrl: "",
  credentials: "same-origin",
});

/**
 * Every request says who it is speaking for, when that is not the signed-in account.
 *
 * An interceptor rather than a parameter on each call: acting as somebody is a property of
 * the session, not of any one request, and threading it through every generated call site
 * would mean the one place it was forgotten silently wrote under the wrong name.
 */
client.interceptors.request.use((request) => {
  for (const [header, value] of Object.entries(actingAsHeader())) {
    request.headers.set(header, value);
  }
  return request;
});
