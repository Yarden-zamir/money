/**
 * Which member this browser is speaking for.
 *
 * A testing affordance: it lets one person drive the app as each of several placeholder
 * members to see how a shared budget behaves without needing four GitHub accounts.
 *
 * The server decides whether to honour it, and only ever does for a member with **no GitHub
 * login**. That single rule is the security model — a placeholder is a stand-in nobody can
 * sign in as, so acting as one speaks for a stand-in rather than for somebody real. Nothing
 * here can impersonate an account; a request naming one is refused with a 403.
 *
 * The commit author stays the signed-in person either way, so `git log` still records who
 * actually pressed the button.
 */
const KEY = "money.actingAs";

export function actingAs(): string | null {
  return localStorage.getItem(KEY);
}

export function setActingAs(person: string | null): void {
  if (person) localStorage.setItem(KEY, person);
  else localStorage.removeItem(KEY);
  // A full reload rather than invalidating queries: every screen is derived from who is
  // acting, so re-fetching piecemeal would briefly mix one person's envelopes with
  // another's totals.
  window.location.reload();
}

/** The header the server reads, or nothing when speaking for the signed-in account. */
export function actingAsHeader(): Record<string, string> {
  const person = actingAs();
  return person ? { "X-Act-As": person } : {};
}
