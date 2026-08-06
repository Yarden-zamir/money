/**
 * Asserts the funding bar: segment widths per funder against the target.
 *
 * The bar's one meaning is "how funded is this envelope, and by whom" — the track is the
 * target, each segment a funder's contribution this month. A bar of the wrong length still
 * looks like a bar, so the widths are asserted, not eyeballed:
 *
 * - segments are proportional to contributions;
 * - an overfunded bucket rescales rather than clipping whoever funded last;
 * - no target means the segments fill the track (the funding mix);
 * - nothing funded means an empty track, whatever was spent.
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

/** [bucket, target, {person: assigned}, expected {person: width%}] */
const CASES = [
  // Half funded by two people unevenly: widths are their share of the TARGET.
  ["half-funded", "2000", { a: "600", b: "400" }, { a: 30, b: 20 }],
  // Fully funded in the split ratio.
  ["funded", "1000", { a: "750", b: "250" }, { a: 75, b: 25 }],
  // Overfunded: track grows to the total, so segments stay proportional (2400 of 2400).
  ["overfunded", "2000", { a: "1600", b: "800" }, { a: 66.7, b: 33.3 }],
  // No target: the bar is the funding mix, filling the track.
  ["no-target", null, { a: "300", b: "100" }, { a: 75, b: 25 }],
  // Nothing funded: empty track, even though there was spending.
  ["unfunded", "500", {}, {}],
];

const me = { login: "dev", name: "A", email: "d@l", avatar_url: null };
const budget = {
  slug: "joint", name: "Household", repo: "y/b", currency: "ILS", branch: "main",
  members: [{ person: "a", name: "A", github: "dev" }, { person: "b", name: "B" }],
  me: "a", can_write: true,
};

const funders = (amounts) =>
  ["a", "b"].map((person) => ({
    person, split: "0.5",
    assigned: amounts[person] ?? "0.00",
    activity: "-50.00",
    available: String(Number(amounts[person] ?? 0) - 50),
  }));

const server = createServer(async (req, res) => {
  const path = (req.url ?? "/").split("?")[0];
  if (path.startsWith("/api/")) {
    let body = [];
    if (path.endsWith("/me")) body = me;
    else if (path.endsWith("/budgets")) body = [budget];
    else if (path.endsWith("/auth/config")) body = { login_url: "/x" };
    else if (path.includes("/months/")) {
      body = {
        person: "a", month: MONTH, currency: "ILS",
        ready_to_assign: "0.00", income: "0.00", assigned: "0.00",
        buckets: CASES.map(([id, target, amounts]) => ({
          bucket: id, name: id, group: "All",
          assigned: "0.00", activity: "-100.00", available: "0.00", target,
          funders: funders(amounts),
        })),
      };
    } else if (path.includes("/buckets")) {
      body = CASES.map(([id], i) => ({
        id, name: id, group: "All", target: null, archived: false, order: i,
        split: { a: "0.5", b: "0.5" },
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

const rendered = await page.locator("[data-bucket]").evaluateAll((rows) =>
  Object.fromEntries(
    rows.map((row) => [
      row.dataset.bucket,
      Object.fromEntries(
        [...row.querySelectorAll("[data-person]")].map((el) => [
          el.dataset.person,
          Number.parseFloat(el.style.width),
        ]),
      ),
    ]),
  ),
);

let failures = 0;
for (const [id, , , want] of CASES) {
  const got = rendered[id] ?? {};
  const people = new Set([...Object.keys(want), ...Object.keys(got)]);
  let ok = true;
  const parts = [];
  for (const person of people) {
    const width = got[person];
    const expected = want[person];
    const fine =
      expected === undefined
        ? width === undefined
        : width !== undefined && Math.abs(width - expected) < 0.5;
    if (!fine) ok = false;
    parts.push(`${person}=${width?.toFixed(1) ?? "—"}% (want ${expected?.toFixed(1) ?? "—"})`);
  }
  if (people.size === 0) parts.push("empty (want empty)");
  console.log(`  ${ok ? "ok   " : "FAIL "} ${id.padEnd(12)} ${parts.join("  ")}`);
  if (!ok) failures += 1;
}

await browser.close();
server.close();
console.log(failures === 0 ? "\nPASS" : `\nFAIL (${failures} of ${CASES.length})`);
process.exit(failures === 0 ? 0 : 1);
