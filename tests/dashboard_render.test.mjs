import { createServer } from "node:http";
import test from "node:test";
import assert from "node:assert/strict";
import { chromium } from "playwright-core";
import worker from "../outputs/sonkuki_gsc_insights_site/worker/index.js";
import { SNAPSHOT } from "../outputs/sonkuki_gsc_insights_site/worker/dashboard_snapshot.js";

const startWorkerServer = async () => {
  const server = createServer(async (request, response) => {
    const origin = `http://${request.headers.host}`;
    const workerResponse = await worker.fetch(new Request(new URL(request.url, origin), {
      method: request.method,
      headers: request.headers,
    }));

    response.writeHead(workerResponse.status, Object.fromEntries(workerResponse.headers));
    response.end(Buffer.from(await workerResponse.arrayBuffer()));
  });

  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      server.off("error", reject);
      resolve();
    });
  });

  const { port } = server.address();
  return {
    url: `http://127.0.0.1:${port}`,
    close: () => new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve())),
  };
};

const expectedPriceDifference = (unit) => {
  if (!(unit.priceMedian > 0 && unit.compMedianPrice > 0)) return "—";
  const delta = (unit.priceMedian - unit.compMedianPrice) / unit.compMedianPrice;
  return `${delta > 0 ? "高于竞品 " : "低于竞品 "}${Math.round(Math.abs(delta) * 100)}%`;
};

test("benchmark renders price-difference values and tones in the browser DOM", async (t) => {
  const server = await startWorkerServer();
  t.after(() => server.close());

  let browser;
  try {
    browser = await chromium.launch({
      executablePath: chromium.executablePath(),
      headless: true,
    });
  } catch (error) {
    if (error?.message?.includes("executable doesn't exist")) {
      t.skip("Playwright Chromium is not installed; ego-lite covers browser validation");
      return;
    }
    throw error;
  }
  t.after(() => browser.close());

  const page = await browser.newPage();
  await page.goto(`${server.url}/?page=benchmark`, { waitUntil: "networkidle" });
  await page.getByText("Snapshot warning", { exact: true }).waitFor();

  const benchmark = page.locator('section[data-page-view="market"].active #benchmark-grid');
  const productBenchmarkSummary = benchmark.locator("details > summary").filter({ hasText: "展开完整商品对标" });
  const productBenchmark = productBenchmarkSummary.locator("..");
  await productBenchmarkSummary.click();
  await assert.doesNotReject(() => productBenchmark.locator("table.data-table").waitFor());

  const rendered = await benchmark.evaluate((element) => ({
    text: element.textContent,
    priceDifferences: [...element.querySelectorAll("table.data-table")].flatMap((table) => {
      const headers = [...table.querySelectorAll("thead th")].map((cell) => cell.textContent?.trim());
      const priceDifferenceIndex = headers.findIndex((header) => header === "价格差 / Price diff");
      return priceDifferenceIndex < 0
        ? []
        : [...table.querySelectorAll("tbody tr")].map((row) => {
            const cell = row.querySelectorAll("td")[priceDifferenceIndex];
            return { text: cell?.textContent?.trim(), className: cell?.querySelector("span")?.className || "" };
          });
    }),
  }));

  assert.doesNotMatch(rendered.text, /undefined|NaN|\[object Object\]/);
  assert.equal(rendered.priceDifferences.length, SNAPSHOT.marketBenchmark.units.length);
  assert.deepEqual(
    rendered.priceDifferences.map(({ text }) => text),
    SNAPSHOT.marketBenchmark.units.map(expectedPriceDifference),
  );
  assert.ok(
    rendered.priceDifferences.some(({ className }) => /\b(?:pill|warn)\b/.test(className)),
    "at least one price-difference cell should carry a tone class",
  );
});
