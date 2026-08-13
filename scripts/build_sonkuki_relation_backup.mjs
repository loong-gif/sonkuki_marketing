import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = "/private/tmp";
const outputDir = "/Users/wyl/sonkuki/outputs/sonkuki_nocodb_relation_backup";
const outputFilename = "sonkuki_nocodb_relation_backup_v2.xlsx";

async function loadPaged(prefix) {
  const names = (await fs.readdir(root))
    .filter((name) => name.startsWith(prefix) && name.endsWith(".json"))
    .sort((a, b) => Number(a.match(/_(\d+)\.json$/)?.[1] ?? 0) - Number(b.match(/_(\d+)\.json$/)?.[1] ?? 0));
  const rows = [];
  for (const name of names) {
    const payload = JSON.parse(await fs.readFile(path.join(root, name), "utf8"));
    rows.push(...(payload.list ?? []));
  }
  return rows;
}

function orderedHeaders(rows) {
  const preferred = ["Id", "CreatedAt", "UpdatedAt", "site_url（属性）", "date", "page", "query", "clicks", "impressions", "ctr", "position"];
  const keys = new Set(rows.flatMap((row) => Object.keys(row)));
  return [...preferred.filter((key) => keys.has(key)), ...[...keys].filter((key) => !preferred.includes(key))];
}

function matrix(rows, headers) {
  return [headers, ...rows.map((row) => headers.map((header) => row[header] ?? null))];
}

function styleSheet(sheet, headerRow, freezeRows = 1) {
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(freezeRows);
  headerRow.format = {
    fill: "#1F4E78",
    font: { bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
  };
  headerRow.format.rowHeight = 24;
  sheet.getUsedRange()?.format.autofitColumns();
}

const scdRows = await loadPaged("scd_plan_");
const queryRows = await loadPaged("query_plan_");
if (scdRows.length !== 12389 || queryRows.length !== 2013) {
  throw new Error(`Unexpected source counts: SCD_Raw=${scdRows.length}, Query_Summary=${queryRows.length}`);
}

const pageStats = new Map();
for (const row of scdRows) {
  const page_url = String(row.page ?? "").trim();
  if (!page_url) continue;
  const current = pageStats.get(page_url) ?? { Rows: 0, Clicks: 0, Impressions: 0, PositionWeight: 0, Queries: new Set() };
  const clicks = Number(row.clicks ?? 0);
  const impressions = Number(row.impressions ?? 0);
  current.Rows += 1;
  current.Clicks += clicks;
  current.Impressions += impressions;
  current.PositionWeight += Number(row.position ?? 0) * impressions;
  current.Queries.add(String(row.query ?? "").trim());
  pageStats.set(page_url, current);
}
const pages = [...pageStats.keys()].sort().map((page_url, index) => {
  const stats = pageStats.get(page_url);
  return {
    Id: index + 1,
    page_url,
    Rows: stats.Rows,
    Clicks: stats.Clicks,
    Impressions: stats.Impressions,
    CTR: stats.Impressions ? stats.Clicks / stats.Impressions : 0,
    Weighted_Avg_Position: stats.Impressions ? stats.PositionWeight / stats.Impressions : 0,
    Queries: stats.Queries.has("") ? stats.Queries.size - 1 : stats.Queries.size,
  };
});

const workbook = Workbook.create();
const raw = workbook.worksheets.add("SCD_Raw_Backup");
const page = workbook.worksheets.add("Page_Summary");
const query = workbook.worksheets.add("Query_Summary_Backup");
const notes = workbook.worksheets.add("Migration_Notes");

const rawHeaders = orderedHeaders(scdRows);
raw.getRangeByIndexes(0, 0, scdRows.length + 1, rawHeaders.length).values = matrix(scdRows, rawHeaders);
styleSheet(raw, raw.getRangeByIndexes(0, 0, 1, rawHeaders.length));
raw.getRange("E2:E12390").setNumberFormat("yyyy-mm-dd");

const pageHeaders = ["Id", "page_url", "Rows", "Clicks", "Impressions", "CTR", "Weighted_Avg_Position", "Queries"];
page.getRangeByIndexes(0, 0, pages.length + 1, pageHeaders.length).values = matrix(pages, pageHeaders);
styleSheet(page, page.getRange("A1:H1"));
page.getRange("B:B").format.columnWidth = 70;
page.getRange(`C2:E${pages.length + 1}`).setNumberFormat("#,##0");
page.getRange(`F2:F${pages.length + 1}`).setNumberFormat("0.00%");
page.getRange(`G2:G${pages.length + 1}`).setNumberFormat("0.0");
page.getRange(`H2:H${pages.length + 1}`).setNumberFormat("#,##0");

const queryHeaders = ["Id", "分组键", "Rows", "Clicks", "Impressions", "CTR", "Weighted_Avg_Position", "Pages"];
query.getRangeByIndexes(0, 0, queryRows.length + 1, queryHeaders.length).values = matrix(queryRows, queryHeaders);
styleSheet(query, query.getRange("A1:H1"));
query.getRange("B:B").format.columnWidth = 55;

const noteRows = [
  ["Snapshot purpose", "Rollback snapshot before NocoDB relation migration"],
  ["Source scope", "sc-domain:sonkuki.com"],
  ["SCD_Raw rows", scdRows.length],
  ["Unique pages", pages.length],
  ["Query_Summary rows", queryRows.length],
  ["Raw columns to preserve", "page -> page_raw; query -> query_raw"],
  ["Page summary fields", "Rows, Clicks, Impressions, CTR, Weighted_Avg_Position, Queries"],
  ["Planned relations", "SCD_Raw.page -> Page; SCD_Raw.query -> Query_Summary"],
  ["Generated at", new Date()],
];
notes.getRangeByIndexes(0, 0, noteRows.length, 2).values = noteRows;
styleSheet(notes, notes.getRange("A1:B1"), 0);
notes.getRange("A:A").format.columnWidth = 28;
notes.getRange("B:B").format.columnWidth = 75;
notes.getRange("B8").setNumberFormat("yyyy-mm-dd hh:mm:ss");

await fs.mkdir(outputDir, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(path.join(outputDir, outputFilename));
console.log(JSON.stringify({ output: path.join(outputDir, outputFilename), scdRows: scdRows.length, pages: pages.length, queryRows: queryRows.length }));
