/**
 * Measures the two perceived-speed claims, against an API with realistic latency.
 *
 * "Feels faster" is not something to assert. Both of these are observable:
 *
 *   1. Stepping to another month must never empty the ledger. Blanking the screen is what
 *      made a sub-second fetch read as a page load.
 *   2. Hovering a tab before clicking it must make the content arrive sooner, because the
 *      request started while the pointer was still moving.
 *
 * The stub answers every read in 350ms — roughly what a git-backed read costs on a cache
 * miss. With no latency there is nothing to hide and both numbers would be meaningless.
 */
import { chromium } from "playwright";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { join, extname, resolve } from "node:path";

const DIST = resolve(import.meta.dirname, "..", "dist");
const PORT = 4601;
const LATENCY = 350;
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".map": "application/json", ".svg": "image/svg+xml" };

const now = new Date();
const MONTH = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;

const me = { login: "dev", name: "Yarden", email: "dev@localhost", avatar_url: null };
const budget = {
  slug: "joint", name: "Household", repo: "y/b", currency: "ILS", branch: "main",
  members: [{ person: "yarden", name: "Yarden", github: "dev" }], me: "yarden", can_write: true,
};
const buckets = ["rent", "groceries", "transport", "fun"].map((id, i) => ({
  id, name: id, group: "Bills", target: null, archived: false, order: i,
}));
const monthFor = (label) => ({
  person: "yarden", month: label, currency: "ILS",
  ready_to_assign: "1240.00", income: "12000.00", assigned: "9500.00",
  buckets: buckets.map((b) => ({
    bucket: b.id, name: b.name, group: b.group,
    assigned: "100.00", activity: "-50.00", available: "50.00", target: null,
  })),
});

const server = createServer(async (req, res) => {
  const path = (req.url ?? "/").split("?")[0];
  if (path.startsWith("/api/")) {
    await new Promise((r) => setTimeout(r, LATENCY));
    let body = [];
    if (path.endsWith("/me")) body = me;
    else if (path.endsWith("/auth/config")) body = { login_url: "/x" };
    else if (path.endsWith("/budgets")) body = [budget];
    else if (path.includes("/months/") && path.includes("/close")) body = { closed: false, tag: null, sha: null };
    else if (path.includes("/months/")) body = monthFor(path.split("/months/")[1].split("/")[0]);
    else if (path.includes("/buckets")) body = buckets;
    else if (path.includes("/balances")) body = { currency: "ILS", balances: [], settle_up: [] };
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

async function page() {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await context.addInitScript(() => {
    localStorage.setItem("money.language", "en");
    localStorage.setItem("money.budget", "joint");
  });
  const p = await context.newPage();
  await p.goto(`http://localhost:${PORT}/`, { waitUntil: "networkidle" });
  await p.waitForSelector("[data-bucket]");
  return p;
}

const rowCount = (p) => p.locator("[data-bucket]").count();
let failures = 0;

// --- 1. stepping months must not empty the ledger -------------------------------------
{
  const p = await page();
  await p.getByRole("button", { name: "Next month" }).click();

  let emptied = 0;
  for (let i = 0; i < 40; i += 1) {
    if ((await rowCount(p)) === 0) emptied += 1;
    await p.waitForTimeout(25);
  }
  const held = emptied === 0;
  console.log(`month step:   ledger empty for ${emptied * 25}ms  ${held ? "PASS" : "FAIL"}`);
  if (!held) failures += 1;
  await p.context().close();
}

// --- 2. hovering a tab before clicking must get content sooner -------------------------
async function timeToBalances({ hover }) {
  const p = await page();
  const tab = p.getByRole("link", { name: "Balances" }).first();
  if (hover) {
    await tab.hover();
    await p.waitForTimeout(LATENCY + 100); // the pointer-travel time being spent on the fetch
  }
  const started = Date.now();
  await tab.click();
  await p.getByRole("heading", { name: "Balances" }).waitFor();
  // The heading renders with the skeleton, so wait for the query to actually resolve.
  await p.waitForFunction(() => !document.querySelector("[aria-hidden].animate-pulse"));
  const elapsed = Date.now() - started;
  await p.context().close();
  return elapsed;
}

const cold = await timeToBalances({ hover: false });
const warm = await timeToBalances({ hover: true });
const better = warm < cold - 100;
console.log(`tab switch:   cold ${cold}ms -> warm ${warm}ms  ${better ? "PASS" : "FAIL"}`);
if (!better) failures += 1;

await browser.close();
server.close();
console.log(failures === 0 ? "\nPASS" : `\nFAIL (${failures})`);
process.exit(failures === 0 ? 0 : 1);
