/**
 * Reproduces "a reorder undoes itself".
 *
 * The move buttons call the same applyMove() the drag does, so this exercises the real
 * mutation loop without fighting HTML5 drag-and-drop in a headless browser.
 *
 * The stub mimics what git actually does: a PUT takes ~600ms (commit, rebase, push) and the
 * GET keeps answering with the ORIGINAL order until every PUT has landed — which is exactly
 * what the server does while writes are still in flight.
 */
import { chromium } from "playwright";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { join, extname } from "node:path";

const DIST = "/Users/kcw/Github/money/main/web/dist";
const PORT = 4599;
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".map": "application/json", ".svg": "image/svg+xml" };

const me = { login: "dev", name: "Yarden", email: "dev@localhost", avatar_url: null };
const now = new Date();
const MONTH = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;

const budget = {
  slug: "joint", name: "Household", repo: "y/b", currency: "ILS", branch: "main",
  members: [{ person: "yarden", name: "Yarden", github: "dev" }],
  me: "yarden", can_write: true,
};

// Four buckets in one group. Nudging the first one down must leave it second.
const NAMES = ["alpha", "beta", "gamma", "delta"];
let buckets = NAMES.map((id, i) => ({ id, name: id, group: "Bills", target: null, archived: false, order: i }));

// Field names come from MonthResponse and BucketState. Inventing them silently renders
// nothing, because the crash lands inside a formatter rather than at the boundary.
const monthFor = (list) => ({
  person: "yarden", month: MONTH, currency: "ILS",
  ready_to_assign: "0.00", income: "0.00", assigned: "0.00",
  buckets: list.map((b) => ({
    bucket: b.id, name: b.name, group: b.group,
    assigned: "0.00", activity: "0.00", available: "0.00", target: null,
  })),
});

let inflight = 0;
let served = [...buckets];   // what GET answers with
let writes = 0;

const server = createServer(async (req, res) => {
  const path = (req.url ?? "/").split("?")[0];
  if (path.startsWith("/api/")) {
    let body = null;
    if (req.method === "PUT" && path.includes("/buckets/")) {
      writes += 1;
      inflight += 1;
      const chunks = []; for await (const c of req) chunks.push(c);
      const sent = JSON.parse(Buffer.concat(chunks).toString());
      const id = path.split("/buckets/")[1];
      // Writes serialize on the store's write lock and each is its own commit, so they
      // land one at a time and a read between them sees a HALF-APPLIED order. That
      // intermediate state is the whole bug — a stub that hides it proves nothing.
      const slot = writes;
      await new Promise((r) => setTimeout(r, 500 * slot));
      buckets = buckets.map((b) => (b.id === id ? { ...b, ...sent, id } : b));
      served = [...buckets].sort((a, b) => a.order - b.order || a.name.localeCompare(b.name));
      inflight -= 1;
      body = sent;
    } else if (path.endsWith("/me")) body = me;
    else if (path.endsWith("/auth/config")) body = { login_url: "/x" };
    else if (path.endsWith("/budgets")) body = [budget];
    else if (path.includes("/buckets")) body = served;
    else if (path.includes("/months/")) body = monthFor(served);
    else if (path.includes("/close")) body = { closed: false, tag: null, sha: null };
    else body = [];
    res.writeHead(200, { "content-type": "application/json" });
    return res.end(JSON.stringify(body));
  }
  try {
    const file = join(DIST, path === "/" ? "index.html" : path);
    const data = await readFile(file);
    res.writeHead(200, { "content-type": TYPES[extname(file)] ?? "application/octet-stream" });
    res.end(data);
  } catch {
    res.writeHead(200, { "content-type": "text/html" });
    res.end(await readFile(join(DIST, "index.html")));
  }
});
await new Promise((ok) => server.listen(PORT, ok));

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
await context.addInitScript(() => {
  localStorage.setItem("money.language", "en");
  localStorage.setItem("money.budget", "joint");
});
const page = await context.newPage();
page.on("pageerror", (e) => console.log("pageerror:", String(e).slice(0, 300)));
await page.goto(`http://localhost:${PORT}/`, { waitUntil: "networkidle" });

const order = async () =>
  (await page.locator("[data-bucket]").evaluateAll((els) => els.map((e) => e.dataset.bucket)))
    .join(",");

const start = await order();
console.log("before:      ", start);
// A stub whose field names have drifted renders nothing, and "no rows never reverted" would
// otherwise pass. Fail loudly instead.
if (start !== "alpha,beta,gamma,delta") {
  console.log("\nFAIL — the month screen did not render the seeded buckets");
  await browser.close(); server.close(); process.exit(1);
}

// Nudge "alpha" down one place.
await page.getByRole("button", { name: "Move down" }).first().click();

// Sample continuously. The contract is not "it ends up right" — a revert that heals on the
// next poll still reads as the app undoing what you just did. The row must never leave the
// place it was put, at any point between the click and the writes settling.
const EXPECTED = "beta,alpha,gamma,delta";
const seen = new Map();
for (let elapsed = 0; elapsed < 14_000; elapsed += 100) {
  const current = await order();
  seen.set(current, (seen.get(current) ?? 0) + 1);
  await page.waitForTimeout(100);
}

console.log("writes:      ", writes);
for (const [state, samples] of seen) {
  const tag = state === EXPECTED ? "ok   " : "WRONG";
  console.log(`  ${tag} ${state}  (${(samples / 10).toFixed(1)}s)`);
}

const held = [...seen.keys()].every((state) => state === EXPECTED);
console.log(held ? "\nPASS — the reorder held throughout" : "\nFAIL — the reorder reverted");

await browser.close();
server.close();
process.exit(held ? 0 : 1);
