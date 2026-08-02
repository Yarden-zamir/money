/**
 * Screenshot the built app against stubbed API responses.
 *
 * Running the real backend would need GitHub auth and a live data repo, and neither says
 * anything about layout. Stubbing the API instead makes every screen reachable in both
 * directions and at any viewport, which is what a UI pass actually needs to look at.
 *
 *   node tools/shoot.mjs [outputDir]
 */

import { chromium } from "playwright";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, resolve } from "node:path";
import { mkdirSync } from "node:fs";

const DIST = resolve(import.meta.dirname, "..", "dist");
const OUT = resolve(process.argv[2] ?? join(import.meta.dirname, "..", "shots"));
const PORT = 4507;

const TYPES = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".svg": "image/svg+xml",
  ".map": "application/json",
};

const me = { login: "dev", name: "Yarden", email: "dev@localhost", avatar_url: null };

const budget = {
  slug: "joint",
  name: "Household",
  repo: "Yarden-zamir/budget-joint",
  currency: "ILS",
  branch: "main",
  members: [
    { person: "yarden", name: "Yarden", github: "Yarden-zamir" },
    { person: "dana", name: "Dana", github: "dana-example" },
  ],
  me: "yarden",
  can_write: true,
};

const buckets = [
  { id: "groceries", name: "Groceries", group: "Essentials", target: { kind: "monthly", amount: "2000.00" }, archived: false },
  { id: "rent", name: "Rent", group: "Essentials", target: { kind: "monthly", amount: "5200.00" }, archived: false },
  { id: "eating-out", name: "Eating out", group: "Lifestyle", target: { kind: "monthly", amount: "800.00" }, archived: false },
  { id: "transport", name: "Transport", group: "Essentials", target: null, archived: false },
  { id: "savings", name: "Savings", group: "Goals", target: { kind: "monthly", amount: "1500.00" }, archived: false },
];

const month = {
  person: "yarden",
  month: "2026-07",
  currency: "ILS",
  ready_to_assign: "1240.00",
  income: "12000.00",
  assigned: "9500.00",
  buckets: [
    { bucket: "groceries", name: "Groceries", group: "Essentials", assigned: "2000.00", activity: "-1642.30", available: "357.70", target: "2000.00" },
    { bucket: "rent", name: "Rent", group: "Essentials", assigned: "5200.00", activity: "-5200.00", available: "0.00", target: "5200.00" },
    { bucket: "eating-out", name: "Eating out", group: "Lifestyle", assigned: "800.00", activity: "-912.50", available: "-112.50", target: "800.00" },
    { bucket: "transport", name: "Transport", group: "Essentials", assigned: "500.00", activity: "-231.00", available: "269.00", target: null },
    { bucket: "savings", name: "Savings", group: "Goals", assigned: "1000.00", activity: "0.00", available: "3400.00", target: "1500.00" },
  ],
};

const entry = (id, date, payee, amount, bucket, shares) => ({
  id,
  kind: "expense",
  date,
  payee,
  amount,
  currency: "ILS",
  paid_by: { yarden: amount },
  shares: shares ?? [
    { person: "yarden", amount: (Number(amount) / 2).toFixed(2), bucket },
    { person: "dana", amount: (Number(amount) / 2).toFixed(2), bucket },
  ],
  note: null,
  tags: [],
  rule: "split-5050",
});

const entries = {
  entries: [
    entry("01K9VYQ2N3X8R4T7B0M6D5C1FA", "2026-07-27", "שופרסל דיל", "-284.51", "groceries"),
    entry("01K9VYQ2N3X8R4T7B0M6D5C1FB", "2026-07-26", "קפה גרג", "-50.00", "eating-out"),
    entry("01K9VYQ2N3X8R4T7B0M6D5C1FC", "2026-07-25", "Rav Kav", "-231.00", "transport"),
    entry("01K9VYQ2N3X8R4T7B0M6D5C1FD", "2026-07-01", "Rent", "-5200.00", "rent"),
  ],
  total: 4,
};

const balances = {
  currency: "ILS",
  balances: [
    { person: "yarden", net: "1287.26" },
    { person: "dana", net: "-1287.26" },
  ],
  settle_up: [{ payer: "dana", payee: "yarden", amount: "1287.26" }],
};

const rules = [
  { id: "groceries", when: { payee_contains: "שופרסל", tag: null, paid_by: null, min_amount: null }, split: { yarden: "0.5", dana: "0.5" }, bucket: { yarden: "groceries", dana: "groceries" } },
  { id: "split-5050", when: { payee_contains: null, tag: null, paid_by: null, min_amount: null }, split: { yarden: "0.5", dana: "0.5" }, bucket: {} },
];

const repos = [
  { full_name: "Yarden-zamir/budget-joint", private: true, description: "Household budget data", is_budget: true, connected: true },
  { full_name: "Yarden-zamir/budget-travel", private: true, description: null, is_budget: true, connected: false },
  { full_name: "Yarden-zamir/dotfiles", private: false, description: "configs", is_budget: false, connected: false },
];

const collaborators = [
  { login: "Yarden-zamir", name: "Yarden", avatar_url: null, permission: "admin", invited: false, is_member: true },
  { login: "dana-example", name: "Dana", avatar_url: null, permission: "write", invited: true, is_member: true },
];

