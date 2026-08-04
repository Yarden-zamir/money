/**
 * Asserts the width and colour of every bucket bar, against cases that were wrong.
 *
 * The bar is the main visual on the main screen and it is derived from three numbers, so it
 * goes wrong quietly: a bar of the wrong length still looks like a bar. These cases are the
 * ones the old `target ?? assigned` denominator got wrong, plus the ones it got right, so a
 * future change has to keep both.
 */
import { chromium } from "playwright";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { join, extname, resolve } from "node:path";

const DIST = resolve(import.meta.dirname, "..", "dist");
const PORT = 4604;
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".map": "application/json" };

const now = new Date();
const MONTH = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;

/**
 * Each case is [id, assigned, activity, available, target, expected percent, expected tone].
 *
 * `available` carries over between months; `assigned` is only this month's. That gap is what
 * every broken case below has in common.
 */
const CASES = [
  // id                 assigned  activity   available  target    want  tone
  ["normal",            "2000",   "-1642.30", "357.70",  "2000",   82,  "positive"],
  ["paid-in-full",      "5200",   "-5200",    "0",       "5200",  100,  "ink-muted"],
  ["no-target",         "500",    "-231",     "269",     null,     46,  "positive"],
  ["overspent",         "800",    "-912.50",  "-112.50", "800",   100,  "negative"],
  ["untouched",         "1000",   "0",        "3400",    "1500",    0,  "positive"],

  // Spent from money carried over, nothing assigned this month. The old denominator was
  // `assigned` = 0, so this rendered empty while 60% of the envelope was gone.
  ["carryover-spend",   "0",      "-300",     "200",     null,     60,  "positive"],

  // Overspent with nothing assigned and no target: the old code produced a red bar of zero
  // width, so the one state that needs acting on was invisible.
  ["overspent-nothing", "0",      "-50",      "-50",     null,    100,  "negative"],

  // Holds more than its target. The old denominator was the target, so this filled completely
  // while a third of the envelope was still available.
  ["over-target",       "3000",   "-2000",    "1000",    "1000",   67,  "positive"],

  // Nearly empty relative to what it held, which is what "low" should mean.
  ["low",               "1000",   "-950",     "50",      "1000",   95,  "warning"],
];

const me = { login: "dev", name: "Y", email: "d@l", avatar_url: null };
const budget = {
  slug: "joint", name: "Household", repo: "y/b", currency: "ILS", branch: "main",
  members: [{ person: "yarden", name: "Y", github: "dev" }], me: "yarden", can_write: true,
};

const server = createServer(async (req, res) => {
  const path = (req.url ?? "/").split("?")[0];
  if (path.startsWith("/api/")) {
    let body = [];
    if (path.endsWith("/me")) body = me;
    else if (path.endsWith("/budgets")) body = [budget];
    else if (path.endsWith("/auth/config")) body = { login_url: "/x" };
    else if (path.includes("/close")) body = { closed: false, tag: null, sha: null };
    else if (path.includes("/months/")) {
      body = {
        person: "yarden", month: MONTH, currency: "ILS",
        ready_to_assign: "0.00", income: "0.00", assigned: "0.00",
        buckets: CASES.map(([id, assigned, activity, available, target]) => ({
          bucket: id, name: id, group: "All", assigned, activity, available, target,
        })),
      };
    } else if (path.includes("/buckets")) {
      body = CASES.map(([id], i) => ({
        id, name: id, group: "All", target: null, archived: false, order: i,
      }));
    }
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
const context = await browser.newContext({ viewport: { width: 1280, height: 1400 } });
await context.addInitScript(() => {
  localStorage.setItem("money.language", "en");
  localStorage.setItem("money.budget", "joint");
});
const page = await context.newPage();
await page.goto(`http://localhost:${PORT}/`, { waitUntil: "networkidle" });
await page.waitForSelector("[data-bucket]");

// Read the rendered fill of each row: its inline width and the tone class it carries.
const rendered = await page.locator("[data-bucket]").evaluateAll((rows) =>
  Object.fromEntries(
    rows.map((row) => {
      const fill = row.querySelector("[style*='width']");
      return [
        row.dataset.bucket,
        { width: fill?.style.width ?? "", className: fill?.className ?? "" },
      ];
    }),
  ),
);

let failures = 0;
for (const [id, , , , , want, tone] of CASES) {
  const got = rendered[id];
  if (!got) {
    console.log(`  ${id.padEnd(18)} MISSING from the page`);
    failures += 1;
    continue;
  }
  const width = Number.parseInt(got.width, 10);
  const okWidth = width === want;
  const okTone = got.className.includes(tone);
  const mark = okWidth && okTone ? "ok   " : "FAIL ";
  console.log(
    `  ${mark} ${id.padEnd(18)} ${String(width).padStart(3)}% (want ${String(want).padStart(3)}%)` +
      `  ${okTone ? tone : `${got.className.match(/bg-[\w/-]+/)?.[0]} (want ${tone})`}`,
  );
  if (!okWidth || !okTone) failures += 1;
}

await browser.close();
server.close();
console.log(failures === 0 ? "\nPASS" : `\nFAIL (${failures} of ${CASES.length})`);
process.exit(failures === 0 ? 0 : 1);
