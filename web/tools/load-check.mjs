/**
 * Measures cold load: how long until the first real number is on screen.
 *
 * The stub charges 900ms for any request that would hit git, which is what a fetch to GitHub
 * actually costs, and 20ms for the rest. That ratio is the whole point — the app used to
 * discover what to fetch in three serial steps, so the expensive part happened three times in
 * a row before anything rendered.
 *
 * Also counts requests, because the fix is "ask for everything at once", and a request count
 * is the honest way to show that rather than a wall-clock number that varies with the machine.
 */
import { chromium } from "playwright";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { join, extname, resolve } from "node:path";

const DIST = resolve(import.meta.dirname, "..", "dist");
const PORT = 4603;
const GIT_COST = 900;
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".map": "application/json" };

const now = new Date();
const MONTH = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;

const me = { login: "dev", name: "Yarden", email: "d@l", avatar_url: null };
const budget = {
  slug: "joint", name: "Household", repo: "y/b", currency: "ILS", branch: "main",
  members: [{ person: "yarden", name: "Yarden", github: "dev" }], me: "yarden", can_write: true,
};
const buckets = ["rent", "groceries", "fun"].map((id, i) => ({
  id, name: id, group: "Bills", target: null, archived: false, order: i,
}));

let order = [];
const server = createServer(async (req, res) => {
  const path = (req.url ?? "/").split("?")[0];
  if (path.startsWith("/api/")) {
    // Anything that resolves a budget touches the clone; /me and /auth do not.
    const touchesGit = !path.endsWith("/me") && !path.includes("/auth/");
    order.push({ path: path.replace("/api/v1", ""), at: Date.now() });
    await new Promise((r) => setTimeout(r, touchesGit ? GIT_COST : 20));

    let body = [];
    if (path.endsWith("/me")) body = me;
    else if (path.endsWith("/auth/config")) body = { login_url: "/x" };
    else if (path.endsWith("/budgets")) body = [budget];
    else if (path.includes("/close")) body = { closed: false, tag: null, sha: null };
    else if (path.includes("/months/")) {
      body = {
        person: "yarden", month: MONTH, currency: "ILS",
        ready_to_assign: "1240.00", income: "12000.00", assigned: "9500.00",
        buckets: buckets.map((b) => ({
          bucket: b.id, name: b.name, group: b.group,
          assigned: "100.00", activity: "-50.00", available: "50.00", target: null,
        })),
      };
    } else if (path.includes("/buckets")) body = buckets;
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

async function coldLoad({ returning }) {
  order = [];
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await context.addInitScript((known) => {
    localStorage.setItem("money.language", "en");
    // A returning visitor already chose a budget; a first-time one has not.
    if (known) localStorage.setItem("money.budget", "joint");
  }, returning);

  const page = await context.newPage();
  const started = Date.now();
  await page.goto(`http://localhost:${PORT}/`);
  await page.waitForSelector("[data-bucket]");
  const elapsed = Date.now() - started;

  // How deep the request chain was: requests that started only after an earlier one finished.
  const first = order[0]?.at ?? started;
  const waves = new Set(order.map((r) => Math.round((r.at - first) / 300))).size;

  const grouped = new Map();
  for (const r of order) {
    const wave = Math.round((r.at - first) / 300);
    grouped.set(wave, [...(grouped.get(wave) ?? []), r.path]);
  }

  await context.close();
  return { elapsed, requests: order.length, waves, grouped };
}

for (const returning of [true, false]) {
  const label = returning ? "returning visitor" : "first-ever visit ";
  const { elapsed, requests, waves, grouped } = await coldLoad({ returning });
  console.log(`  ${label}  ${String(elapsed).padStart(5)}ms   ${requests} requests in ${waves} wave(s)`);
  for (const [wave, paths] of [...grouped].sort((a, b) => a[0] - b[0])) {
    console.log(`      wave ${wave}: ${paths.join(", ")}`);
  }
}

await browser.close();
server.close();
