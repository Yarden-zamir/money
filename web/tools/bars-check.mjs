/**
 * Asserts the width of every funder's bar, against cases that were once wrong.
 *
 * A bar is the main visual on the main screen and is derived from two numbers, so it goes
 * wrong quietly: a bar of the wrong length still looks like a bar. These cases are the ones
 * the old `target ?? assigned` denominator got wrong, plus the ones it got right, so a future
 * change has to keep both.
 *
 * Each case is now one funder in a shared bucket, which is also what the length means: a
 * person's own spending measured against their own contribution.
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

/** Each case is [id, assigned, activity, available, target, expected percent]. */
const CASES = [
  // id                 assigned  activity   available  target    want
  ["normal",            "2000",   "-1642.30", "357.70",  "2000",   82],
  ["paid-in-full",      "5200",   "-5200",    "0",       "5200",  100],
  ["no-target",         "500",    "-231",     "269",     null,     46],
  ["overspent",         "800",    "-912.50",  "-112.50", "800",   100],
  ["untouched",         "1000",   "0",        "3400",    "1500",    0],

  // Spent from money carried over, nothing assigned this month. The old denominator was
  // `assigned` = 0, so this rendered empty while 60% of the envelope was gone.
  ["carryover-spend",   "0",      "-300",     "200",     null,     60],

  // Overspent with nothing assigned and no target: the old code produced a bar of zero
  // width, so the one state that needs acting on was invisible.
  ["overspent-nothing", "0",      "-50",      "-50",     null,    100],

  // Holds more than its target. The old denominator was the target, so this filled completely
  // while a third of the envelope was still available.
  ["over-target",       "3000",   "-2000",    "1000",    "1000",   67],

  // Nearly empty relative to what it held.
  ["low",               "1000",   "-950",     "50",      "1000",   95],
];

const me = { login: "dev", name: "Y", email: "d@l", avatar_url: null };
const budget = {
  slug: "joint", name: "Household", repo: "y/b", currency: "ILS", branch: "main",
  members: [{ person: "yarden", name: "Y", github: "dev" }], me: "yarden", can_write: true,
};

/** One funder per bucket, so each bar is that case in isolation. */
const funderFor = ([, assigned, activity, available]) => [
  { person: "yarden", split: "1", assigned, activity, available },
];

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
        buckets: CASES.map((entry) => {
          const [id, assigned, activity, available, target] = entry;
          return {
            bucket: id, name: id, group: "All", assigned, activity, available, target,
            funders: funderFor(entry),
          };
        }),
      };
    } else if (path.includes("/buckets")) {
      body = CASES.map(([id], i) => ({
        id, name: id, group: "All", target: null, archived: false, order: i,
        split: { yarden: "1" },
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

// The rendered fill for each row's single funder: its inline width, and whether it carries
// the hatch that marks an overspent funder without relying on colour.
const rendered = await page.locator("[data-bucket]").evaluateAll((rows) =>
  Object.fromEntries(
    rows.map((row) => {
      const fill = row.querySelector("[style*='width']");
      return [
        row.dataset.bucket,
        { width: fill?.style.width ?? "", hatched: fill?.classList.contains("bar-overspent") },
      ];
    }),
  ),
);

let failures = 0;
for (const [id, , , available, , want] of CASES) {
  const got = rendered[id];
  if (!got) {
    console.log(`  ${id.padEnd(18)} MISSING from the page`);
    failures += 1;
    continue;
  }
  const width = Number.parseInt(got.width, 10);
  const wantHatch = Number(available) < 0;
  const okWidth = width === want;
  const okHatch = Boolean(got.hatched) === wantHatch;
  const mark = okWidth && okHatch ? "ok   " : "FAIL ";
  console.log(
    `  ${mark} ${id.padEnd(18)} ${String(width).padStart(3)}% (want ${String(want).padStart(3)}%)` +
      `  ${okHatch ? (wantHatch ? "hatched" : "plain") : "WRONG hatch"}`,
  );
  if (!okWidth || !okHatch) failures += 1;
}

await browser.close();
server.close();
console.log(failures === 0 ? "\nPASS" : `\nFAIL (${failures} of ${CASES.length})`);
process.exit(failures === 0 ? 0 : 1);