const scheduled = [
  { id: "rent", name: "Rent", payee: "Landlord", amount: "-5200.00", currency: "ILS", kind: "expense",
    recurrence: { cadence: "monthly", day: 1, interval: 1 }, starts: "2026-01-01", ends: null,
    last_posted: "2026-07-01", paused: false, paid_by: {}, shares: [], bucket: "rent", note: null, tags: [] },
  { id: "salary", name: "Salary", payee: "Employer", amount: "12000.00", currency: "ILS", kind: "income",
    recurrence: { cadence: "monthly", day: 28, interval: 1 }, starts: "2026-01-01", ends: null,
    last_posted: null, paused: false, paid_by: {}, shares: [], bucket: null, note: null, tags: [] },
];

const dueList = {
  through: "2026-08-16",
  due: [
    { scheduled_id: "rent", name: "Rent", payee: "Landlord", amount: "-5200.00", currency: "ILS", kind: "expense", date: "2026-08-01", overdue: true },
    { scheduled_id: "salary", name: "Salary", payee: "Employer", amount: "12000.00", currency: "ILS", kind: "income", date: "2026-08-28", overdue: false },
  ],
};

const historyFeed = {
  undoable: "aaaaaaa1",
  events: [
    { sha: "aaaaaaa1c0ffee", subject: "entry: add שופרסל דיל 284.51 ILS", kind: "entry", author: "Yarden", actor: "dev", date: "2026-08-02T09:12:00Z", entry_id: null, mine: true },
    { sha: "bbbbbbb2c0ffee", subject: "assign: yarden groceries 2000.00 for 2026-08", kind: "assignment", author: "Yarden", actor: "dev", date: "2026-08-01T20:03:00Z", entry_id: null, mine: true },
    { sha: "ccccccc3c0ffee", subject: "bucket: yarden savings", kind: "bucket", author: "Dana", actor: "dana-example", date: "2026-07-30T11:40:00Z", entry_id: null, mine: false },
  ],
};

const ROUTES = [
  [/\/history/, () => historyFeed],
  [/\/suggest/, () => ({ payee: null, amount: null, bucket: null, shares: [], items: [], place_name: null, confidence: 0, basis: "none", reason: "Nothing similar yet.", sample_size: 0 })],
  [/\/entries\/payees/, () => []],
  [/\/scheduled\/due/, () => dueList],
  [/\/budgets\/joint\/scheduled/, () => scheduled],
  [/\/github\/repos/, () => repos],
  [/\/github\/users/, () => []],
  [/\/budgets\/joint\/collaborators/, () => collaborators],
  [/\/api\/v1\/me\/keys$/, () => []],
  [/\/api\/v1\/me$/, () => me],
  [/\/api\/v1\/auth\/config$/, () => ({ login_url: "/api/v1/auth/github/start" })],
  [/\/budgets\/joint\/months\//, () => month],
  [/\/budgets\/joint\/entries/, () => entries],
  [/\/budgets\/joint\/buckets/, () => buckets],
  [/\/budgets\/joint\/balances/, () => balances],
  [/\/budgets\/joint\/members/, () => budget.members],
  [/\/budgets\/joint\/rules/, () => rules],
  [/\/api\/v1\/budgets$/, () => [budget]],
];

function serve() {
  const server = createServer(async (req, res) => {
    const path = (req.url ?? "/").split("?")[0];
    let file = join(DIST, path === "/" ? "index.html" : path);
    try {
      const body = await readFile(file);
      res.writeHead(200, { "content-type": TYPES[extname(file)] ?? "application/octet-stream" });
      res.end(body);
    } catch {
      const body = await readFile(join(DIST, "index.html"));
      res.writeHead(200, { "content-type": "text/html" });
      res.end(body);
    }
  });
  return new Promise((ok) => server.listen(PORT, () => ok(server)));
}

const SCREENS = [
  ["month", "/"],
  ["entries", "/entries"],
  ["balances", "/balances"],
  ["scheduled", "/scheduled"],
  ["rules", "/rules"],
  ["settings", "/settings"],
  ["history", "/history"],
];

const VIEWPORTS = [
  ["desktop", { width: 1280, height: 900 }],
  ["mobile", { width: 390, height: 844 }],
];

const server = await serve();
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();

for (const [device, viewport] of VIEWPORTS) {
  for (const language of ["he", "en"]) {
    const context = await browser.newContext({ viewport, deviceScaleFactor: 2 });
    await context.addInitScript((lang) => {
      localStorage.setItem("money.language", lang);
      localStorage.setItem("money.budget", "joint");
    }, language);

    await context.route("**/api/**", async (route) => {
      const url = route.request().url();
      const match = ROUTES.find(([pattern]) => pattern.test(url));
      if (!match) return route.fulfill({ status: 404, body: '{"error":{"code":"nf","message":"no stub"}}' });
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(match[1]()),
      });
    });

    const page = await context.newPage();
    for (const [name, path] of SCREENS) {
      await page.goto(`http://localhost:${PORT}${path}`, { waitUntil: "networkidle" });
      await page.waitForTimeout(250);
      await page.screenshot({
        path: join(OUT, `${device}-${language}-${name}.png`),
        fullPage: true,
      });
    }

    // The quick-add dialog is reachable from every screen, so it gets its own shot.
    await page.goto(`http://localhost:${PORT}/`, { waitUntil: "networkidle" });
    await page.getByRole("button", { name: /add entry|הוספת תנועה/i }).first().click();
    await page.waitForTimeout(300);
    await page.screenshot({ path: join(OUT, `${device}-${language}-quickadd.png`) });
    await context.close();
  }
}

await browser.close();
server.close();
console.log(`wrote screenshots to ${OUT}`);
